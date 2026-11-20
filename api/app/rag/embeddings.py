from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

from app.config import get_settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    grams: list[str] = []
    for token in tokens:
        grams.append(token)
        if len(token) >= 4:
            for i in range(len(token) - 2):
                grams.append(token[i : i + 3])
    return grams


def _hash_embed(text: str, dims: int) -> list[float]:
    """Deterministic sparse-hash embedding (M2-friendly, no model download)."""
    vec = [0.0] * dims
    grams = _tokenize(text)
    if not grams:
        return vec
    for gram in grams:
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + (digest[5] / 255.0)
        vec[idx] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@lru_cache(maxsize=1)
def _fastembed_model():
    from fastembed import TextEmbedding

    settings = get_settings()
    return TextEmbedding(model_name=settings.embedding_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    provider = settings.embedding_provider.lower().strip()
    if provider in {"hash", "local_hash", "test"}:
        return [_hash_embed(t, settings.embedding_dims) for t in texts]
    if provider in {"fastembed", "bge"}:
        model = _fastembed_model()
        return [list(map(float, vec)) for vec in model.embed(texts)]
    raise RuntimeError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
