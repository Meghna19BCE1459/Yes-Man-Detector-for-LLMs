"""Minimal async client for OpenAI-compatible chat APIs (OpenRouter, Groq, Gemini, OpenAI, Anthropic, Ollama).

Every provider here speaks the same /chat/completions dialect, so one client covers all of them.
Per-provider rate limiting and retry-with-backoff keep free tiers happy.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ProviderSpec:
    base_url: str
    key_env: str | None
    default_rpm: int


PROVIDERS: dict[str, ProviderSpec] = {
    "openrouter": ProviderSpec("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", 20),
    "groq": ProviderSpec("https://api.groq.com/openai/v1", "GROQ_API_KEY", 30),
    "google": ProviderSpec("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", 10),
    "openai": ProviderSpec("https://api.openai.com/v1", "OPENAI_API_KEY", 60),
    "anthropic": ProviderSpec("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", 50),
    "ollama": ProviderSpec("http://localhost:11434/v1", None, 1000),
}

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class ProviderError(RuntimeError):
    pass


@dataclass
class ChatResult:
    text: str
    latency_s: float
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _Limiter:
    """Spaces request starts at least 60/rpm seconds apart and caps in-flight requests."""

    def __init__(self, rpm: int, max_concurrency: int):
        self.interval = 60.0 / max(rpm, 1)
        self.sem = asyncio.Semaphore(max_concurrency)
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def __aenter__(self):
        await self.sem.acquire()
        async with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self.interval
        if wait > 0:
            await asyncio.sleep(wait)

    async def __aexit__(self, *exc):
        self.sem.release()


class ChatClient:
    def __init__(self, provider_overrides: dict[str, dict] | None = None, timeout: float = 120.0):
        self.overrides = provider_overrides or {}
        self._http = httpx.AsyncClient(timeout=timeout)
        self._limiters: dict[str, _Limiter] = {}

    async def aclose(self):
        await self._http.aclose()

    def _spec(self, provider: str) -> tuple[str, str | None, int, int]:
        o = self.overrides.get(provider, {})
        base = PROVIDERS.get(provider)
        if base is None and "base_url" not in o:
            raise ProviderError(f"Unknown provider '{provider}'. Known: {', '.join(PROVIDERS)}")
        url = o.get("base_url") or base.base_url
        key_env = o.get("key_env", base.key_env if base else None)
        rpm = int(o.get("rpm", base.default_rpm if base else 60))
        conc = int(o.get("max_concurrency", 4))
        return url.rstrip("/"), key_env, rpm, conc

    def _limiter(self, provider: str) -> _Limiter:
        if provider not in self._limiters:
            _, _, rpm, conc = self._spec(provider)
            self._limiters[provider] = _Limiter(rpm, conc)
        return self._limiters[provider]

    def _headers(self, provider: str) -> dict[str, str]:
        _, key_env, _, _ = self._spec(provider)
        h = {"Content-Type": "application/json"}
        if key_env:
            key = os.environ.get(key_env)
            if not key:
                raise ProviderError(f"Missing API key: set {key_env} in your .env file")
            h["Authorization"] = f"Bearer {key}"
            if provider == "anthropic":
                h["x-api-key"] = key
                h["anthropic-version"] = "2023-06-01"
        if provider == "openrouter":
            h["X-Title"] = "Yes-Man Detector"
        return h

    async def chat(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        extra: dict | None = None,
        max_attempts: int = 6,
    ) -> ChatResult:
        url, *_ = self._spec(provider)
        headers = self._headers(provider)
        body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if extra:
            body.update(extra)

        last_err = ""
        for attempt in range(max_attempts):
            async with self._limiter(provider):
                t0 = time.monotonic()
                try:
                    r = await self._http.post(f"{url}/chat/completions", json=body, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_err = f"{type(e).__name__}: {e}"
                    r = None
                latency = time.monotonic() - t0

            if r is not None and r.status_code == 200:
                data = r.json()
                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                text = msg.get("content") or ""
                if isinstance(text, list):  # some providers return content parts
                    text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
                usage = data.get("usage") or {}
                return ChatResult(
                    text=text,
                    latency_s=latency,
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                )

            if r is not None:
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code not in RETRY_STATUS:
                    raise ProviderError(f"{provider}/{model}: {last_err}")
                retry_after = r.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else 0
            else:
                delay = 0
            await asyncio.sleep(max(delay, min(60.0, 2.0 * 2**attempt)))

        raise ProviderError(f"{provider}/{model}: gave up after {max_attempts} attempts ({last_err})")

    async def list_models(self, provider: str) -> list[str]:
        url, *_ = self._spec(provider)
        r = await self._http.get(f"{url}/models", headers=self._headers(provider))
        r.raise_for_status()
        data = r.json()
        items = data.get("data") or data.get("models") or []
        ids = [m.get("id") or m.get("name") for m in items if isinstance(m, dict)]
        return sorted(i.removeprefix("models/") for i in ids if i)
