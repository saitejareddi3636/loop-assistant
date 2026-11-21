from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

EVALS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVALS_ROOT.parent
API_ROOT = REPO_ROOT / "api"


def bootstrap_evals_env(*, suite: str = "deterministic") -> None:
    """Point the process at the isolated evals DB and API package.

    Never loads production Oracle secrets. Prefers evals/.env, then repo .env
    only for GROQ_API_KEY when running live/voice suites.
    """
    os.environ.setdefault("APP_ENV", "evals")
    os.environ["EVALS_SUITE"] = suite

    evals_env = EVALS_ROOT / ".env"
    if evals_env.exists():
        load_dotenv(evals_env, override=True)
    else:
        load_dotenv(EVALS_ROOT / ".env.example", override=False)

    # Isolated DB default — do not fall back to production DATABASE_URL.
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://loopp_evals:loopp_evals@localhost:5434/loopp_evals",
    )

    if suite == "deterministic":
        os.environ["LLM_PROVIDER"] = "mock"
        os.environ["LLM_MODEL"] = "mock-support"
        os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
        os.environ.setdefault("VOICE_BACKEND", "hosted")
    elif suite in {"live", "voice", "all"}:
        # Allow repo .env for Groq key only; DB URL stays evals-isolated.
        repo_env = REPO_ROOT / ".env"
        values: dict = {}
        if repo_env.exists():
            from dotenv import dotenv_values

            values = dotenv_values(repo_env) or {}
            if values.get("GROQ_API_KEY") and not os.environ.get("GROQ_API_KEY"):
                os.environ["GROQ_API_KEY"] = values["GROQ_API_KEY"]
        # Force live providers — evals/.env defaults to mock for CI and must not win here.
        os.environ["LLM_PROVIDER"] = os.environ.get("EVALS_LLM_PROVIDER") or "groq"
        os.environ["LLM_MODEL"] = (
            os.environ.get("EVALS_LLM_MODEL")
            or values.get("LLM_MODEL")
            or "openai/gpt-oss-120b"
        )
        if suite == "live":
            os.environ["VOICE_BACKEND"] = "hosted"
        if suite in {"voice", "all"}:
            os.environ["VOICE_BACKEND"] = values.get("VOICE_BACKEND") or "local"
        # Live/voice suites are TPM-sensitive on free Groq tiers.
        os.environ.setdefault("LLM_MAX_RETRIES", "6")
        os.environ.setdefault("LLM_RETRY_BASE_SECONDS", "3.0")
        os.environ.setdefault("EVALS_LIVE_PAUSE_SECONDS", "8")

    os.environ.setdefault("SESSION_SECRET", "evals-only-secret")
    os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
    os.environ.setdefault("EMBEDDING_DIMS", "384")

    api_path = str(API_ROOT)
    if api_path not in sys.path:
        sys.path.insert(0, api_path)

    # Clear cached settings so DATABASE_URL / LLM_PROVIDER take effect.
    try:
        from app.config import get_settings

        get_settings.cache_clear()
    except Exception:  # noqa: BLE001
        pass
