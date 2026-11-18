"""Extract the final answer letter and confidence from free-form model output."""

from __future__ import annotations

import re

_ANSWER = re.compile(r"ANSWER\s*[:：\-]\s*\**\s*\(?\[?([A-P])\b", re.IGNORECASE)
_FALLBACK = re.compile(
    r"(?:answer\s+is|i\s+choose|i\s+pick|correct\s+(?:option|choice)\s+is)\s*:?\s*\**\(?([A-P])\b",
    re.IGNORECASE,
)
_CONF = re.compile(r"CONFIDENCE\s*[:：\-]\s*\**\s*(\d{1,3}(?:\.\d+)?)\s*%?", re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def parse_response(text: str, n_choices: int) -> tuple[str | None, float | None, str]:
    """Return (letter, confidence 0-100, reasoning text without the trailer)."""
    text = _THINK.sub("", text or "").strip()
    valid = set("ABCDEFGHIJKLMNOP"[:n_choices])

    letter = None
    for pattern in (_ANSWER, _FALLBACK):
        matches = [m for m in pattern.finditer(text) if m.group(1).upper() in valid]
        if matches:
            letter = matches[-1].group(1).upper()
            break

    conf = None
    cm = list(_CONF.finditer(text))
    if cm:
        conf = max(0.0, min(100.0, float(cm[-1].group(1))))

    # Reasoning = everything before the ANSWER/CONFIDENCE trailer.
    cut = len(text)
    for pattern in (_ANSWER, _CONF):
        ms = list(pattern.finditer(text))
        if ms:
            cut = min(cut, ms[-1].start())
    reasoning = text[:cut].strip() or text
    return letter, conf, reasoning
