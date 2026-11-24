"""
Deployment step 1: secrets and local data never go to GitHub.
Run from the mediq/ folder with:   pytest
"""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MUST_IGNORE = [".env", "*.db", ".DS_Store", "__pycache__/", ".vercel/"]


def test_gitignore_has_the_safety_rules():
    lines = {line.strip() for line in (ROOT / ".gitignore").read_text().splitlines()}
    assert [rule for rule in MUST_IGNORE if rule not in lines] == []
    assert "!.env.example" in lines                      # the template (no real values) IS shared


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="not a git checkout")
def test_no_secrets_or_databases_are_tracked():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    bad = [f for f in tracked
           if f.endswith((".db", ".sqlite", ".DS_Store")) or "__pycache__" in f
           or (f.split("/")[-1].startswith(".env") and f != ".env.example")]
    assert bad == []
