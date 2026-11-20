from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Load repo .env for GROQ_API_KEY / DATABASE_URL, then force mock defaults for unit tests.
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH, override=True)
# Prefer explicit DATABASE_URL from the project .env (Docker may map 5433).
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text().splitlines():
        if _line.startswith("DATABASE_URL="):
            os.environ["DATABASE_URL"] = _line.split("=", 1)[1].strip()
            break
os.environ["LLM_PROVIDER"] = "mock"
os.environ["LLM_MODEL"] = "mock-support"
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("EMBEDDING_DIMS", "384")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://loopp:loopp@localhost:5432/loopp",
)

from app.config import get_settings
from app.db import session as db_session
from app.db.session import init_db
from app.main import create_app
from app.rag.retrieve import seed_policy_index

get_settings.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def prepare_database() -> AsyncGenerator[None, None]:
    """Recreate a NullPool engine per test to avoid cross-loop asyncpg issues."""
    await db_session.engine.dispose()
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
    )
    db_session.engine = engine
    db_session.async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    await init_db()
    async with db_session.async_session_factory() as session:
        await seed_policy_index(session)
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    async with db_session.async_session_factory() as db:
        yield db


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    get_settings.cache_clear()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def conversation_id() -> uuid.UUID:
    return uuid.uuid4()
