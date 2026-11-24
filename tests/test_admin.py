"""
Tests for the admin console: GET /api/admin/overview and changing roles.
Run from the mediq/ folder with:   pytest
"""

from fastapi.testclient import TestClient

from backend.app.main import app
from helpers import admin_headers, login_headers, queue_token

client = TestClient(app)
ADMIN = admin_headers()
PASSWORD = "console-password-1"


def make_account(email, role):
    r = client.post("/api/auth/users", headers=ADMIN, json={
        "full_name": f"Console {role}", "email": email, "password": PASSWORD, "role": role})
    assert r.status_code == 201, r.text
    return r.json()["id"], login_headers(email, PASSWORD)


# ---------- overview ----------

def test_overview_is_admin_only():
    _, doctor = make_account("doc@console.example", "doctor")
    assert client.get("/api/admin/overview").status_code == 401
    assert client.get("/api/admin/overview", headers=doctor).status_code == 403
    assert client.get("/api/admin/overview", headers=ADMIN).status_code == 200


def test_overview_counts_go_up():
    before = client.get("/api/admin/overview", headers=ADMIN).json()

    queue_token("Counted", 1)
    client.post("/api/enquiries", json={"name": "Counted", "country_code": "+91", "mobile": "9822222222",
                                        "speciality": "Cardiology", "consent": True})
    client.post("/api/callback", json={"name": "Counted", "mobile": "9822222223", "consent": True})
    client.post("/api/auth/signup", json={"full_name": "Counted", "email": "counted@console.example",
                                          "password": PASSWORD})

    after = client.get("/api/admin/overview", headers=ADMIN).json()
    assert after["queue"]["waiting"] == before["queue"]["waiting"] + 1
    assert after["enquiries_total"] == before["enquiries_total"] + 1
    assert after["enquiries_today"] == before["enquiries_today"] + 1
    assert sum(after["callbacks"].values()) == sum(before["callbacks"].values()) + 1
    assert after["accounts"]["patient"] == before["accounts"]["patient"] + 1
    assert after["beds"]["free"] + after["beds"]["occupied"] == after["beds"]["total"]
    assert "Counted" not in str(after)            # counts only, never names


# ---------- changing roles ----------

def test_admin_changes_a_role_and_it_applies_at_once():
    user_id, headers = make_account("promote@console.example", "pharmacist")
    assert client.get("/api/admin/overview", headers=headers).status_code == 403

    r = client.patch(f"/api/auth/users/{user_id}", headers=ADMIN, json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    # Same token as before: the role is read from the database on every request
    assert client.get("/api/admin/overview", headers=headers).status_code == 200


def test_only_admin_changes_roles():
    user_id, headers = make_account("self-promote@console.example", "pharmacist")
    r = client.patch(f"/api/auth/users/{user_id}", headers=headers, json={"role": "admin"})
    assert r.status_code == 403


def test_admin_cannot_remove_their_own_admin_role():
    me = client.get("/api/auth/me", headers=ADMIN).json()
    r = client.patch(f"/api/auth/users/{me['id']}", headers=ADMIN, json={"role": "patient"})
    assert r.status_code == 400 and "own admin role" in r.json()["detail"]


def test_doctor_with_sessions_must_have_them_removed_first():
    doctor_id, _ = make_account("busy@console.example", "doctor")
    slot = client.post("/api/schedule", headers=ADMIN, json={
        "doctor_id": doctor_id, "department_id": 1, "weekday": 6,
        "start_time": "07:00", "end_time": "08:00", "room": 1}).json()

    r = client.patch(f"/api/auth/users/{doctor_id}", headers=ADMIN, json={"role": "pharmacist"})
    assert r.status_code == 409 and "OPD session" in r.json()["detail"]

    client.delete(f"/api/schedule/{slot['id']}", headers=ADMIN)
    r = client.patch(f"/api/auth/users/{doctor_id}", headers=ADMIN, json={"role": "pharmacist"})
    assert r.status_code == 200


def test_bad_role_or_unknown_account():
    assert client.patch("/api/auth/users/99999", headers=ADMIN, json={"role": "doctor"}).status_code == 404
    user_id, _ = make_account("typo@console.example", "patient")
    assert client.patch(f"/api/auth/users/{user_id}", headers=ADMIN, json={"role": "superuser"}).status_code == 422


def test_console_page_is_served_and_admin_only():
    page = client.get("/admin.html")
    assert page.status_code == 200 and 'data-require-roles="admin"' in page.text


def test_account_times_say_they_are_utc():
    # So the browser converts them to local time correctly (no 5.5-hour shift)
    created = client.get("/api/auth/users", headers=ADMIN).json()[0]["created_at"]
    assert created.endswith("Z") or created.endswith("+00:00")
