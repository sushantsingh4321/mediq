"""
Deployment step 4: the database address and serverless safety.
(The full test suite was also run against a real PostgreSQL: see LEARN.md 19.4.)
Run from the mediq/ folder with:   pytest
"""

import pytest

from backend.app import security
from backend.app.config import normalize_database_url


@pytest.mark.parametrize("given, expected", [
    # What Neon shows you: SQLAlchemy 2.1 would read it as psycopg 3, which we don't install
    ("postgresql://u:p@ep-cool-1.aws.neon.tech/neondb?sslmode=require",
     "postgresql+psycopg2://u:p@ep-cool-1.aws.neon.tech/neondb?sslmode=require"),
    # Older style some tools still give out
    ("postgres://u:p@host/db?sslmode=require", "postgresql+psycopg2://u:p@host/db?sslmode=require"),
    # Already names a driver, or SQLite: left alone
    ("postgresql+psycopg2://u:p@host/db", "postgresql+psycopg2://u:p@host/db"),
    ("sqlite:////tmp/mediq.db", "sqlite:////tmp/mediq.db"),
])
def test_database_urls_use_our_driver(given, expected):
    assert normalize_database_url(given) == expected


def test_postgres_uses_nullpool_for_serverless(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    # Build the same kind of engine database.py builds for PostgreSQL (no connection is made)
    engine = create_engine(normalize_database_url("postgresql://u:p@localhost/db"), poolclass=NullPool)
    assert isinstance(engine.pool, NullPool) and engine.dialect.driver == "psycopg2"
    src = open(security.__file__.replace("security.py", "database.py")).read()
    assert "poolclass=NullPool" in src


def test_missing_secret_key_stops_the_app_on_vercel(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "")
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(RuntimeError, match="SECRET_KEY is not set"):
        security.get_secret_key()


def test_missing_secret_key_locally_still_works_with_a_warning(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "")
    monkeypatch.delenv("VERCEL", raising=False)
    assert len(security.get_secret_key()) >= 32
