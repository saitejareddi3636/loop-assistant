from fastapi import APIRouter
from sqlalchemy import text

from app.api.schemas import HealthOut
from app.config import get_settings
from app.db.session import async_session_factory

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    settings = get_settings()
    db_status = "ok"
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
            await session.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
    except Exception as exc:  # noqa: BLE001
        db_status = f"error: {exc}"

    provider = settings.llm_provider.lower()
    llm_ready = provider in {"mock", "local", "demo"} or bool(settings.effective_llm_api_key)
    return HealthOut(
        status="ok" if db_status == "ok" else "degraded",
        database=db_status,
        llm_configured=llm_ready,
        model=f"{settings.llm_provider}:{settings.llm_model}",
    )
