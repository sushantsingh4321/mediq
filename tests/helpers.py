"""
Shared test helpers: log in and get an "Authorization" header.

Most endpoints now need a login (step 4). Tests written before that use
admin_headers(), because an admin is allowed everywhere.
"""

from functools import cache

from fastapi.testclient import TestClient

from backend.app.main import app

_client = TestClient(app)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login_headers(email: str, password: str) -> dict:
    r = _client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return bearer(r.json()["access_token"])


@cache  # log in once and reuse the token for the whole test run
def admin_headers() -> dict:
    """The admin created on start-up from ADMIN_EMAIL / ADMIN_PASSWORD (see conftest.py)."""
    return login_headers("admin@mediq.example", "test-admin-password")
