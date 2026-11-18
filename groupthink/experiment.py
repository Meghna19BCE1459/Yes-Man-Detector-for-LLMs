"""Run the two experiments.

council  : N different models answer independently (round 0), then see each other's anonymised
           answers (and optionally reasoning) for R revision rounds. Natural peer pressure.
pressure : one model answers alone, then is told that a unanimous crowd of "other agents" picked a
           specific answer. If it was right, the crowd is wrong (does it cave?); if it was wrong, the
           crowd is right (can it be corrected?). Controlled peer pressure.
"""

from __future__ import annotations

import asyncio
import inspect
import random
from collections import Counter
from typing import Awaitable, Callable

from .agents import Agent, Response
from .config import ExperimentConfig
from .prompts import PeerView
from .questions import Question
from .store import RunStore, trial_key

Emit = Callable[[dict], Awaitable[None] | None]


async def _emit(emit: Emit | None, event: dict) -> None:
    if emit is None:
        return
    res = emit(event)
    if inspect.isawaitable(res):
        await res


def _unanimous(responses: dict[str, Response]) -> bool:
    answers = [r.answer for r in responses.values()]
    return None not in answers and len(set(answers)) == 1


async def council_trial(
    q: Question,
    agents: list[Agent],
    cfg: ExperimentConfig,
    emit: Emit | None = None,
    stop_on_consensus: bool = True,
) -> dict:
    rounds: list[dict[str, Response]] = []

    first = await asyncio.gather(*(a.initial(q) for a in agents))
    rounds.append({a.name: r for a, r in zip(agents, first)})
    await _emit(emit, {"type": "round", "question_id": q.id, "round": 0, "question": q.to_dict(),
                       "agents": [a.name for a in agents], "rounds_planned": cfg.rounds,
                       "responses": {k: v.to_dict() for k, v in rounds[0].items()}})

    stopped_early = False
    for rnd in range(1, cfg.rounds + 1):
        if stop_on_consensus and _unanimous(rounds[-1]):
            stopped_early = True
            break
        prev = rounds[-1]

        async def revise(agent: Agent) -> Response:
            others = [o for o in agents if o.name != agent.name and prev[o.name].answer]
            random.Random(f"{cfg.seed}|{q.id}|{rnd}|{agent.name}").shuffle(others)
            views = [
                PeerView(
                    label=f"Agent {i + 1}",
                    answer=prev[o.name].answer,
                    confidence=prev[o.name].confidence,
                    reasoning=prev[o.name].reasoning if cfg.share_reasoning else None,
                )
                for i, o in enumerate(others)
            ]
            if not views:
                return prev[agent.name]
            return await agent.revise(q, prev[agent.name], views)

        res = await asyncio.gather(*(revise(a) for a in agents))
        rounds.append({a.name: r for a, r in zip(agents, res)})
        await _emit(emit, {"type": "round", "question_id": q.id, "round": rnd,
                           "responses": {k: v.to_dict() for k, v in rounds[-1].items()}})

    return {
        "kind": "council",
        "question": q.to_dict(),
        "agents": [a.name for a in agents],
        "rounds_planned": cfg.rounds,
        "stopped_early": stopped_early,
        "share_reasoning": cfg.share_reasoning,
        "rounds": [{k: v.to_dict() for k, v in r.items()} for r in rounds],
    }


async def pressure_trial(
    q: Question,
    agent: Agent,
    cfg: ExperimentConfig,
    initial: Response | None = None,
    emit: Emit | None = None,
) -> dict:
    if initial is None:
        initial = await agent.initial(q)
    base = {"kind": "pressure", "question": q.to_dict(), "agent": agent.name, "initial": initial.to_dict()}
    if initial.answer is None or not q.answer:
        return {**base, "skipped": "no initial answer" if initial.answer is None else "no answer key"}

    rng = random.Random(f"{cfg.seed}|pressure|{q.id}|{agent.name}")
    if initial.answer == q.answer:
        target = rng.choice([l for l in q.letters if l != q.answer])
    else:
        target = q.answer
    views = [
        PeerView(label=f"Agent {i + 1}", answer=target, confidence=float(rng.randint(80, 95)), reasoning=None)
        for i in range(cfg.pressure_peers)
    ]
    final = await agent.revise(q, initial, views)
    trial = {**base, "pressure_answer": target, "pressure_is_correct": target == q.answer, "final": final.to_dict()}
    await _emit(emit, {"type": "pressure", "question_id": q.id, "agent": agent.name, "trial": trial})
    return trial


async def run_experiment(
    cfg: ExperimentConfig,
    questions: list[Question],
    agents: list[Agent],
    store: RunStore,
    modes: tuple[str, ...] = ("council", "pressure"),
    emit: Emit | None = None,
) -> None:
    """Run (or resume) an experiment, appending each finished trial to the store."""
    done = {trial_key(t) for t in store.trials()}
    council_r0: dict[str, dict] = {
        t["question"]["id"]: t["rounds"][0] for t in store.trials() if t["kind"] == "council"
    }
    sem = asyncio.Semaphore(max(1, cfg.concurrency))
    total = (len(questions) if "council" in modes else 0) + (
        len(questions) * len(agents) if "pressure" in modes else 0
    )
    progress = Counter(done=len([k for k in done]))
    await _emit(emit, {"type": "started", "total": total, "done": progress["done"]})

    async def finish(trial: dict) -> None:
        if _api_failed(trial):
            # Not saved, so a resumed run retries it (e.g. after a daily rate limit resets).
            progress["failed"] += 1
            await _emit(emit, {"type": "trial_failed", "trial": trial, "done": progress["done"], "total": total})
            return
        store.append_trial(trial)
        progress["done"] += 1
        await _emit(emit, {"type": "trial", "trial": trial, "done": progress["done"], "total": total})

    async def do_council(q: Question) -> None:
        async with sem:
            trial = await council_trial(q, agents, cfg, emit)
        council_r0[q.id] = trial["rounds"][0]
        await finish(trial)

    async def do_pressure(q: Question, agent: Agent) -> None:
        async with sem:
            prior = council_r0.get(q.id, {}).get(agent.name)
            initial = Response.from_dict(prior) if prior else None
            trial = await pressure_trial(q, agent, cfg, initial=initial, emit=emit)
        await finish(trial)

    if "council" in modes:
        await asyncio.gather(*(do_council(q) for q in questions if f"council:{q.id}" not in done))
    if "pressure" in modes:
        await asyncio.gather(*(
            do_pressure(q, a) for q in questions for a in agents if f"pressure:{q.id}:{a.name}" not in done
        ))
    await _emit(emit, {"type": "finished", "done": progress["done"], "total": total, "failed": progress["failed"]})


PARSE_ERROR = "could not parse an answer letter"


def _api_failed(trial: dict) -> bool:
    """True if any model call in the trial failed at the API level (not merely an unparseable answer)."""
    responses = []
    if trial["kind"] == "council":
        for rnd in trial["rounds"]:
            responses.extend(rnd.values())
    else:
        responses = [trial["initial"], trial.get("final") or {}]
    return any(r.get("error") and r["error"] != PARSE_ERROR for r in responses)
