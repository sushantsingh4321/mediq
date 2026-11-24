"""
Deployment step 2: the Vercel files (api/index.py, vercel.json, requirements.txt).
We can't run Vercel inside pytest, so we check the pieces: the function loads
our app, the routes send each URL where it should go, and nothing is missing.
Run from the mediq/ folder with:   pytest
"""

import importlib.util
import json
import pathlib
import re

from fastapi.testclient import TestClient

from backend.app.main import app as real_app

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "vercel.json").read_text())


def load_vercel_function():
    spec = importlib.util.spec_from_file_location("vercel_api_index", ROOT / "api" / "index.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def route_for(path: str):
    """Where vercel.json sends a URL: the first route whose "src" matches, or the static files."""
    for r in CONFIG["routes"]:
        if "handle" in r:
            return "static file"
        if re.fullmatch(r["src"], path):
            return r["dest"]
    return "static file"


def test_the_vercel_function_is_our_fastapi_app():
    module = load_vercel_function()
    assert module.app is real_app
    assert TestClient(module.app).get("/api/health").status_code == 200


def test_urls_go_to_the_right_place():
    assert route_for("/api/departments") == "/api/index"
    assert route_for("/api/appointments/me") == "/api/index"
    assert route_for("/docs") == "/api/index"                 # the API docs come from FastAPI
    assert route_for("/") == "/home.html"                      # the website, not the OPD screens
    assert route_for("/book.html") == "static file"            # pages: Vercel serves them directly
    assert route_for("/style.css") == "static file"


def test_static_files_come_from_frontend():
    assert CONFIG["outputDirectory"] == "frontend"
    for page in ["home.html", "book.html", "login.html", "pharmacy.html", "doctor-appointments.html", "core.js"]:
        assert (ROOT / "frontend" / page).exists(), page


def test_the_function_gets_the_code_and_migrations_it_needs():
    include = CONFIG["functions"]["api/index.py"]["includeFiles"]
    assert "backend" in include and "migrations" in include


def test_requirements_include_the_postgres_driver():
    req = (ROOT / "requirements.txt").read_text()
    assert "psycopg2-binary" in req and "fastapi" in req and "sqlalchemy" in req


def test_python_version_and_no_unsupported_options():
    # Found with "vercel dev": macOS's built-in Python 3.9 can't run Vercel's helper or mediQ
    assert (ROOT / ".python-version").read_text().strip() == "3.12"
    # "maxDuration" in vercel.json broke Vercel's Python builder (DEV_BUILDER_RESULT_HAS_MAXDURATION)
    assert "maxDuration" not in CONFIG["functions"]["api/index.py"]
