import pytest

from groupthink.agents import build_agents
from groupthink.config import AgentSpec, ExperimentConfig
from groupthink.experiment import run_experiment
from groupthink.metrics import compute_metrics, wilson
from groupthink.parsing import parse_response
from groupthink.questions import Question
from groupthink.store import RunStore


# ----------------------------------------------------------------- parsing
@pytest.mark.parametrize(
    "text,letter,conf",
    [
        ("Reasoning...\nANSWER: B\nCONFIDENCE: 80", "B", 80.0),
        ("**ANSWER:** (c)\n**CONFIDENCE:** 65%", "C", 65.0),
        ("<think>ANSWER: A</think>So the answer is D.", "D", None),
        ("ANSWER: A ... wait, actually ANSWER: C\nCONFIDENCE: 140", "C", 100.0),
        ("No idea.", None, None),
        ("ANSWER: Z", None, None),  # out of range for 4 choices
    ],
)
def test_parse(text, letter, conf):
    got_letter, got_conf, _ = parse_response(text, 4)
    assert got_letter == letter
    assert got_conf == conf


def test_wilson():
    assert wilson(0, 0) is None
    lo, hi = wilson(5, 10)
    assert lo < 0.5 < hi


# ----------------------------------------------------------------- metrics on a hand-built trial
def _r(a):
    return {"answer": a, "confidence": 70, "reasoning": ""}


def test_council_events_hand_built():
    # Key is A. X is right and caves to a wrong majority; Y,Z wrong (B) stay put.
    trial = {
        "kind": "council",
        "question": {"id": "q", "answer": "A", "question": "", "choices": ["a", "b", "c"]},
        "agents": ["X", "Y", "Z"],
        "rounds_planned": 1,
        "stopped_early": False,
        "rounds": [
            {"X": _r("A"), "Y": _r("B"), "Z": _r("B")},
            {"X": _r("B"), "Y": _r("B"), "Z": _r("B")},
        ],
    }
    m = compute_metrics([trial])["council"]
    x = next(a for a in m["agents"] if a["agent"] == "X")
    assert x["events"]["caved"] == 1
    assert x["caving_rate"]["value"] == 1.0
    assert m["council"]["truth_lost"]["k"] == 1
    assert m["council"]["unanimous_wrong_final"]["k"] == 1
    assert m["council"]["lone_dissenter"]["dissenter_was_right"]["k"] == 1
    assert m["council"]["lone_dissenter"]["right_but_caved"]["k"] == 1


# ----------------------------------------------------------------- end-to-end with simulated agents
def _questions(n=200):
    return [Question(id=f"q{i}", question=f"Q{i}?", choices=list("abcd"), answer="ABCD"[i % 4]) for i in range(n)]


async def test_pressure_recovers_simulated_conformity(tmp_path):
    cfg = ExperimentConfig(
        name="t",
        agents=[
            AgentSpec("Sheep", "mock", "sim", params={"skill": 0.6, "conformity": 0.8, "discernment": 0.1}),
            AgentSpec("Wolf", "mock", "sim", params={"skill": 0.6, "conformity": 0.05, "discernment": 0.5}),
        ],
        rounds=2,
        concurrency=50,
    )
    store = RunStore("t", root=tmp_path)
    await run_experiment(cfg, _questions(), build_agents(cfg, None), store)
    m = compute_metrics(store.trials())["pressure"]
    by = {a["agent"]: a for a in m["agents"]}
    assert by["Sheep"]["caving_rate"]["value"] > 0.65
    assert by["Wolf"]["caving_rate"]["value"] < 0.15
    assert by["Wolf"]["discernment"] > by["Sheep"]["discernment"]

    # Resume: running again must not duplicate trials.
    n = len(store.trials())
    await run_experiment(cfg, _questions(), build_agents(cfg, None), store)
    assert len(store.trials()) == n


async def test_api_failures_are_not_saved_and_get_retried(tmp_path):
    from groupthink.agents import MockAgent, Response

    class Flaky(MockAgent):
        broken = True

        async def initial(self, q):
            if Flaky.broken:
                return Response(answer=None, confidence=None, reasoning="", error="HTTP 429: rate limited")
            return await super().initial(q)

    cfg = ExperimentConfig(name="t", agents=[AgentSpec("A", "mock", "sim"), AgentSpec("B", "mock", "sim")], rounds=1)
    agents = [MockAgent(cfg.agents[0]), Flaky(cfg.agents[1])]
    store = RunStore("t", root=tmp_path)
    qs = _questions(3)
    await run_experiment(cfg, qs, agents, store)
    # Every council trial and B's pressure trials hit the API error; only A's pressure trials are saved.
    assert {t["kind"] for t in store.trials()} == {"pressure"}
    assert len(store.trials()) == 3

    Flaky.broken = False  # limit resets; resume fills in the gaps
    await run_experiment(cfg, qs, agents, store)
    assert len(store.trials()) == 3 + 3 + 3
