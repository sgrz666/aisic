from pathlib import Path

from sqlalchemy import select

from edusci.memory.database import build_session_factory
from edusci.memory.models import ResearchChunkRecord
from edusci.memory.retrieval import (
    HybridCandidate,
    ResearchMemoryIndex,
    hybrid_rank,
    lexical_score,
)


def test_lexical_score_supports_chinese_character_ngrams_and_english_terms() -> None:
    assert lexical_score("教育资源配置", "人口变化影响基础教育资源配置") > 0
    assert lexical_score("student anxiety", "student mental health and anxiety") > 0
    assert lexical_score("student anxiety", "school lunch menu") == 0


def test_hybrid_rank_fuses_lexical_and_semantic_results_deterministically() -> None:
    candidates = [
        HybridCandidate(id="semantic", text="学生心理健康", embedding=[1.0, 0.0]),
        HybridCandidate(id="lexical", text="人工智能焦虑调查", embedding=[0.0, 1.0]),
        HybridCandidate(id="noise", text="校园午餐", embedding=[-1.0, 0.0]),
    ]

    ranked = hybrid_rank(
        "人工智能焦虑",
        [1.0, 0.0],
        candidates,
        limit=3,
    )

    assert [item.id for item in ranked[:2]] == ["semantic", "lexical"]
    assert ranked[0].hybrid_score > ranked[1].hybrid_score > ranked[2].hybrid_score


class _Embedder:
    embedding_model = "text-embedding-v4"
    embedding_dimension = 1024

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [
            ([1.0] + [0.0] * 1023 if "焦虑" in text else [0.0, 1.0] + [0.0] * 1022)
            for text in texts
        ]


def test_research_memory_index_caches_embeddings_and_reuses_them(tmp_path: Path) -> None:
    factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'memory.db').as_posix()}"
    )
    embedder = _Embedder()

    with factory() as session:
        session.add_all(
            [
                ResearchChunkRecord(
                    version_id="version-a",
                    chunk_index=0,
                    locator="Results",
                    text="人工智能使用与学生焦虑相关",
                    text_hash="a" * 64,
                ),
                ResearchChunkRecord(
                    version_id="version-b",
                    chunk_index=0,
                    locator="Methods",
                    text="学校午餐满意度调查",
                    text_hash="b" * 64,
                ),
            ]
        )
        session.commit()
        index = ResearchMemoryIndex(session, embedder)

        index.ensure_embeddings(list(session.scalars(select(ResearchChunkRecord))))
        first_calls = len(embedder.calls)
        ranked = index.search("人工智能焦虑", limit=2)

        chunks = list(session.scalars(select(ResearchChunkRecord)))

    assert first_calls == 1
    assert len(embedder.calls) == 2  # one document batch plus one query embedding
    assert all(chunk.embedding_model == "text-embedding-v4" for chunk in chunks)
    assert all(chunk.embedding_dimension == 1024 for chunk in chunks)
    assert ranked[0].text == "人工智能使用与学生焦虑相关"
