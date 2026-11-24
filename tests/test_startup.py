"""
Deployment step 5: what happens when the app starts.
Locally: migrations + first admin + demo data. On Vercel: nothing (it runs
once from your laptop, scripts/setup_production.py) and no background jobs.
Run from the mediq/ folder with:   pytest
"""

import os
import pathlib
import sqlite3
import subprocess
import sys

from backend.app.config import get_settings

ROOT = pathlib.Path(__file__).resolve().parent.parent


def start_app_in_a_new_python(tmp_path, **env):
    """Import the app the way Vercel does (api/index.py), in a fresh process, and call /api/health."""
    db = tmp_path / "startup.db"
    code = ("import sys; sys.path.insert(0, '.')\n"
            "from fastapi.testclient import TestClient\n"
            "from api.index import app\n"
            "print(TestClient(app).get('/api/health').status_code)\n")
    clean_env = {k: v for k, v in os.environ.items() if k not in ("VERCEL", "MEDIQ_STARTUP_TASKS")}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                            env={**clean_env, "DATABASE_URL": f"sqlite:///{db}",
                                 "SECRET_KEY": "x" * 40, **env})
    assert result.returncode == 0, result.stderr[-800:]
    tables = {r[0] for r in sqlite3.connect(db).execute("select name from sqlite_master where type='table'")}
    return result.stdout.strip().splitlines()[-1], tables


def test_on_vercel_start_up_does_no_database_work(tmp_path):
    status, tables = start_app_in_a_new_python(tmp_path, VERCEL="1")
    assert status == "200"              # the app answers...
    assert tables == set()              # ...without creating tables or adding data


def test_locally_start_up_migrates_and_seeds(tmp_path):
    status, tables = start_app_in_a_new_python(tmp_path)
    assert status == "200"
    assert {"users", "appointments", "medicines", "alembic_version"} <= tables


def test_the_switch_can_force_it_on_vercel(tmp_path):
    _, tables = start_app_in_a_new_python(tmp_path, VERCEL="1", MEDIQ_STARTUP_TASKS="1")
    assert "users" in tables


def test_callbacks_are_dry_run_unless_someone_says_false(monkeypatch):
    monkeypatch.delenv("DRY_RUN", raising=False)
    assert get_settings().dry_run is True           # not set at all (e.g. forgotten on Vercel): no real calls
    monkeypatch.setenv("DRY_RUN", "true")
    assert get_settings().dry_run is True
    monkeypatch.setenv("DRY_RUN", "false")
    assert get_settings().dry_run is False


def test_no_show_check_runs_when_appointments_are_loaded():
    """There is no timer: the routes that load appointments run sweep_no_shows first."""
    import inspect
    from backend.app import main
    from backend.app.routers import appointments
    for fn in (appointments.my_appointments, appointments.doctor_appointments, appointments.check_in,
               main.call_next):
        assert "sweep_no_shows(" in inspect.getsource(fn), fn.__name__
