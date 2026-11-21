"""Groq/OpenAI rate-limit retry helpers: Retry-After + bounded backoff."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent import llm as llm_mod
from app.config import get_settings


class _FakeRateLimit(Exception):
    def __init__(self, retry_after: str | None = "2"):
        super().__init__("Error code: 429 - rate limit exceeded")
        headers = {"retry-after": retry_after} if retry_after else {}
        self.response = SimpleNamespace(headers=headers)
        self.status_code = 429


@pytest.fixture(autouse=True)
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_extract_retry_after_from_response_headers():
    exc = _FakeRateLimit("3.5")
    assert llm_mod.extract_retry_after_seconds(exc) == 3.5


def test_compute_retry_delay_under_budget(monkeypatch):
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "1")
    monkeypatch.setenv("LLM_RETRY_MAX_SECONDS", "10")
    get_settings.cache_clear()
    delay = llm_mod.compute_retry_delay_seconds(_FakeRateLimit("2"), attempt=1)
    assert 2.0 <= delay <= 10.0


def test_compute_retry_delay_raises_when_retry_after_exceeds_budget(monkeypatch):
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "1")
    monkeypatch.setenv("LLM_RETRY_MAX_SECONDS", "5")
    get_settings.cache_clear()
    with pytest.raises(llm_mod.RateLimitBudgetExceeded) as ei:
        llm_mod.compute_retry_delay_seconds(_FakeRateLimit("30"), attempt=1)
    assert ei.value.retry_after_seconds == 30.0
    assert ei.value.budget_seconds == 5.0


@pytest.mark.asyncio
async def test_ainvoke_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("LLM_MAX_RETRIES", "3")
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "0.01")
    monkeypatch.setenv("LLM_RETRY_MAX_SECONDS", "0.05")
    get_settings.cache_clear()

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    calls = {"n": 0}

    class Flaky:
        async def ainvoke(self, _messages):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _FakeRateLimit("0.02")
            return "ok"

    out = await llm_mod.ainvoke_with_retries(Flaky(), [])
    assert out == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2


@pytest.mark.asyncio
async def test_ainvoke_fails_fast_when_retry_after_exceeds_budget(monkeypatch):
    monkeypatch.setenv("LLM_MAX_RETRIES", "4")
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "0.01")
    monkeypatch.setenv("LLM_RETRY_MAX_SECONDS", "2")
    get_settings.cache_clear()

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    calls = {"n": 0}

    class HugeWait:
        async def ainvoke(self, _messages):
            calls["n"] += 1
            raise _FakeRateLimit("60")

    with pytest.raises(llm_mod.RateLimitBudgetExceeded):
        await llm_mod.ainvoke_with_retries(HugeWait(), [])
    assert calls["n"] == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_ainvoke_exhausts_retries_on_persistent_429(monkeypatch):
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "0.01")
    monkeypatch.setenv("LLM_RETRY_MAX_SECONDS", "0.05")
    get_settings.cache_clear()

    async def fake_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    class Always429:
        async def ainvoke(self, _messages):
            raise _FakeRateLimit("0.01")

    with pytest.raises(_FakeRateLimit):
        await llm_mod.ainvoke_with_retries(Always429(), [])
