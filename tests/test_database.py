"""
Tests for step 1: the database and the users table.
They use the separate test database set up in conftest.py, never mediq.db.
Run from the mediq/ folder with:   pytest
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

import backend.app.main  # noqa: F401  (importing the app runs the migrations)
from backend.app.database import DATABASE_URL, Base, SessionLocal, engine
from backend.app.db_models import Role, User


def make_user(db, email, **extra):
    """Helper: add one user and save it."""
    user = User(full_name="Test Person", email=email, hashed_password="not-a-real-hash", **extra)
    db.add(user)
    db.commit()
    return user


def test_tests_use_their_own_database():
    assert "mediq-tests-" in DATABASE_URL       # the temp file from conftest.py
    assert not DATABASE_URL.endswith("/mediq.db")


def test_users_table_has_the_right_columns():
    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    assert columns == {"id", "full_name", "email", "phone", "hashed_password", "role", "created_at",
                       "auto_accept"}   # auto_accept: doctors only (self-booking, migration 0009)


def test_migrations_match_the_models():
    # If someone edits db_models.py but forgets to write a migration, this fails.
    with engine.connect() as conn:
        differences = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert differences == []


def test_save_and_read_a_user():
    with SessionLocal() as db:
        saved = make_user(db, "asha@example.com", phone="+919876543210")
        assert saved.id is not None                   # the database gave it an id

    with SessionLocal() as db:                         # a fresh session: really from the database
        found = db.scalars(select(User).where(User.email == "asha@example.com")).one()
        assert found.full_name == "Test Person"
        assert found.role == Role.PATIENT             # the default role
        assert found.created_at is not None


def test_email_must_be_unique():
    with SessionLocal() as db:
        make_user(db, "same@example.com")
        with pytest.raises(IntegrityError):            # the DATABASE refuses the duplicate
            make_user(db, "same@example.com")
        db.rollback()


def test_role_is_stored_as_text():
    with SessionLocal() as db:
        make_user(db, "doc@example.com", role=Role.DOCTOR)
        raw = db.connection().exec_driver_sql(
            "SELECT role FROM users WHERE email = 'doc@example.com'").scalar_one()
    assert raw == "doctor"
