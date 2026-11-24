"""
The database connection.

Until now mediQ kept everything in Python memory (lost on restart). User
accounts must survive restarts, so they live in a real database:

    SQLite      a single file (mediq/mediq.db), nothing to install. Great for learning.
    PostgreSQL  a database server, for when mediQ goes live. Only DATABASE_URL changes.

SQLAlchemy is the library that lets us use Python classes (db_models.py)
instead of writing SQL by hand, and works the same for both databases.
"""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import PROJECT_DIR, get_settings

DATABASE_URL = get_settings().database_url

# SQLite only lets the thread that opened a connection use it. FastAPI uses
# several threads, so we switch that check off (safe: each request gets its
# own session, see get_db below). Other databases don't need this.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# The engine knows HOW to reach the database. Create it once for the whole app.
engine = create_engine(DATABASE_URL, connect_args=connect_args)

if DATABASE_URL.startswith("sqlite"):
    # SQLite ignores FOREIGN KEY rules unless you switch them on for every
    # connection. (PostgreSQL always enforces them.) With this on, deleting a
    # doctor's account also deletes their OPD sessions (ondelete="CASCADE").
    @event.listens_for(engine, "connect")
    def _sqlite_foreign_keys_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

# A session is one "conversation" with the database: read, change, then commit.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Every table class in db_models.py inherits from this."""


def get_db():
    """
    FastAPI dependency: gives an endpoint a session and always closes it afterwards.

        @router.get("/me")
        def me(db: Session = Depends(get_db)): ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations():
    """
    Bring the database tables up to date by running Alembic's migrations
    (the same as typing `alembic upgrade head` in the mediq/ folder).
    Called once when the app starts, so you never forget to do it.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(PROJECT_DIR) / "alembic.ini"))
    cfg.attributes["configure_logger"] = False  # keep uvicorn's log settings as they are
    command.upgrade(cfg, "head")
