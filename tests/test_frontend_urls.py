"""
Deployment step 3: the frontend only ever calls the API with RELATIVE URLs
("/api/..."), so the same pages work on http://localhost:8000 and on the
Vercel address, with no change. This test fails if a fixed address sneaks in.
Run from the mediq/ folder with:   pytest
"""

import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parent.parent / "frontend"
FILES = sorted(FRONTEND.glob("*.html")) + sorted(FRONTEND.glob("*.js"))
ALLOWED_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com", "www.w3.org")   # fonts, SVG namespace


def code_only(text: str) -> str:
    """The file without // and <!-- --> comments (comments may mention example addresses)."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return re.sub(r"(^|[^:])//[^\n]*", r"\1", text)


def test_no_fixed_server_address_in_the_frontend():
    problems = []
    for f in FILES:
        code = code_only(f.read_text())
        for bad in ("localhost", "127.0.0.1", ":8000"):
            if bad in code:
                problems.append(f"{f.name}: contains {bad}")
        for url in re.findall(r"https?://[^\s\"'`)<>]+", code):
            if not url.split("/")[2].startswith(ALLOWED_HOSTS):
                problems.append(f"{f.name}: absolute URL {url}")
    assert problems == []


def test_every_fetch_goes_to_a_relative_api_path():
    calls = {f.name: re.findall(r"fetch\(([^,)]+)", code_only(f.read_text())) for f in FILES}
    calls = {name: c for name, c in calls.items() if c}
    assert calls == {"app.js": ["API + path"], "core.js": ['"/api" + path']}
    assert 'const API = "/api";' in (FRONTEND / "app.js").read_text()
