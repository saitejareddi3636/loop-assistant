from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from app.config import get_settings


@dataclass
class SessionToken:
    token: str
    conversation_id: str
    expires_at: float


def _secret() -> bytes:
    settings = get_settings()
    raw = settings.session_secret or "dev-only-change-me"
    return raw.encode("utf-8")


def issue_session_token(conversation_id: str, ttl_seconds: int | None = None) -> SessionToken:
    settings = get_settings()
    ttl = ttl_seconds or settings.session_ttl_seconds
    expires_at = time.time() + ttl
    nonce = secrets.token_hex(8)
    payload = f"{conversation_id}:{int(expires_at)}:{nonce}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    token = f"{payload}:{sig}"
    return SessionToken(token=token, conversation_id=conversation_id, expires_at=expires_at)


def verify_session_token(token: str, conversation_id: str) -> bool:
    try:
        conversation, expires_s, nonce, sig = token.split(":")
    except ValueError:
        return False
    if conversation != conversation_id:
        return False
    if time.time() > float(expires_s):
        return False
    payload = f"{conversation}:{expires_s}:{nonce}"
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
