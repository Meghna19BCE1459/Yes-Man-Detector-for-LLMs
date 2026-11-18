"""Glue shared by the CLI and the web server: build agents, run, record status."""

from __future__ import annotations

from dotenv import load_dotenv

from .agents import build_agents
from .config import ExperimentConfig
from .experiment import Emit, run_experiment
from .providers import ChatClient
from .questions import Question
from .store import RunStore

load_dotenv()


async def execute(
    cfg: ExperimentConfig,
    questions: list[Question],
    store: RunStore,
    modes: tuple[str, ...],
    question_set: str = "custom",
    emit: Emit | None = None,
) -> None:
    client = ChatClient(cfg.providers)
    try:
        agents = build_agents(cfg, client)
        store.write_meta(
            status="running",
            config=cfg.to_dict(),
            council=cfg.name,
            agents=[a.name for a in agents],
            modes=list(modes),
            question_set=question_set,
            n_questions=len(questions),
            questions=[q.to_dict() for q in questions],
        )
        await run_experiment(cfg, questions, agents, store, modes=modes, emit=emit)
        store.write_meta(status="finished")
    except BaseException as e:
        store.write_meta(status="error", error=f"{type(e).__name__}: {e}"[:500])
        raise
    finally:
        await client.aclose()
