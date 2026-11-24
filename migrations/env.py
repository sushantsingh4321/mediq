"""
Alembic's start-up script: runs whenever you type an `alembic ...` command
(and when the app starts, through database.run_migrations()).

Its two jobs:
  1. connect to OUR database (DATABASE_URL from .env, via backend/app/database.py)
  2. know OUR tables (Base.metadata), so `alembic revision --autogenerate`
     can compare them with the database and write the migration for you.
"""

from logging.config import fileConfig

from alembic import context

from backend.app import db_models  # noqa: F401  (importing it registers the tables on Base)
from backend.app.database import DATABASE_URL, Base, engine

config = context.config

# Use alembic.ini's log settings only when run from the command line, so we
# don't change uvicorn's logging when the app runs migrations on start-up.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    context.configure(url=DATABASE_URL, target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Normal mode: connect and change the database."""
    with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # SQLite rebuilds a table by copying it and DROPPING the old one. With
            # foreign keys switched on, dropping `users` would count as deleting
            # every user, and ON DELETE CASCADE would wipe their OPD sessions.
            # So: keys off while migrating (must be set before the transaction),
            # then check every link is still valid.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()   # SQLAlchemy opened a transaction for the PRAGMA: close it first
        # render_as_batch=True: SQLite can't change an existing column directly,
        # so Alembic rebuilds the table for it. Harmless on PostgreSQL.
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
            if sqlite:
                broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if broken:   # raising here undoes this migration run
                    raise RuntimeError(f"Migration left rows pointing at missing rows: {broken[:5]}")
        if sqlite:
            # This connection goes back to the app's pool: switch the safety check back on.
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
