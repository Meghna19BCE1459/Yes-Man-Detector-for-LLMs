"""FastAPI backend for the dashboard. Runs stream live over Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import load_config
from .metrics import compute_metrics
from .questions import LETTERS, Question, load_questions
from .runner import execute
from .store import RUNS_DIR, RunStore, list_runs, new_run_id

CONFIG_DIR = Path("configs")
QUESTION_DIR = Path("data/questions")
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

app = FastAPI(title="Yes-Man Detector for LLMs")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ live runs
class LiveRun:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.finished = False

    def publish(self, ev: dict) -> None:
        self.events.append(ev)
        for q in self.subscribers:
            q.put_nowait(ev)


LIVE: dict[str, LiveRun] = {}
TASKS: set[asyncio.Task] = set()


def _start(run_id: str, coro_factory) -> None:
    live = LIVE[run_id] = LiveRun()

    async def runner():
        try:
            await coro_factory(live.publish)
        except Exception as e:  # surfaced to the UI; also stored in meta.json by execute()
            live.publish({"type": "error", "message": f"{type(e).__name__}: {e}"[:500]})
        finally:
            live.finished = True
            live.publish({"type": "closed"})

    task = asyncio.create_task(runner())
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)


# ------------------------------------------------------------------ catalog
def _safe(dir_: Path, name: str, ext: str) -> Path:
    p = (dir_ / f"{name}{ext}").resolve()
    if p.parent != dir_.resolve() or not p.exists():
        raise HTTPException(404, f"{name} not found")
    return p


@app.get("/api/configs")
def configs():
    out = []
    for p in sorted(CONFIG_DIR.glob("*.toml")):
        try:
            cfg = load_config(p)
            out.append({
                "id": p.stem,
                "name": cfg.name,
                "rounds": cfg.rounds,
                "agents": [{"name": a.name, "provider": a.provider, "model": a.model} for a in cfg.agents],
            })
        except Exception as e:
            out.append({"id": p.stem, "error": str(e)})
    return out


@app.get("/api/question-sets")
def question_sets():
    out = []
    for p in sorted(QUESTION_DIR.glob("*.jsonl")):
        with open(p, encoding="utf-8") as f:
            n = sum(1 for line in f if line.strip())
        out.append({"id": p.stem, "count": n})
    return out


# ------------------------------------------------------------------ runs
@app.get("/api/runs")
def runs():
    metas = list_runs()
    for m in metas:
        m.pop("questions", None)
        m.pop("config", None)
        if m.get("status") == "running" and m["id"] not in LIVE:
            m["status"] = "interrupted"
    return metas


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    store = _store(run_id)
    meta = store.read_meta()
    if not meta.get("live"):
        meta.pop("questions", None)
    meta.pop("config", None)
    if meta.get("status") == "running" and run_id not in LIVE:
        meta["status"] = "interrupted"
    return {"meta": meta, "metrics": compute_metrics(store.trials())}


@app.get("/api/runs/{run_id}/trials")
def run_trials(run_id: str):
    return _store(run_id).trials()


def _store(run_id: str) -> RunStore:
    if not (RUNS_DIR / run_id / "meta.json").exists() or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(404, "run not found")
    return RunStore(run_id)


class StartRun(BaseModel):
    config: str
    question_set: str
    mode: str = Field("both", pattern="^(council|pressure|both)$")
    limit: int | None = Field(None, ge=1, le=5000)
    rounds: int | None = Field(None, ge=1, le=10)
    share_reasoning: bool | None = None


@app.post("/api/runs")
async def start_run(body: StartRun):
    cfg = load_config(_safe(CONFIG_DIR, body.config, ".toml"))
    if body.rounds:
        cfg.rounds = body.rounds
    if body.share_reasoning is not None:
        cfg.share_reasoning = body.share_reasoning
    qs = load_questions(_safe(QUESTION_DIR, body.question_set, ".jsonl"), limit=body.limit)
    modes = ("council", "pressure") if body.mode == "both" else (body.mode,)
    run_id = new_run_id(cfg.name) + "-" + uuid.uuid4().hex[:4]
    store = RunStore(run_id)
    store.write_meta(status="running", council=cfg.name, agents=[a.name for a in cfg.agents],
                     question_set=body.question_set, n_questions=len(qs), modes=list(modes))
    _start(run_id, lambda emit: execute(cfg, qs, store, modes, question_set=body.question_set, emit=emit))
    return {"run_id": run_id}


class StartDebate(BaseModel):
    config: str
    question: str = Field(min_length=3, max_length=4000)
    choices: list[str] = Field(min_length=2, max_length=10)
    answer: str | None = None  # optional: the correct letter, if known
    rounds: int | None = Field(None, ge=1, le=10)


@app.post("/api/debate")
async def start_debate(body: StartDebate):
    cfg = load_config(_safe(CONFIG_DIR, body.config, ".toml"))
    if body.rounds:
        cfg.rounds = body.rounds
    answer = (body.answer or "").strip().upper()
    if answer and answer not in LETTERS[: len(body.choices)]:
        raise HTTPException(400, "answer must be one of the choice letters")
    q = Question(id=f"live-{uuid.uuid4().hex[:6]}", question=body.question.strip(),
                 choices=[c.strip() for c in body.choices], answer=answer, source="live")
    run_id = "debate-" + new_run_id(cfg.name).removeprefix(cfg.name + "-") + "-" + uuid.uuid4().hex[:4]
    store = RunStore(run_id)
    store.write_meta(status="running", council=cfg.name, agents=[a.name for a in cfg.agents],
                     question_set="live debate", n_questions=1, modes=["council"], live=True,
                     questions=[q.to_dict()])
    # Live debates always run every round so you can watch opinions evolve.
    _start(run_id, lambda emit: _debate(cfg, q, store, emit))
    return {"run_id": run_id}


async def _debate(cfg, q, store, emit):
    from .agents import build_agents
    from .experiment import council_trial
    from .providers import ChatClient

    client = ChatClient(cfg.providers)
    try:
        agents = build_agents(cfg, client)
        store.write_meta(config=cfg.to_dict(), questions=[q.to_dict()])
        emit({"type": "started", "total": 1, "done": 0})
        trial = await council_trial(q, agents, cfg, emit, stop_on_consensus=False)
        store.append_trial(trial)
        emit({"type": "trial", "trial": trial, "done": 1, "total": 1})
        store.write_meta(status="finished")
        emit({"type": "finished", "done": 1, "total": 1})
    except BaseException as e:
        store.write_meta(status="error", error=str(e)[:500])
        raise
    finally:
        await client.aclose()


@app.get("/api/runs/{run_id}/events")
async def events(run_id: str):
    live = LIVE.get(run_id)

    async def stream():
        if live is None:
            yield "data: " + json.dumps({"type": "closed"}) + "\n\n"
            return
        q: asyncio.Queue = asyncio.Queue()
        backlog = list(live.events)
        live.subscribers.add(q)
        try:
            for ev in backlog:
                yield "data: " + json.dumps(ev) + "\n\n"
            if live.finished:
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield "data: " + json.dumps(ev) + "\n\n"
                if ev["type"] == "closed":
                    return
        finally:
            live.subscribers.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ frontend
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = (WEB_DIST / path).resolve()
        if path and f.is_file() and WEB_DIST in f.parents:
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
