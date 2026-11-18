"""Agents answer a question independently, then revise after seeing peers.

`LLMAgent` calls a real model. `MockAgent` simulates one with a tunable skill and conformity,
which makes the whole pipeline (and the UI) runnable offline and gives the metrics a known ground truth
to be tested against.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
from collections import Counter
from dataclasses import asdict, dataclass

from .config import AgentSpec, ExperimentConfig
from .parsing import parse_response
from .prompts import PeerView, initial_prompt, revision_prompt
from .providers import ChatClient
from .questions import Question


@dataclass
class Response:
    answer: str | None
    confidence: float | None
    reasoning: str
    raw: str = ""
    error: str | None = None
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Response":
        return cls(**d)


class Agent:
    def __init__(self, spec: AgentSpec):
        self.spec = spec
        self.name = spec.name

    async def initial(self, q: Question) -> Response:
        raise NotImplementedError

    async def revise(self, q: Question, own: Response, peers: list[PeerView]) -> Response:
        raise NotImplementedError


class LLMAgent(Agent):
    def __init__(self, spec: AgentSpec, client: ChatClient, cfg: ExperimentConfig):
        super().__init__(spec)
        self.client = client
        self.cfg = cfg

    async def _ask(self, q: Question, messages: list[dict]) -> Response:
        try:
            res = await self.client.chat(
                self.spec.provider,
                self.spec.model,
                messages,
                temperature=self.spec.temperature if self.spec.temperature is not None else self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
                extra=self.spec.params or None,
            )
        except Exception as e:  # recorded, never fatal for the run
            return Response(answer=None, confidence=None, reasoning="", error=str(e)[:500])
        letter, conf, reasoning = parse_response(res.text, len(q.choices))
        return Response(
            answer=letter,
            confidence=conf,
            reasoning=reasoning,
            raw=res.text,
            error=None if letter else "could not parse an answer letter",  # keep in sync with experiment.PARSE_ERROR
            latency_s=round(res.latency_s, 3),
            prompt_tokens=res.prompt_tokens,
            completion_tokens=res.completion_tokens,
        )

    async def initial(self, q: Question) -> Response:
        return await self._ask(q, initial_prompt(q))

    async def revise(self, q: Question, own: Response, peers: list[PeerView]) -> Response:
        return await self._ask(q, revision_prompt(q, own.answer, own.confidence, own.reasoning, peers))


class MockAgent(Agent):
    """Simulated agent.

    params:
      skill       P(correct) when answering alone
      conformity  P(adopting the peer majority when it disagrees and is wrong)
      discernment extra P(adopting the peer majority when the majority is right)
    """

    def __init__(self, spec: AgentSpec, seed: int = 0):
        super().__init__(spec)
        p = spec.params or {}
        self.skill = float(p.get("skill", 0.6))
        self.conformity = float(p.get("conformity", 0.3))
        self.discernment = float(p.get("discernment", 0.3))
        self.latency = float(p.get("latency", 0.0))  # fake "thinking" time so live views animate
        self.seed = seed

    async def _think(self, rng: random.Random) -> None:
        if self.latency:
            await asyncio.sleep(self.latency * rng.uniform(0.5, 1.5))

    def _rng(self, *parts) -> random.Random:
        h = hashlib.sha256("|".join(map(str, (self.seed, self.name, *parts))).encode()).hexdigest()
        return random.Random(int(h[:16], 16))

    def _wrong(self, q: Question, rng: random.Random) -> str:
        options = [l for l in q.letters if l != q.answer] or list(q.letters)
        # Concentrate wrong answers on a "tempting" distractor so a wrong majority can form.
        tempting = options[int(hashlib.md5(q.id.encode()).hexdigest(), 16) % len(options)]
        return tempting if rng.random() < 0.6 else rng.choice(options)

    async def initial(self, q: Question) -> Response:
        t0 = time.monotonic()
        rng = self._rng(q.id, 0)
        await self._think(rng)
        correct = bool(q.answer) and rng.random() < self.skill
        ans = q.answer if correct else self._wrong(q, rng)
        conf = round(rng.uniform(55, 95) if correct else rng.uniform(35, 85))
        return Response(
            answer=ans,
            confidence=conf,
            reasoning=f"[simulated] Working through the options, {ans} looks most consistent with the question.",
            latency_s=round(time.monotonic() - t0, 3),
        )

    async def revise(self, q: Question, own: Response, peers: list[PeerView]) -> Response:
        rng = self._rng(q.id, "rev", own.answer, tuple(sorted(p.answer for p in peers)))
        await self._think(rng)
        counts = Counter(p.answer for p in peers)
        majority, n = counts.most_common(1)[0] if counts else (None, 0)
        new, conf = own.answer, own.confidence
        why = "[simulated] I reviewed the other agents' arguments and I'm keeping my answer."
        if majority and majority != own.answer and n > len(peers) / 2:
            p_switch = self.conformity
            if q.answer and majority == q.answer:
                p_switch = min(1.0, p_switch + self.discernment)
            if rng.random() < p_switch:
                new = majority
                conf = round(rng.uniform(50, 85))
                why = f"[simulated] Most other agents chose {majority}; their argument seems convincing, so I'm switching."
        return Response(answer=new, confidence=conf, reasoning=why)


def build_agents(cfg: ExperimentConfig, client: ChatClient | None) -> list[Agent]:
    agents: list[Agent] = []
    for spec in cfg.agents:
        if spec.provider == "mock":
            agents.append(MockAgent(spec, seed=cfg.seed))
        else:
            if client is None:
                raise ValueError("A ChatClient is required for non-mock agents")
            agents.append(LLMAgent(spec, client, cfg))
    return agents
