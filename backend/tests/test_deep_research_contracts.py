from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from edusci.autonomy.contracts import DeepResearchLimits, EvidenceStance
from edusci.memory.database import build_session_factory
from edusci.memory.models import ResearchDocumentRecord


def test_adaptive_deep_limits_expand_to_hard_budget() -> None:
    limits = DeepResearchLimits()

    assert limits.depth_mode == "adaptive_deep"
    assert limits.initial_rounds == 5
    assert limits.initial_fulltexts == 20
    assert limits.soft_timeout_minutes == 60
    assert limits.max_rounds == 10
    assert limits.max_fulltexts == 60
    assert limits.hard_timeout_minutes == 120


def test_deep_limits_reject_soft_budget_above_hard_budget() -> None:
    with pytest.raises(ValueError, match="初始预算不能超过最大预算"):
        DeepResearchLimits(initial_fulltexts=40, max_fulltexts=20)


def test_research_memory_tables_and_run_metrics_exist(tmp_path: Path) -> None:
    factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'deep.db').as_posix()}"
    )
    with factory() as session:
        inspector = inspect(session.get_bind())
        tables = set(inspector.get_table_names())
        run_columns = {
            column["name"] for column in inspector.get_columns("autonomous_runs")
        }

    assert {
        "research_documents",
        "research_document_versions",
        "research_chunks",
        "research_claims",
        "claim_evidence_links",
        "project_evidence_uses",
        "research_iterations",
    }.issubset(tables)
    assert {
        "current_iteration",
        "source_count",
        "fulltext_count",
        "claim_count",
        "coverage",
        "counter_evidence_coverage",
        "model_usage",
        "stop_reason",
        "degraded_sources",
    }.issubset(run_columns)


def test_research_documents_are_globally_deduplicated(tmp_path: Path) -> None:
    factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'dedup.db').as_posix()}"
    )
    with factory() as session:
        session.add(
            ResearchDocumentRecord(
                canonical_key="doi:10.1000/example",
                title="Example",
                source_type="scholarly",
                canonical_url="https://doi.org/10.1000/example",
            )
        )
        session.commit()
        session.add(
            ResearchDocumentRecord(
                canonical_key="doi:10.1000/example",
                title="Duplicate",
                source_type="scholarly",
                canonical_url="https://doi.org/10.1000/example",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_evidence_stance_includes_counter_and_qualifier() -> None:
    assert EvidenceStance.COUNTER.value == "counter"
    assert EvidenceStance.QUALIFIES.value == "qualifies"
