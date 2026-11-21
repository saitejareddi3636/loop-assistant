from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_RETRY_AFTER_RE = re.compile(r"retry[- ]after[:\s]+(\d+(?:\.\d+)?)", re.IGNORECASE)


class RateLimitBudgetExceeded(Exception):
    """Retry-After exceeds our in-process retry budget — do not keep hitting the API."""

    def __init__(self, retry_after_seconds: float, budget_seconds: float):
        self.retry_after_seconds = float(retry_after_seconds)
        self.budget_seconds = float(budget_seconds)
        super().__init__(
            f"Rate limited; Retry-After {self.retry_after_seconds:.0f}s exceeds "
            f"retry budget {self.budget_seconds:.0f}s"
        )


def get_chat_model() -> Any:
    settings = get_settings()
    provider = settings.llm_provider.lower().strip()

    if provider in {"mock", "local", "demo"}:
        from app.agent.mock_llm import MockSupportChatModel

        return MockSupportChatModel()

    if provider in {"groq", "openai", "openai_compatible", "compatible"}:
        api_key = settings.effective_llm_api_key
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY / LLM_API_KEY is not set. Copy .env.example to .env and add a key."
            )
        from langchain_openai import ChatOpenAI

        base_url = settings.llm_base_url
        if provider == "groq" and "groq.com" not in base_url:
            base_url = "https://api.groq.com/openai/v1"

        return ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            max_retries=0,  # we handle retries ourselves for clearer rate-limit UX
            streaming=False,  # ainvoke path; avoids streaming TPM waste on failed chunks
        )

    if provider in {"anthropic", "claude"}:
        api_key = settings.effective_llm_api_key
        if not api_key:
            raise RuntimeError(
                "LLM_API_KEY (or ANTHROPIC_API_KEY) is not set for Anthropic provider."
            )
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            streaming=False,
        )

    raise RuntimeError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")


def _is_retryable(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "rate" in text or "429" in text or "timeout" in text or "503" in text or "502" in text:
        return True
    if "ratelimit" in name or "apiconnection" in name or "timeout" in name:
        return True
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code in {429, 502, 503, 504}:
        return True
    return False


def is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    if "429" in text or "rate" in text or "ratelimit" in name:
        return True
    return getattr(exc, "status_code", None) == 429


def _header_retry_after(headers: Any) -> float | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if not callable(getter):
        try:
            getter = dict(headers).get
        except Exception:  # noqa: BLE001
            return None
    raw = getter("retry-after") or getter("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def extract_retry_after_seconds(exc: Exception) -> float | None:
    """Pull Retry-After from HTTP exception wrappers (Groq/OpenAI/httpx)."""
    candidates: list[Any] = [exc, getattr(exc, "__cause__", None), getattr(exc, "__context__", None)]
    for obj in candidates:
        if obj is None:
            continue
        response = getattr(obj, "response", None)
        if response is not None:
            delay = _header_retry_after(getattr(response, "headers", None))
            if delay is not None:
                return delay
        delay = _header_retry_after(getattr(obj, "headers", None))
        if delay is not None:
            return delay
        body = getattr(obj, "body", None)
        if isinstance(body, dict):
            err = body.get("error") if isinstance(body.get("error"), dict) else body
            for key in ("retry_after", "retry-after"):
                if key in err:
                    try:
                        return float(err[key])
                    except (TypeError, ValueError):
                        pass
    match = _RETRY_AFTER_RE.search(str(exc))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def compute_retry_delay_seconds(exc: Exception, *, attempt: int) -> float:
    """Delay for an in-budget retry. Raises RateLimitBudgetExceeded if Retry-After is too large."""
    settings = get_settings()
    budget = float(settings.llm_retry_max_seconds)
    hinted = extract_retry_after_seconds(exc)
    if hinted is not None and hinted > budget:
        raise RateLimitBudgetExceeded(hinted, budget)
    base = settings.llm_retry_base_seconds * (2 ** max(0, attempt - 1))
    delay = max(base, hinted) if hinted is not None else base
    # Small jitter to avoid synchronized retries under TPM limits.
    delay = delay + min(0.25 * attempt, 1.0)
    return min(delay, budget)


async def ainvoke_with_retries(model: Any, messages: list[Any]) -> Any:
    settings = get_settings()
    attempt = 0
    last_exc: Exception | None = None
    while attempt <= settings.llm_max_retries:
        try:
            return await model.ainvoke(messages)
        except RateLimitBudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            attempt += 1
            if attempt > settings.llm_max_retries or not _is_retryable(exc):
                raise
            # Fail closed when provider asks us to wait longer than our budget —
            # do not sleep/cap and hammer 429 again.
            delay = compute_retry_delay_seconds(exc, attempt=attempt)
            logger.warning(
                "LLM call failed (%s); retry %s/%s in %.1fs (retry_after=%s)",
                type(exc).__name__,
                attempt,
                settings.llm_max_retries,
                delay,
                extract_retry_after_seconds(exc),
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
