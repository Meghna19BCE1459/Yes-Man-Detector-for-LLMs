"""On-disk storage for runs: runs/<run_id>/meta.json + trials.jsonl (one completed trial per line)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path("runs")


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


class RunStore:
    def __init__(self, run_id: str, root: Path | str = RUNS_DIR):
        self.run_id = run_id
        self.dir = Path(root) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.dir / "meta.json"
        self.trials_path = self.dir / "trials.jsonl"
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- meta
    def read_meta(self) -> dict:
        if self.meta_path.exists():
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        return {}

    def write_meta(self, **updates) -> dict:
        with self._lock:
            meta = self.read_meta()
            meta.update(updates)
            meta.setdefault("id", self.run_id)
            meta.setdefault("created", datetime.now(timezone.utc).isoformat())
            meta["updated"] = datetime.now(timezone.utc).isoformat()
            self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return meta

    # --------------------------------------------------------------- trials
    def append_trial(self, trial: dict) -> None:
        with self._lock:
            with open(self.trials_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(trial, ensure_ascii=False) + "\n")

    def trials(self) -> list[dict]:
        if not self.trials_path.exists():
            return []
        out = []
        with open(self.trials_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # tolerate a half-written last line after a crash
        return out


def trial_key(trial: dict) -> str:
    if trial["kind"] == "council":
        return f"council:{trial['question']['id']}"
    return f"pressure:{trial['question']['id']}:{trial['agent']}"


def list_runs(root: Path | str = RUNS_DIR) -> list[dict]:
    root = Path(root)
    if not root.exists():
        return []
    metas = []
    for d in root.iterdir():
        m = d / "meta.json"
        if m.exists():
            try:
                metas.append(json.loads(m.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
    return sorted(metas, key=lambda m: m.get("created", ""), reverse=True)
