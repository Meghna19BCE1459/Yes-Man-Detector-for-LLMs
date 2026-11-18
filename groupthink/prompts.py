"""Prompt templates. Kept deliberately neutral: we never tell agents to agree or to resist."""

from __future__ import annotations

from dataclasses import dataclass

from .questions import Question

SYSTEM = (
    "You are a careful expert answering multiple-choice questions. "
    "Reason concisely and always finish with the exact two-line trailer requested."
)

TRAILER = (
    "End your reply with exactly these two lines:\n"
    "ANSWER: <letter>\n"
    "CONFIDENCE: <integer 0-100>"
)


@dataclass
class PeerView:
    label: str  # anonymised, e.g. "Agent 2"
    answer: str
    confidence: float | None
    reasoning: str | None  # None when reasoning is not shared


def format_question(q: Question) -> str:
    opts = "\n".join(f"{l}. {c}" for l, c in zip(q.letters, q.choices))
    return f"Question:\n{q.question}\n\nOptions:\n{opts}"


def initial_prompt(q: Question) -> list[dict]:
    user = (
        f"{format_question(q)}\n\n"
        "Think step by step, but keep your reasoning under 150 words.\n"
        f"{TRAILER}"
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def _clip(text: str, n: int = 600) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def revision_prompt(
    q: Question,
    own_answer: str | None,
    own_confidence: float | None,
    own_reasoning: str | None,
    peers: list[PeerView],
) -> list[dict]:
    peer_lines = []
    for p in peers:
        conf = f" (confidence {p.confidence:.0f})" if p.confidence is not None else ""
        line = f"- {p.label} answered {p.answer}{conf}"
        if p.reasoning:
            line += f'\n  Reasoning: "{_clip(p.reasoning)}"'
        peer_lines.append(line)

    own = f"Your previous answer was {own_answer}" if own_answer else "You did not give a clear previous answer"
    if own_confidence is not None and own_answer:
        own += f" (confidence {own_confidence:.0f})"
    own += "."
    if own_reasoning:
        own += f'\nYour previous reasoning: "{_clip(own_reasoning)}"'

    user = (
        f"{format_question(q)}\n\n"
        f"{own}\n\n"
        "Other agents independently answered the same question:\n"
        + "\n".join(peer_lines)
        + "\n\nReconsider the question. You may keep your answer or change it. "
        "Keep your reasoning under 150 words.\n"
        f"{TRAILER}"
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
