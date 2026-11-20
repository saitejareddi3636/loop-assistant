from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.config import get_settings
from app.db.session import async_session_factory, init_db
from app.rag.retrieve import seed_policy_index

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    async with async_session_factory() as session:
        count = await seed_policy_index(session)
        logger.info("Seeded/updated %s policy chunks", count)
    if not get_settings().voice_lazy_load:
        # Load voice models in the background so the first voice session
        # does not wait ~45s for TTS weights.
        asyncio.get_running_loop().run_in_executor(None, _warm_voice_stack)
    yield


def _warm_voice_stack() -> None:
    try:
        from app.voice.factory import get_voice_stack

        logger.info("Voice stack warmed: %s", get_voice_stack().backend)
    except Exception:  # noqa: BLE001
        logger.exception("Voice stack warmup failed")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Loopp Support Agent API",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api")

    # Production: serve Vite build if present (Docker image copies to /app/web_dist).
    for candidate in (Path("web_dist"), Path("../web/dist"), Path("/app/web_dist")):
        if candidate.is_dir() and (candidate / "index.html").exists():
            app.mount("/", StaticFiles(directory=str(candidate), html=True), name="web")
            break
    return app


app = create_app()
