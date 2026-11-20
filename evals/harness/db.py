from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db import session as db_session
from app.db.session import init_db
from app.rag.retrieve import seed_policy_index


async def prepare_evals_database() -> None:
    """Bind the app session factory to the isolated evals engine and seed RAG."""
    await db_session.engine.dispose()
    settings = get_settings()
    url = settings.database_url
    if "loopp_evals" not in url and os_environ_allow_non_evals() is False:
        raise RuntimeError(
            f"Refusing to run evals against non-isolated DATABASE_URL={url!r}. "
            "Expected database name loopp_evals."
        )
    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    db_session.engine = engine
    db_session.async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    await init_db()
    async with db_session.async_session_factory() as session:
        await seed_policy_index(session)


def os_environ_allow_non_evals() -> bool:
    import os

    return os.environ.get("EVALS_ALLOW_SHARED_DB", "").lower() in {"1", "true", "yes"}


@asynccontextmanager
async def evals_session() -> AsyncGenerator[AsyncSession, None]:
    async with db_session.async_session_factory() as session:
        yield session
