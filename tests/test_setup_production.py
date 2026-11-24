"""
Deployment step 6: scripts/setup_production.py (migrations + admin + sample data).
It was also run twice against a real PostgreSQL (LEARN.md 19.6). Here we run it
on a throwaway SQLite file (allowed only with a hidden test flag) and check the
times it must REFUSE to run.
Run from the mediq/ folder with:   pytest
"""

import os
import pathlib
import sqlite3
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def run_script(tmp_path, env_lines, *flags):
    env_file = tmp_path / "env.production"
    env_file.write_text("\n".join(env_lines) + "\n")
    clean = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "ADMIN_EMAIL", "ADMIN_PASSWORD")}
    return subprocess.run([sys.executable, "scripts/setup_production.py", "--env-file", str(env_file), *flags],
                          cwd=ROOT, capture_output=True, text=True, env=clean, input="")


def test_sets_up_an_empty_database_and_is_safe_to_run_again(tmp_path):
    db = tmp_path / "prod.db"
    lines = [f"DATABASE_URL=sqlite:///{db}", "ADMIN_EMAIL=boss@prod.example", "ADMIN_PASSWORD=prod-only-password-123"]
    first = run_script(tmp_path, lines, "--yes", "--allow-sqlite")
    assert first.returncode == 0, first.stdout + first.stderr
    assert "departments: 3, medicines: 30, wards: 3, ambulances: 4, users: 1" in first.stdout
    again = run_script(tmp_path, lines, "--yes", "--allow-sqlite")
    assert "departments: 3, medicines: 30, wards: 3, ambulances: 4, users: 1" in again.stdout   # no duplicates
    con = sqlite3.connect(db)
    assert con.execute("select email, role from users").fetchall() == [("boss@prod.example", "admin")]
    assert con.execute("select version_num from alembic_version").fetchone()[0] == "0011"


def test_no_sample_data_keeps_only_the_essentials(tmp_path):
    lines = [f"DATABASE_URL=sqlite:///{tmp_path / 'p.db'}", "ADMIN_EMAIL=b@prod.example", "ADMIN_PASSWORD=prod-only-password-123"]
    r = run_script(tmp_path, lines, "--yes", "--allow-sqlite", "--no-sample-data")
    assert "departments: 3, medicines: 0, wards: 0, ambulances: 0, users: 1" in r.stdout


def test_refuses_sqlite_without_the_test_flag(tmp_path):
    r = run_script(tmp_path, [f"DATABASE_URL=sqlite:///{tmp_path / 'x.db'}", "ADMIN_EMAIL=a@b.example",
                              "ADMIN_PASSWORD=prod-only-password-123"], "--yes")
    assert r.returncode == 1 and "SQLite" in r.stdout


def test_refuses_without_a_production_admin(tmp_path):
    r = run_script(tmp_path, ["DATABASE_URL=postgresql://u:p@example.invalid/db?sslmode=require"], "--yes")
    assert r.returncode == 1 and "ADMIN_EMAIL and ADMIN_PASSWORD" in r.stdout   # never borrows the LOCAL admin


def test_asks_before_changing_anything(tmp_path):
    lines = [f"DATABASE_URL=sqlite:///{tmp_path / 'ask.db'}", "ADMIN_EMAIL=a@b.example", "ADMIN_PASSWORD=prod-only-password-123"]
    r = run_script(tmp_path, lines, "--allow-sqlite")                  # no --yes, and we answer nothing
    assert r.returncode == 1 and "nothing was changed" in r.stdout
    assert not (tmp_path / "ask.db").exists()


def test_never_prints_the_database_password(tmp_path):
    r = run_script(tmp_path, ["DATABASE_URL=postgresql://user:SuperSecret99@ep-x.neon.tech/neondb?sslmode=require",
                              "ADMIN_EMAIL=a@b.example", "ADMIN_PASSWORD=prod-only-password-123"])
    assert "ep-x.neon.tech" in r.stdout and "SuperSecret99" not in r.stdout + r.stderr


def test_placeholder_text_gets_a_plain_message(tmp_path):
    r = run_script(tmp_path, ["DATABASE_URL=PASTE-THE-ADDRESS-FROM-5a-HERE", "ADMIN_EMAIL=a@b.example",
                              "ADMIN_PASSWORD=prod-only-password-123"], "--yes")
    assert r.returncode == 1 and "isn't a database address" in r.stdout and "Traceback" not in r.stderr
    r = run_script(tmp_path, ["DATABASE_URL=postgresql://u:p@ep-x.neon.tech/db?sslmode=require",
                              "ADMIN_EMAIL=YOUR-EMAIL", "ADMIN_PASSWORD=prod-only-password-123"], "--yes")
    assert r.returncode == 1 and "isn't an email address" in r.stdout
