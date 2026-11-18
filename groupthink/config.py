"""Experiment configuration, loaded from a TOML file in configs/."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class AgentSpec:
    name: str  # display name, unique within a council
    provider: str  # openrouter | groq | google | openai | anthropic | ollama | mock
    model: str
    temperature: float | None = None
    params: dict = field(default_factory=dict)  # mock-agent knobs or extra request fields


@dataclass
class ExperimentConfig:
    name: str
    agents: list[AgentSpec]
    rounds: int = 3  # debate rounds after the independent round 0
    share_reasoning: bool = True  # do agents see each other's reasoning or only answers?
    temperature: float = 0.3
    max_tokens: int = 2048
    concurrency: int = 4  # questions debated in parallel
    seed: int = 0
    pressure_peers: int = 4  # size of the fake unanimous crowd in the pressure test
    providers: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict, name: str = "custom") -> "ExperimentConfig":
        exp = d.get("experiment", d)
        agents = [AgentSpec(**a) for a in d["agents"]]
        names = [a.name for a in agents]
        if len(set(names)) != len(names):
            raise ValueError(f"Agent names must be unique, got {names}")
        if len(agents) < 2:
            raise ValueError("A council needs at least 2 agents")
        return cls(
            name=d.get("name", name),
            agents=agents,
            rounds=int(exp.get("rounds", 3)),
            share_reasoning=bool(exp.get("share_reasoning", True)),
            temperature=float(exp.get("temperature", 0.3)),
            max_tokens=int(exp.get("max_tokens", 2048)),
            concurrency=int(exp.get("concurrency", 4)),
            seed=int(exp.get("seed", 0)),
            pressure_peers=int(exp.get("pressure_peers", 4)),
            providers=d.get("providers", {}),
        )


def load_config(path: str | Path) -> ExperimentConfig:
    path = Path(path)
    # utf-8-sig: tolerate the byte-order mark Windows editors like to add.
    data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    return ExperimentConfig.from_dict(data, name=path.stem)
