import gc

import pytest
from sqlalchemy.orm import close_all_sessions

from edusci.memory import database


@pytest.fixture(autouse=True)
def close_database_resources(monkeypatch):
    """Keep tests from leaking SQLite handles across cases on Windows."""
    engines = []
    create_engine = database.create_engine

    def tracked_create_engine(*args, **kwargs):
        engine = create_engine(*args, **kwargs)
        engines.append(engine)
        return engine

    monkeypatch.setattr(database, "create_engine", tracked_create_engine)
    yield
    close_all_sessions()
    for engine in engines:
        engine.dispose()
    gc.collect()
