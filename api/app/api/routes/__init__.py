from fastapi import APIRouter

from app.api.routes.conversations import router as conversations_router
from app.api.routes.health import router as health_router
from app.api.routes.transcribe import router as transcribe_router
from app.api.routes.voice import router as voice_router
from app.api.routes.voice_status import router as voice_status_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(conversations_router)
api_router.include_router(transcribe_router)
api_router.include_router(voice_router)
api_router.include_router(voice_status_router)
