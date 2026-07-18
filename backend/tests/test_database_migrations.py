from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from edusci.memory.migrations import upgrade_database


def test_upgrade_adds_deep_research_columns_to_existing_database(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE autonomous_runs ("
                "id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36), status VARCHAR(40)"
                ")"
            )
        )

    applied = upgrade_database(engine)

    columns = {item["name"] for item in inspect(engine).get_columns("autonomous_runs")}
    assert "current_iteration" in columns
    assert "counter_evidence_coverage" in columns
    assert "degraded_sources" in columns
    assert applied == [
        "20260701_deep_research_metrics",
        "20260718_research_quality",
        "20260718_evidence_quality",
    ]

    assert upgrade_database(engine) == []
    engine.dispose()


def test_upgrade_adds_embedding_cache_to_an_already_migrated_database(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'quality.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_migrations ("
                "version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO schema_migrations (version) "
                "VALUES ('20260701_deep_research_metrics')"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE research_chunks ("
                "id VARCHAR(36) PRIMARY KEY, version_id VARCHAR(36), "
                "chunk_index INTEGER, locator VARCHAR(200), text TEXT, "
                "text_hash VARCHAR(64))"
            )
        )

    applied = upgrade_database(engine)

    columns = {item["name"] for item in inspect(engine).get_columns("research_chunks")}
    assert {"embedding", "embedding_model", "embedding_dimension"} <= columns
    assert applied == ["20260718_research_quality", "20260718_evidence_quality"]
    engine.dispose()


def test_upgrade_adds_evidence_quality_schema_without_rebuilding_tables(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'evidence.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_migrations ("
                "version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO schema_migrations (version) VALUES "
                "('20260701_deep_research_metrics'), ('20260718_research_quality')"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE autonomous_runs ("
                "id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36), status VARCHAR(40))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE claim_evidence_links ("
                "id VARCHAR(36) PRIMARY KEY, claim_id VARCHAR(36), "
                "chunk_id VARCHAR(36), stance VARCHAR(20), "
                "excerpt_hash VARCHAR(64), confidence INTEGER)"
            )
        )

    applied = upgrade_database(engine)

    run_columns = {
        item["name"] for item in inspect(engine).get_columns("autonomous_runs")
    }
    link_columns = {
        item["name"] for item in inspect(engine).get_columns("claim_evidence_links")
    }
    tables = set(inspect(engine).get_table_names())
    assert {"quality_metrics", "quality_gate_status"} <= run_columns
    assert {
        "excerpt",
        "validation_status",
        "entailment_score",
        "validator_model",
    } <= link_columns
    assert {"research_subquestions", "research_claim_subquestions"} <= tables
    assert applied == ["20260718_evidence_quality"]
    engine.dispose()
