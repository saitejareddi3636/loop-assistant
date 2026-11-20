from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import PolicyChunkRow
from app.rag.embeddings import embed_query, embed_texts
from app.rag.policies import POLICY_CHUNKS


def _content_hash(body: str, version: str, section_id: str) -> str:
    return hashlib.sha256(f"{section_id}:{version}:{body}".encode()).hexdigest()


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"


async def seed_policy_index(session: AsyncSession) -> int:
    """Upsert versioned policy chunks and embed only changed content."""
    settings = get_settings()
    upserted = 0
    for chunk in POLICY_CHUNKS:
        digest = _content_hash(chunk.body, chunk.version, chunk.section_id)
        existing = await session.scalar(
            select(PolicyChunkRow).where(PolicyChunkRow.section_id == chunk.section_id)
        )
        if existing and existing.content_hash == digest and existing.embedding_model == (
            f"{settings.embedding_provider}:{settings.embedding_model}"
        ):
            continue

        embedding = embed_texts([f"{chunk.title}\n{chunk.body}"])[0]
        payload = {
            "doc_id": chunk.doc_id,
            "section_id": chunk.section_id,
            "title": chunk.title,
            "tier": chunk.tier,
            "version": chunk.version,
            "status": chunk.status,
            "intent": chunk.intent,
            "citation": chunk.citation,
            "effective_from": chunk.effective_from,
            "effective_to": chunk.effective_to,
            "body": chunk.body,
            "is_exception": chunk.is_exception,
            "supersedes": chunk.supersedes,
            "content_hash": digest,
            "embedding_model": f"{settings.embedding_provider}:{settings.embedding_model}",
            "embedding": embedding,
            "search_text": f"{chunk.title} {chunk.intent} {chunk.citation} {chunk.body}",
        }
        if existing is None:
            session.add(PolicyChunkRow(**payload))
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
        upserted += 1
    await session.commit()
    return upserted


def _rrf_fuse(
    vector_hits: list[tuple[str, float]],
    keyword_hits: list[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for rank, (section_id, _) in enumerate(vector_hits):
        scores[section_id] = scores.get(section_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, (section_id, _) in enumerate(keyword_hits):
        scores[section_id] = scores.get(section_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


async def hybrid_search_policies(
    session: AsyncSession,
    *,
    query: str,
    tier: str | None = None,
    as_of: date | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Hybrid vector + full-text retrieval with confidence guardrails."""
    settings = get_settings()
    top_k = limit or settings.rag_top_k
    as_of = as_of or date(2026, 11, 19)
    query_vec = embed_query(query)
    vec_literal = _vector_literal(query_vec)

    filters = ["status = 'active'", "(effective_to IS NULL OR effective_to >= :as_of)"]
    params: dict[str, Any] = {"as_of": as_of, "q": query, "limit": top_k}
    if tier:
        filters.append("(tier = :tier OR tier = '*')")
        params["tier"] = tier
    where_sql = " AND ".join(filters)

    vector_sql = text(
        f"""
        SELECT section_id, 1 - (embedding <=> CAST(:embedding AS vector)) AS score
        FROM policy_chunks
        WHERE {where_sql}
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
        """
    ).bindparams(bindparam("embedding"))

    keyword_sql = text(
        f"""
        SELECT section_id,
               ts_rank_cd(to_tsvector('english', search_text), plainto_tsquery('english', :q)) AS score
        FROM policy_chunks
        WHERE {where_sql}
          AND to_tsvector('english', search_text) @@ plainto_tsquery('english', :q)
        ORDER BY score DESC
        LIMIT :limit
        """
    )

    vector_rows = (
        await session.execute(vector_sql, {**params, "embedding": vec_literal})
    ).all()
    keyword_rows = (await session.execute(keyword_sql, params)).all()

    vector_hits = [(r.section_id, float(r.score or 0.0)) for r in vector_rows]
    keyword_hits = [(r.section_id, float(r.score or 0.0)) for r in keyword_rows]
    fused = _rrf_fuse(vector_hits, keyword_hits)[:top_k]
    if not fused and vector_hits:
        fused = [(sid, score) for sid, score in vector_hits[:top_k]]

    section_ids = [sid for sid, _ in fused]
    if not section_ids:
        return {
            "ok": True,
            "documents": [],
            "count": 0,
            "confident": False,
            "threshold": settings.rag_cosine_threshold,
            "reason": "no_matches",
            "should_escalate": True,
        }

    rows = (
        await session.scalars(
            select(PolicyChunkRow).where(PolicyChunkRow.section_id.in_(section_ids))
        )
    ).all()
    by_id = {row.section_id: row for row in rows}

    documents: list[dict[str, Any]] = []
    max_cosine = 0.0
    for section_id, rrf_score in fused:
        row = by_id.get(section_id)
        if row is None:
            continue
        # Recompute cosine against stored embedding for guardrail decision.
        cosine = next((score for sid, score in vector_hits if sid == section_id), 0.0)
        max_cosine = max(max_cosine, cosine)
        documents.append(
            {
                "doc_id": row.doc_id,
                "section_id": row.section_id,
                "title": row.title,
                "tier": row.tier,
                "version": row.version,
                "status": row.status,
                "intent": row.intent,
                "citation": row.citation,
                "excerpt": row.body,
                "is_exception": row.is_exception,
                "rrf_score": rrf_score,
                "cosine": cosine,
            }
        )

    confident = max_cosine >= settings.rag_cosine_threshold and len(documents) > 0
    return {
        "ok": True,
        "documents": documents,
        "count": len(documents),
        "confident": confident,
        "max_cosine": max_cosine,
        "threshold": settings.rag_cosine_threshold,
        "should_escalate": not confident,
        "reason": None if confident else "below_confidence_threshold",
    }
