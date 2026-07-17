from __future__ import annotations

from sqlalchemy import Engine, inspect, text


_DEEP_RESEARCH_COLUMNS = {
    "current_iteration": "INTEGER NOT NULL DEFAULT 0",
    "source_count": "INTEGER NOT NULL DEFAULT 0",
    "fulltext_count": "INTEGER NOT NULL DEFAULT 0",
    "claim_count": "INTEGER NOT NULL DEFAULT 0",
    "coverage": "INTEGER NOT NULL DEFAULT 0",
    "counter_evidence_coverage": "INTEGER NOT NULL DEFAULT 0",
    "model_usage": "JSON NOT NULL DEFAULT '{}'",
    "stop_reason": "VARCHAR(80) NOT NULL DEFAULT ''",
    "degraded_sources": "JSON NOT NULL DEFAULT '[]'",
}


def upgrade_database(engine: Engine) -> list[str]:
    """Apply small, idempotent schema upgrades to databases created before migrations."""
    migration = "20260701_deep_research_metrics"
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        applied = connection.execute(
            text("SELECT version FROM schema_migrations WHERE version = :version"),
            {"version": migration},
        ).scalar_one_or_none()
        if applied:
            return []

        tables = set(inspect(connection).get_table_names())
        if "autonomous_runs" in tables:
            existing = {
                column["name"]
                for column in inspect(connection).get_columns("autonomous_runs")
            }
            for name, definition in _DEEP_RESEARCH_COLUMNS.items():
                if name not in existing:
                    connection.execute(
                        text(f"ALTER TABLE autonomous_runs ADD COLUMN {name} {definition}")
                    )

        connection.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"),
            {"version": migration},
        )
    return [migration]
