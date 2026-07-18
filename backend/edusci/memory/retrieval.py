from __future__ import annotations

import math
import re

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from edusci.memory.models import ResearchChunkRecord


class HybridCandidate(BaseModel):
    id: str
    text: str
    embedding: list[float] | None = None
    lexical_score: float = 0.0
    semantic_score: float = 0.0
    hybrid_score: float = 0.0


def _terms(value: str) -> set[str]:
    lowered = value.lower()
    terms = set(re.findall(r"[a-z0-9]+", lowered))
    for run in re.findall(r"[\u3400-\u9fff]+", lowered):
        if len(run) == 1:
            terms.add(run)
        else:
            terms.update(run[index : index + 2] for index in range(len(run) - 1))
    return terms


def lexical_score(query: str, text: str) -> float:
    query_terms = _terms(query)
    if not query_terms:
        return 0.0
    text_terms = _terms(text)
    return len(query_terms.intersection(text_terms)) / len(query_terms)


def cosine_similarity(left: list[float], right: list[float] | None) -> float:
    if right is None or len(left) != len(right) or not left:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def _rank(values: list[tuple[str, float]]) -> dict[str, int]:
    ordered = sorted(
        (item for item in values if item[1] > 0),
        key=lambda item: (-item[1], item[0]),
    )
    return {item_id: index + 1 for index, (item_id, _) in enumerate(ordered)}


def hybrid_rank(
    query: str,
    query_embedding: list[float] | None,
    candidates: list[HybridCandidate],
    *,
    limit: int = 20,
) -> list[HybridCandidate]:
    scored = [
        item.model_copy(
            update={
                "lexical_score": lexical_score(query, item.text),
                "semantic_score": cosine_similarity(query_embedding or [], item.embedding),
            }
        )
        for item in candidates
    ]
    lexical_ranks = _rank([(item.id, item.lexical_score) for item in scored])
    semantic_ranks = _rank([(item.id, item.semantic_score) for item in scored])
    fused = [
        item.model_copy(
            update={
                "hybrid_score": (
                    (
                        0.45 / (60 + lexical_ranks[item.id])
                        if item.id in lexical_ranks
                        else 0.0
                    )
                    + (
                        0.55 / (60 + semantic_ranks[item.id])
                        if item.id in semantic_ranks
                        else 0.0
                    )
                )
            }
        )
        for item in scored
    ]
    return sorted(fused, key=lambda item: (-item.hybrid_score, item.id))[:limit]


class ResearchMemoryIndex:
    def __init__(self, session: Session, embedder) -> None:
        self.session = session
        self.embedder = embedder
        self.embedding_model = str(embedder.embedding_model)
        self.embedding_dimension = int(embedder.embedding_dimension)

    def ensure_embeddings(self, chunks: list[ResearchChunkRecord]) -> int:
        stale = [
            chunk
            for chunk in chunks
            if chunk.embedding is None
            or chunk.embedding_model != self.embedding_model
            or chunk.embedding_dimension != self.embedding_dimension
        ]
        for start in range(0, len(stale), 10):
            batch = stale[start : start + 10]
            vectors = self.embedder.embed([chunk.text for chunk in batch])
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector
                chunk.embedding_model = self.embedding_model
                chunk.embedding_dimension = self.embedding_dimension
                self.session.add(chunk)
        self.session.flush()
        return len(stale)

    def search(self, query: str, *, limit: int = 20) -> list[HybridCandidate]:
        query_embedding = self.embedder.embed([query])[0]
        chunks = list(
            self.session.scalars(
                select(ResearchChunkRecord).where(
                    ResearchChunkRecord.embedding.is_not(None),
                    ResearchChunkRecord.embedding_model == self.embedding_model,
                    ResearchChunkRecord.embedding_dimension == self.embedding_dimension,
                )
            )
        )
        candidates = [
            HybridCandidate(
                id=chunk.id,
                text=chunk.text,
                embedding=list(chunk.embedding) if chunk.embedding is not None else None,
            )
            for chunk in chunks
        ]
        return hybrid_rank(query, query_embedding, candidates, limit=limit)
