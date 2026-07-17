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
    assert applied == ["20260701_deep_research_metrics"]

    assert upgrade_database(engine) == []
    engine.dispose()
