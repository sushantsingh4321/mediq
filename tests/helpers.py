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


def queue_token(patient_name: str, department_id: int) -> dict:
    """
    Put a patient in a department's queue and return the token as JSON-like dict.
    The reception desk (POST /api/tokens) was removed; bookings and doctors'
    walk-ins use the same store.add_token underneath, so tests use it directly.
    """
    from backend.app.queue_view import to_view
    from backend.app.store import store
    token = store.add_token(patient_name, store.departments[department_id])
    return to_view(token).model_dump(mode="json")
