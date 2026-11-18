"""Question sets: multiple-choice questions with a known correct answer."""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

LETTERS = "ABCDEFGHIJKLMNOP"


@dataclass
class Question:
    id: str
    question: str
    choices: list[str]
    answer: str  # correct letter, e.g. "B"; "" if unknown (live debates)
    category: str = "general"
    source: str = "custom"
    meta: dict = field(default_factory=dict)

    @property
    def letters(self) -> str:
        return LETTERS[: len(self.choices)]

    def is_correct(self, letter: str | None) -> bool | None:
        if not self.answer:
            return None
        return letter is not None and letter == self.answer

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        answer = str(d.get("answer", "")).strip().upper()
        return cls(
            id=str(d["id"]),
            question=d["question"],
            choices=list(d["choices"]),
            answer=answer,
            category=d.get("category", "general"),
            source=d.get("source", "custom"),
            meta=d.get("meta", {}),
        )


def load_questions(path: str | Path, limit: int | None = None, shuffle_seed: int | None = None) -> list[Question]:
    qs: list[Question] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                qs.append(Question.from_dict(json.loads(line)))
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(qs)
    if limit:
        qs = qs[:limit]
    return qs


def save_questions(qs: list[Question], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for q in qs:
            f.write(json.dumps(q.to_dict(), ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- MMLU-Pro

HF_ROWS = "https://datasets-server.huggingface.co/rows"
MMLU_PRO = "TIGER-Lab/MMLU-Pro"
MMLU_PRO_PARQUET = "https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro/resolve/main/data/test-00000-of-00001.parquet"
CACHE_DIR = Path("data/cache")


async def fetch_mmlu_pro(n: int, seed: int = 0, categories: list[str] | None = None) -> list[Question]:
    """Sample `n` questions from the public MMLU-Pro test split (10 options each).

    Primary path: download the dataset's Parquet file once (~4 MB, cached in data/cache/) and sample
    locally. Fallback: the Hugging Face datasets-server row API, if pyarrow isn't installed.
    """
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        return await _fetch_mmlu_pro_rows_api(n, seed, categories)
    rows = await _load_mmlu_pro_parquet()
    if categories:
        wanted = {c.lower() for c in categories}
        rows = [r for r in rows if r["category"].lower() in wanted]
        if not rows:
            raise ValueError(f"No questions in categories {categories}. Valid: {sorted({r['category'] for r in rows})}")
    picked = random.Random(seed).sample(rows, min(n, len(rows)))
    return [
        Question(
            id=f"mmlupro-{r['question_id']}",
            question=r["question"],
            choices=[str(o) for o in r["options"]],
            answer=str(r["answer"]).strip().upper(),
            category=r["category"],
            source="MMLU-Pro",
        )
        for r in picked
    ]


async def _load_mmlu_pro_parquet() -> list[dict]:
    import pyarrow.parquet as pq

    path = CACHE_DIR / "mmlu_pro_test.parquet"
    if not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            for attempt in range(5):
                try:
                    async with client.stream("GET", MMLU_PRO_PARQUET) as r:
                        if r.status_code == 200:
                            with open(tmp, "wb") as f:
                                async for chunk in r.aiter_bytes():
                                    f.write(chunk)
                            break
                        err = f"HTTP {r.status_code}"
                except httpx.TransportError as e:
                    err = str(e)
                await asyncio.sleep(2 * (attempt + 1))
            else:
                raise RuntimeError(f"Could not download MMLU-Pro from Hugging Face ({err}). Try again in a few minutes.")
        tmp.replace(path)
    cols = ["question_id", "question", "options", "answer", "category"]
    return pq.read_table(path, columns=cols).to_pylist()


async def _fetch_mmlu_pro_rows_api(n: int, seed: int = 0, categories: list[str] | None = None) -> list[Question]:
    async with httpx.AsyncClient(timeout=60) as client:
        first = await _rows(client, 0, 1)
        total = first["num_rows_total"]
        rng = random.Random(seed)
        out: list[Question] = []
        seen: set[int] = set()
        sem = asyncio.Semaphore(6)

        async def grab(idx: int) -> Question | None:
            async with sem:
                data = await _rows(client, idx, 1)
            row = data["rows"][0]["row"]
            if categories and row["category"] not in categories:
                return None
            return Question(
                id=f"mmlupro-{row['question_id']}",
                question=row["question"],
                choices=[str(o) for o in row["options"]],
                answer=row["answer"].strip().upper(),
                category=row["category"],
                source="MMLU-Pro",
            )

        while len(out) < n and len(seen) < total:
            batch = []
            while len(batch) < (n - len(out)) * (3 if categories else 1) and len(seen) < total:
                i = rng.randrange(total)
                if i not in seen:
                    seen.add(i)
                    batch.append(i)
            for q in await asyncio.gather(*(grab(i) for i in batch)):
                if q is not None and len(out) < n:
                    out.append(q)
        return out


async def _rows(client: httpx.AsyncClient, offset: int, length: int) -> dict:
    for attempt in range(5):
        r = await client.get(
            HF_ROWS,
            params={"dataset": MMLU_PRO, "config": "default", "split": "test", "offset": offset, "length": length},
        )
        if r.status_code == 200:
            return r.json()
        await asyncio.sleep(1.5 * (attempt + 1))
    r.raise_for_status()
    return {}
