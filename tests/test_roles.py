"""
Tests for step 4: roles and protected endpoints.

    401 = not logged in        403 = logged in, but the wrong role
Admins are allowed everywhere. Run from the mediq/ folder with:   pytest
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import schedule as schedule_module
from backend.app.routers.auth import seed_first_admin
from helpers import admin_headers, bearer, login_headers, queue_token

client = TestClient(app)          # NOT logged in; each test passes headers itself
PASSWORD = "staff-password-1"


def make_account(email, role):
    """Helper: the admin creates an account, then we log in as it."""
    r = client.post("/api/auth/users", headers=admin_headers(), json={
        "full_name": f"Test {role}", "email": email, "password": PASSWORD, "role": role})
    assert r.status_code == 201, r.text
    return login_headers(email, PASSWORD)


def make_patient(email):
    r = client.post("/api/auth/signup", json={"full_name": "Pat", "email": email, "password": PASSWORD})
    return bearer(r.json()["access_token"])


# One account of each kind, shared by the tests in this file
DOCTOR = make_account("doctor@roles.example", "doctor")
PHARMACIST = make_account("pharmacy@roles.example", "pharmacist")
PATIENT = make_patient("patient@roles.example")
ADMIN = admin_headers()


# ---------- the first admin ----------

def test_first_admin_is_created_from_env_once():
    me = client.get("/api/auth/me", headers=ADMIN).json()
    assert me["email"] == "admin@mediq.example" and me["role"] == "admin"

    def admin_count():
        return sum(u["role"] == "admin" for u in client.get("/api/auth/users", headers=ADMIN).json())

    before = admin_count()
    seed_first_admin()   # running it again (a restart) must not create another admin
    assert admin_count() == before


# ---------- who can create staff accounts ----------

def test_only_admin_creates_staff_accounts():
    new = {"full_name": "Dr X", "email": "drx@roles.example", "password": PASSWORD, "role": "doctor"}
    assert client.post("/api/auth/users", json=new).status_code == 401                    # not logged in
    assert client.post("/api/auth/users", json=new, headers=PATIENT).status_code == 403
    assert client.post("/api/auth/users", json=new, headers=DOCTOR).status_code == 403
    assert client.post("/api/auth/users", json=new, headers=PHARMACIST).status_code == 403
    created = client.post("/api/auth/users", json=new, headers=ADMIN)
    assert created.status_code == 201 and created.json()["role"] == "doctor"


def test_account_list_is_admin_only_and_has_no_passwords():
    assert client.get("/api/auth/users", headers=DOCTOR).status_code == 403
    users = client.get("/api/auth/users", headers=ADMIN)
    assert users.status_code == 200 and "hashed_password" not in users.text


# ---------- doctor screen ----------

def test_call_next_needs_a_doctor():
    url = "/api/departments/1/call-next?room=1"
    assert client.post(url).status_code == 401
    assert client.post(url, headers=PATIENT).status_code == 403
    denied = client.post(url, headers=PHARMACIST)
    assert denied.status_code == 403 and denied.json()["detail"] == "This needs a doctor account."
    # A doctor gets past the ROLE check, but (Module 2) only during their own
    # OPD session. This doctor has no sessions, so it's still 403, with a reason.
    off_duty = client.post(url, headers=DOCTOR)
    assert off_duty.status_code == 403 and "not on OPD duty" in off_duty.json()["detail"]
    assert client.post("/api/departments/1/finish?room=1", headers=PATIENT).status_code == 403


# ---------- the reception desk was removed ----------

def test_reception_role_and_route_are_gone():
    body = {"patient_name": "Walk-in", "department_id": 1}
    assert client.post("/api/tokens", json=body, headers=ADMIN).status_code in (404, 405)
    new = {"full_name": "Desk", "email": "desk@roles.example", "password": PASSWORD, "role": "receptionist"}
    assert client.post("/api/auth/users", json=new, headers=ADMIN).status_code == 422   # not a role any more


# ---------- dashboard ----------

def test_changing_departments_needs_an_admin():
    dept = client.get("/api/departments").json()[0]
    assert client.put(f"/api/departments/{dept['id']}", json=dept).status_code == 401
    assert client.put(f"/api/departments/{dept['id']}", json=dept, headers=DOCTOR).status_code == 403
    assert client.put(f"/api/departments/{dept['id']}", json=dept, headers=ADMIN).status_code == 200


# ---------- staff lists with names and phone numbers ----------

def test_staff_lists_are_hidden_from_patients_and_strangers():
    # Phone numbers and messages: staff only
    for url in ["/api/callback", "/api/enquiries"]:
        assert client.get(url).status_code == 401, url
        assert client.get(url, headers=PATIENT).status_code == 403, url
        assert client.get(url, headers=ADMIN).status_code == 200, url
    assert client.get("/api/callback", headers=DOCTOR).status_code == 403    # admins handle call-backs now


def test_everyone_can_view_queue_and_beds_but_only_staff_see_names():
    dept = client.get("/api/departments").json()[0]
    queue_token("Kavya Rao Iyer", dept["id"])
    queue_url = f"/api/departments/{dept['id']}/queue"
    for headers in [{}, PATIENT]:                      # a visitor, then a logged-in patient
        names = [t["patient_name"] for t in client.get(queue_url, headers=headers).json()]
        assert "K. R. I." in names and "Kavya Rao Iyer" not in names
        assert client.get("/api/wards", headers=headers).status_code == 200
    names = [t["patient_name"] for t in client.get(queue_url, headers=DOCTOR).json()]
    assert "Kavya Rao Iyer" in names
    # A broken or expired token is treated as a visitor, not an error
    assert client.get("/api/wards", headers={"Authorization": "Bearer nonsense"}).status_code == 200


# ---------- the public website keeps working without a login ----------

def test_public_pages_still_work_without_login():
    for url in ["/api/site", "/api/departments", "/api/departments/1/stats",
                "/api/wards/availability", "/api/hospital/summary", "/"]:
        assert client.get(url).status_code == 200, url
    assert client.post("/api/enquiries", json={
        "name": "Public", "country_code": "+91", "mobile": "9811111111",
        "speciality": "Cardiology", "consent": True}).status_code == 201
    assert client.post("/api/callback", json={
        "name": "Public", "mobile": "9811111112", "consent": True}).status_code == 201


# ---------- step 6: a full journey with real roles ----------

def test_patient_in_queue_and_doctor_calls_them(monkeypatch):
    dept = client.post("/api/departments", headers=ADMIN, json={
        "code": "RLS", "name": "Roles Test", "doctors": 1}).json()

    # Module 2: give the doctor a Monday 09:00-13:00 session and pretend it's Monday 10:00
    doctor_id = client.get("/api/auth/me", headers=DOCTOR).json()["id"]
    assert client.post("/api/schedule", headers=ADMIN, json={
        "doctor_id": doctor_id, "department_id": dept["id"], "weekday": 0,
        "start_time": "09:00", "end_time": "13:00", "room": 1}).status_code == 201
    monkeypatch.setattr(schedule_module, "now_local",
                        lambda: datetime(2026, 11, 23, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")))  # a Monday
    queue_token("Journey", dept["id"])

    queue = client.get(f"/api/departments/{dept['id']}/queue", headers=DOCTOR).json()
    assert [t["patient_name"] for t in queue] == ["Journey"]

    called = client.post(f"/api/departments/{dept['id']}/call-next?room=1", headers=DOCTOR)
    assert called.status_code == 200 and called.json()["number"] == "RLS-001"
    assert client.post(f"/api/departments/{dept['id']}/finish?room=1", headers=DOCTOR).status_code == 200
