from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from edusci.memory.migrations import upgrade_database


class Base(DeclarativeBase):
    pass


def build_session_factory(database_url: str) -> sessionmaker:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, future=True)
    if database_url.startswith(("postgresql", "postgres")):
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    upgrade_database(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def managed_session(database_url: str) -> Generator[Session, None, None]:
    session_factory = build_session_factory(database_url)
    try:
        with session_factory() as session:
            yield session
    finally:
        session_factory.kw["bind"].dispose()
