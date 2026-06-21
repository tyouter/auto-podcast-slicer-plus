"""Unified LLM gateway. Single place all DeepSeek/VLM/HTTP calls go through.

Fixes legacy bug #7: LLM calls were scattered across quality_gate,
subtitle_style_extractor, text_corrector, subtitle_content — each with its own
``except Exception: pass`` that silently turned "LLM down" into "passed=True".
Here every call:
  * has a timeout + bounded retry with exponential backoff,
  * records an explicit WARNING (never silent) on degradation,
  * returns a typed ``LLMResponse`` distinguishing success / degraded / failure,
so callers can NEVER mistake "LLM unavailable" for "check passed".
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

log = logging.getLogger(__name__)

__all__ = ["LLMOutcome", "LLMResponse", "LLMClient", "NoLLMClient"]


class LLMOutcome(str, Enum):
    OK = "ok"  # call succeeded
    DEGRADED = "degraded"  # transient failure after retries, caller may continue
    UNAVAILABLE = "unavailable"  # no key / config / hard failure — caller MUST handle


@dataclass(frozen=True)
class LLMResponse:
    """Typed result. ``outcome`` tells callers whether to trust ``content``."""

    outcome: LLMOutcome
    content: str = ""
    attempts: int = 0
    error: str = ""
    elapsed_s: float = 0.0
    usage: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome is LLMOutcome.OK

    def raise_if_unavailable(self) -> "LLMResponse":
        """Convenience: raise if the LLM is hard-unavailable.

        Most deterministic stages want a *degraded* result to be a visible
        warning, not a crash — but some stages (e.g. quality gate that would
        otherwise report a false PASS) want to fail loudly. Call this there.
        """
        if self.outcome is LLMOutcome.UNAVAILABLE:
            raise RuntimeError(f"LLM unavailable: {self.error}")
        return self


class LLMClient:
    """Stateful HTTP client for an OpenAI-compatible chat endpoint.

    Stateful (holds base_url / api_key / default model) and **reused** across
    calls — never construct per-request. Inject one instance into any stage
    that needs an LLM (proofread.llm_corrector, style.extractor, …).
    """

    def __init__(
        self,
        base_url: str = "https://api.deepseek.com/v1",
        api_key: Optional[str] = None,
        default_model: str = "deepseek-chat",
        timeout: float = 30.0,
        max_retries: int = 2,
        backoff_base: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # api_key=None → fall back to env. api_key="" → explicit "no key".
        if api_key is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        messages: list[dict],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """Send a chat completion. Returns a typed LLMResponse."""
        if not self.api_key:
            log.warning("LLMClient.chat called without an API key — returning UNAVAILABLE")
            return LLMResponse(outcome=LLMOutcome.UNAVAILABLE, error="no api key")

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        deadline_timeout = timeout or self.timeout
        last_err = ""
        for attempt in range(1, self.max_retries + 2):  # initial + retries
            t0 = time.monotonic()
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=deadline_timeout) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                content = (raw.get("choices") or [{}])[0].get("message", {}).get("content", "")
                return LLMResponse(
                    outcome=LLMOutcome.OK,
                    content=content.strip(),
                    attempts=attempt,
                    elapsed_s=time.monotonic() - t0,
                    usage=raw.get("usage", {}) or {},
                )
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}: {e.reason}"
                # 4xx (except 429) are not retryable.
                if e.code != 429 and 400 <= e.code < 500:
                    log.warning("LLM call failed (%s) — not retrying", last_err)
                    return LLMResponse(
                        outcome=LLMOutcome.DEGRADED, attempts=attempt, error=last_err,
                        elapsed_s=time.monotonic() - t0,
                    )
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = f"{type(e).__name__}: {e}"

            if attempt <= self.max_retries:
                sleep_s = self.backoff_base ** (attempt - 1)
                log.warning("LLM call attempt %d failed (%s) — retrying in %.1fs",
                            attempt, last_err, sleep_s)
                time.sleep(sleep_s)

        log.warning("LLM call exhausted retries (%s) — DEGRADED", last_err)
        return LLMResponse(
            outcome=LLMOutcome.DEGRADED, attempts=self.max_retries + 1,
            error=last_err, elapsed_s=0.0,
        )

    def chat_json(
        self,
        messages: list[dict],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> tuple[LLMResponse, Optional[Any]]:
        """Chat expecting a JSON object back. Returns (response, parsed_or_None).

        A parse failure after a successful HTTP call is reported as DEGRADED
        with the raw content preserved in ``response.content``.
        """
        resp = self.chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
        if not resp.ok:
            return resp, None
        try:
            # Tolerate ```json fences and leading prose.
            txt = resp.content.strip()
            if txt.startswith("```"):
                txt = txt.strip("`")
                if txt.lower().startswith("json"):
                    txt = txt[4:].strip()
            return resp, json.loads(txt)
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("LLM returned non-JSON (%s): %.200s", e, resp.content)
            return (
                LLMResponse(
                    outcome=LLMOutcome.DEGRADED,
                    content=resp.content,
                    attempts=resp.attempts,
                    error=f"json decode: {e}",
                    elapsed_s=resp.elapsed_s,
                ),
                None,
            )


class NoLLMClient(LLMClient):
    """Null object: always UNAVAILABLE. Use when a stage should run LLM-free."""

    def __init__(self) -> None:  # noqa: D401
        # Skip the real __init__ — we don't want to read env keys.
        self.base_url = ""
        self.api_key = ""
        self.default_model = ""
        self.timeout = 0.0
        self.max_retries = 0
        self.backoff_base = 0.0

    @property
    def available(self) -> bool:
        return False

    def chat(self, messages, **kwargs) -> LLMResponse:  # type: ignore[override]
        return LLMResponse(outcome=LLMOutcome.UNAVAILABLE, error="NoLLMClient")
