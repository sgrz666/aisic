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

_RESEARCH_CHUNK_QUALITY_COLUMNS = {
    "embedding": "VECTOR(1024)",
    "embedding_model": "VARCHAR(100) NOT NULL DEFAULT ''",
    "embedding_dimension": "INTEGER NOT NULL DEFAULT 0",
}

_RUN_QUALITY_COLUMNS = {
    "quality_metrics": "JSON NOT NULL DEFAULT '{}'",
    "quality_gate_status": "VARCHAR(24) NOT NULL DEFAULT 'PENDING'",
}

_EVIDENCE_QUALITY_COLUMNS = {
    "excerpt": "TEXT NOT NULL DEFAULT ''",
    "validation_status": "VARCHAR(24) NOT NULL DEFAULT 'candidate'",
    "entailment_score": "INTEGER NOT NULL DEFAULT 0",
    "validator_model": "VARCHAR(100) NOT NULL DEFAULT 'deterministic'",
}


def upgrade_database(engine: Engine) -> list[str]:
    """Apply small, idempotent schema upgrades to databases created before migrations."""
    applied_now: list[str] = []
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        applied = set(
            connection.execute(text("SELECT version FROM schema_migrations")).scalars()
        )
        tables = set(inspect(connection).get_table_names())
        deep_migration = "20260701_deep_research_metrics"
        if deep_migration not in applied:
            if "autonomous_runs" in tables:
                existing = {
                    column["name"]
                    for column in inspect(connection).get_columns("autonomous_runs")
                }
                for name, definition in _DEEP_RESEARCH_COLUMNS.items():
                    if name not in existing:
                        connection.execute(
                            text(
                                f"ALTER TABLE autonomous_runs ADD COLUMN {name} {definition}"
                            )
                        )
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": deep_migration},
            )
            applied_now.append(deep_migration)

        quality_migration = "20260718_research_quality"
        if quality_migration not in applied:
            if "research_chunks" in tables:
                existing = {
                    column["name"]
                    for column in inspect(connection).get_columns("research_chunks")
                }
                for name, definition in _RESEARCH_CHUNK_QUALITY_COLUMNS.items():
                    if name not in existing:
                        connection.execute(
                            text(
                                f"ALTER TABLE research_chunks ADD COLUMN {name} {definition}"
                            )
                        )
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": quality_migration},
            )
            applied_now.append(quality_migration)

        evidence_migration = "20260718_evidence_quality"
        if evidence_migration not in applied:
            if "autonomous_runs" in tables:
                existing = {
                    column["name"]
                    for column in inspect(connection).get_columns("autonomous_runs")
                }
                for name, definition in _RUN_QUALITY_COLUMNS.items():
                    if name not in existing:
                        connection.execute(
                            text(
                                f"ALTER TABLE autonomous_runs ADD COLUMN {name} {definition}"
                            )
                        )
            if "claim_evidence_links" in tables:
                existing = {
                    column["name"]
                    for column in inspect(connection).get_columns(
                        "claim_evidence_links"
                    )
                }
                for name, definition in _EVIDENCE_QUALITY_COLUMNS.items():
                    if name not in existing:
                        connection.execute(
                            text(
                                "ALTER TABLE claim_evidence_links "
                                f"ADD COLUMN {name} {definition}"
                            )
                        )
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS research_subquestions ("
                    "id VARCHAR(36) PRIMARY KEY, run_id VARCHAR(36) NOT NULL, "
                    "ordinal INTEGER NOT NULL, question TEXT NOT NULL, "
                    "required BOOLEAN NOT NULL DEFAULT TRUE, "
                    "status VARCHAR(24) NOT NULL DEFAULT 'searching', "
                    "CONSTRAINT uq_run_subquestion_ordinal UNIQUE (run_id, ordinal))"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS research_claim_subquestions ("
                    "id VARCHAR(36) PRIMARY KEY, subquestion_id VARCHAR(36) NOT NULL, "
                    "claim_id VARCHAR(36) NOT NULL, relevance_score INTEGER NOT NULL DEFAULT 0, "
                    "status VARCHAR(24) NOT NULL DEFAULT 'candidate', "
                    "CONSTRAINT uq_subquestion_claim UNIQUE (subquestion_id, claim_id))"
                )
            )
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": evidence_migration},
            )
            applied_now.append(evidence_migration)
    return applied_now
