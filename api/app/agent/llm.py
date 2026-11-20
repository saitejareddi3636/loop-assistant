from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


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
            streaming=True,
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
            streaming=True,
        )

    raise RuntimeError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")


def _is_retryable(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "rate" in text or "429" in text or "timeout" in text or "503" in text or "502" in text:
        return True
    if "ratelimit" in name or "apiconnection" in name or "timeout" in name:
        return True
    return False


async def ainvoke_with_retries(model: Any, messages: list[Any]) -> Any:
    settings = get_settings()
    attempt = 0
    last_exc: Exception | None = None
    while attempt <= settings.llm_max_retries:
        try:
            return await model.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            attempt += 1
            if attempt > settings.llm_max_retries or not _is_retryable(exc):
                raise
            delay = settings.llm_retry_base_seconds * (2 ** (attempt - 1))
            logger.warning("LLM call failed (%s); retrying in %.1fs", exc, delay)
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
