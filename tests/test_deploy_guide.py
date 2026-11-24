"""
Deployment step 8: DEPLOY.md stays in step with the code it describes.
Run from the mediq/ folder with:   pytest
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUIDE = (ROOT / "DEPLOY.md").read_text()


def test_the_guide_covers_every_stage():
    for must in ("git push", "vercel.com", "Storage", "Neon", "SECRET_KEY", "DRY_RUN",
                 "scripts/setup_production.py", ".env.production", "Redeploy", "/api/health",
                 "Sign up", "Book Appointment", "I've arrived", "Call next", "Dispense"):
        assert must in GUIDE, must


def test_files_and_commands_it_mentions_exist():
    for path in ("api/index.py", "vercel.json", "scripts/setup_production.py", ".env.example"):
        assert (ROOT / path).exists(), path
    # every "git add" path in the guide is a real file or folder
    for line in re.findall(r"^git add (.+)$", GUIDE, re.M):
        for path in line.split():
            assert (ROOT / path).exists(), path


def test_what_the_guide_promises_matches_the_app():
    from fastapi.testclient import TestClient
    from backend.app.main import app
    assert TestClient(app).get("/api/health").json()["status"] == "ok"     # "{"status":"ok", ...}"
    assert "Done. departments:" in (ROOT / "scripts" / "setup_production.py").read_text()
