"""
Set up (or update) the PRODUCTION database, from your laptop.

On Vercel the app does no start-up work (LEARN.md 19.5), so run this once
before the first deploy, and again whenever there's a new migration:

    1. Make a file .env.production in the mediq/ folder (git never uploads it):

           DATABASE_URL=postgresql://user:password@ep-xxx.aws.neon.tech/neondb?sslmode=require
           ADMIN_EMAIL=you@yourhospital.example
           ADMIN_PASSWORD=a-long-password-only-for-production

    2. From the mediq/ folder:

           .venv/bin/python scripts/setup_production.py

What it does, each step only if needed (safe to run again):
    - migrations: brings every table up to date (alembic upgrade head)
    - the first admin account, from ADMIN_EMAIL / ADMIN_PASSWORD
    - departments (General Medicine, Paediatrics, Orthopaedics): booking needs them
    - sample data: 30 medicines with batches, wards and ambulances
      (skip with --no-sample-data)

Options:
    --env-file FILE     settings file (default: .env.production)
    --yes               don't ask "Continue?" (for automation)
    --no-sample-data    only migrations, the admin and departments
"""

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def fail(message: str) -> None:
    print(f"\nStopped: {message}\n")
    sys.exit(1)


def describe(url: str) -> str:
    """postgresql://user:SECRET@host/db?... -> 'host / db' (never print the password)."""
    parts = urlsplit(url)
    return f"{parts.hostname or 'this computer'} / database '{parts.path.lstrip('/')}'"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Set up the production database (migrations, admin, sample data).")
    parser.add_argument("--env-file", default=".env.production")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--no-sample-data", action="store_true")
    parser.add_argument("--allow-sqlite", action="store_true", help=argparse.SUPPRESS)   # tests only
    args = parser.parse_args(argv)

    # 1. Production settings FIRST, so they win over the local .env the app reads later.
    env_file = (ROOT / args.env_file) if not Path(args.env_file).is_absolute() else Path(args.env_file)
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file, override=True)
        print(f"Settings from {env_file.name}")
    elif not os.getenv("DATABASE_URL"):
        fail(f"{env_file.name} not found and DATABASE_URL isn't set. See the top of this file.")

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        fail("DATABASE_URL is empty. Copy it from Neon (Connection string) into .env.production.")
    if url.startswith("sqlite") and not args.allow_sqlite:
        fail("DATABASE_URL points at a SQLite file. This script is for the production (Neon) database.")
    if not url.startswith("sqlite") and not (url.startswith(("postgresql://", "postgres://", "postgresql+"))
                                             and "@" in url):
        fail("DATABASE_URL in .env.production isn't a database address. It must be ONLY the address, "
             "starting with postgresql:// and containing @ (copy DATABASE_URL_UNPOOLED from Vercel > "
             "Storage > your database, the part after the =). No quotes, no spaces, no 'psql'.")
    if "@" not in os.getenv("ADMIN_EMAIL", "@"):
        fail("ADMIN_EMAIL in .env.production isn't an email address (it has no @).")
    # Checked BEFORE the app reads the local .env, so your LOCAL admin password is never used by accident
    if not (os.getenv("ADMIN_EMAIL") and os.getenv("ADMIN_PASSWORD")):
        fail("ADMIN_EMAIL and ADMIN_PASSWORD must be in .env.production (the production admin's login).")

    # 2. Say where we're about to write, and ask.
    print(f"Database: {describe(url) if not url.startswith('sqlite') else url}")
    print(f"Admin:    {os.environ['ADMIN_EMAIL']}")
    if not args.yes:
        try:
            answer = input("Continue? Type yes: ")
        except (EOFError, KeyboardInterrupt):     # no answer (Ctrl+D / Ctrl+C): treat as "no"
            answer = ""
        if answer.strip().lower() != "yes":
            fail("nothing was changed.")

    # 3. Now load the app, with its own start-up work switched off: we do each step here, out loud.
    os.environ["MEDIQ_STARTUP_TASKS"] = "0"
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import func, select

    from backend.app import main as app_main
    from backend.app.database import SessionLocal, engine, run_migrations
    from backend.app.db_models import AmbulanceRow, DepartmentRow, MedicineRow, Role, User, WardRow
    from backend.app.routers import ambulance, auth, beds
    from backend.app.services import pharmacy_seed

    print("\n1. Migrations ...")
    run_migrations()
    with engine.connect() as conn:
        from alembic.migration import MigrationContext
        print(f"   tables are at version {MigrationContext.configure(conn).get_current_revision()}")

    print("2. Admin account ...")
    auth.seed_first_admin()
    with SessionLocal() as db:
        admins = db.scalars(select(User.email).where(User.role == Role.ADMIN)).all()
    if not admins:
        fail("no admin could be created. Is ADMIN_PASSWORD long enough (see the log line above)?")
    print(f"   admin accounts: {', '.join(admins)}")

    print("3. Departments ...")
    app_main.seed_demo_data()

    if not args.no_sample_data:
        print("4. Sample data: medicines, wards, ambulances ...")
        pharmacy_seed.seed_demo_pharmacy()
        beds.seed_demo_wards()
        ambulance.seed_demo_ambulances()

    with SessionLocal() as db:
        count = lambda row: db.scalar(select(func.count()).select_from(row))   # noqa: E731
        print(f"\nDone. departments: {count(DepartmentRow)}, medicines: {count(MedicineRow)}, "
              f"wards: {count(WardRow)}, ambulances: {count(AmbulanceRow)}, users: {count(User)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
