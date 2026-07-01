from pathlib import Path

from sqlalchemy import inspect

from edusci.memory.database import build_session_factory
from edusci.memory.models import DocumentChunk, KnowledgeEntity, MemoryEdge


def test_eduscimem_has_vector_entities_and_generic_relation_edges(tmp_path: Path) -> None:
    session_factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'memory.db').as_posix()}"
    )
    with session_factory() as session:
        tables = set(inspect(session.get_bind()).get_table_names())

    assert {KnowledgeEntity.__tablename__, MemoryEdge.__tablename__} <= tables
    assert DocumentChunk.__table__.c.embedding.type.dim == 1024
    assert KnowledgeEntity.__table__.c.embedding.type.dim == 1024
