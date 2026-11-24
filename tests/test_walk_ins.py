"""
Self-booking step 7: walk-ins. With no reception desk, the doctor adds a
patient who just turned up. They're checked in at once and queued by the time
they arrived. Clock: Monday 30 Nov 2026, set per test.
Run from the mediq/ folder with:   pytest
"""

import itertools
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import schedule as schedule_module
from helpers import admin_headers, login_headers

client = TestClient(app)
ADMIN = admin_headers()
PASSWORD = "walkin-password-1"
_n = itertools.count(1)


@pytest.fixture
def set_time(monkeypatch):
    def setter(hhmm):
        h, m = map(int, hhmm.split(":"))
        moment = datetime(2026, 11, 30, h, m, tzinfo=ZoneInfo("Asia/Kolkata"))
        monkeypatch.setattr(schedule_module, "now_local", lambda: moment)
    setter("09:05")
    return setter


@pytest.fixture
def clinic(set_time):
    """A department and a doctor on duty Mondays 09:00-11:00 in Room 1. Returns (dept, doctor_id, headers)."""
    n = next(_n)
    dept = client.post("/api/departments", headers=ADMIN, json={"code": f"W{n}", "name": f"Walk {n}", "doctors": 1}).json()
    email = f"walkdoc{n}@walkin.example"
    doc = client.post("/api/auth/users", headers=ADMIN, json={"full_name": f"Dr. Walk {n}", "email": email,
                                                              "password": PASSWORD, "role": "doctor"}).json()
    client.post("/api/schedule", headers=ADMIN, json={"doctor_id": doc["id"], "department_id": dept["id"],
                "weekday": 0, "start_time": "09:00", "end_time": "11:00", "room": 1})
    return dept, doc["id"], login_headers(email, PASSWORD)


def walk_in(headers, dept, name="Ravi Kumar", **extra):
    return client.post("/api/doctor/walk-ins", headers=headers,
                       json={"patient_name": name, "department_id": dept["id"], **extra})


def live_queue(dept):
    return [t["patient_name"] for t in client.get(f"/api/departments/{dept['id']}/queue", headers=ADMIN).json()]


def test_walk_in_is_checked_in_with_a_token_in_the_live_queue(clinic):
    dept, _, doc_headers = clinic
    r = walk_in(doc_headers, dept, reason="Chest pain since morning")
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "checked_in" and a["source"] == "walk_in" and a["patient_name"] == "Ravi Kumar"
    assert a["token_number"] == f"{dept['code']}-001" and a["token_status"] == "waiting"
    assert a["slot_start"].startswith("09:05") and a["room"] == 1 and a["people_ahead"] == 0
    assert live_queue(dept) == ["Ravi Kumar"]                          # no "I've arrived" needed
    days = client.get("/api/doctor/appointments", headers=doc_headers).json()
    assert days[0]["appointments"][0]["source"] == "walk_in"           # in the doctor's list too


def test_walk_ins_queue_by_arrival_time(clinic, set_time):
    dept, doc, doc_headers = clinic
    email = f"booked{next(_n)}@walkin.example"
    client.post("/api/auth/signup", json={"full_name": "Booked Patient", "email": email, "password": PASSWORD})
    booked = login_headers(email, PASSWORD)
    set_time("08:30")
    b = client.post("/api/appointments", headers=booked, json={"doctor_id": doc, "department_id": dept["id"],
                    "date": "2026-11-30", "slot_start": "09:20", "reason": "Check-up"}).json()
    client.post(f"/api/appointments/{b['id']}/checkin", headers=booked)   # 09:20 booking, already here
    set_time("09:10")
    walk_in(doc_headers, dept, "Early Walker")                         # arrived 09:10: before the 09:20 slot
    set_time("09:30")
    walk_in(doc_headers, dept, "Late Walker")                          # arrived 09:30: after it
    assert live_queue(dept) == ["Early Walker", "Booked Patient", "Late Walker"]


def test_two_walk_ins_at_the_same_moment_both_get_in(clinic):
    dept, _, doc_headers = clinic
    first = walk_in(doc_headers, dept, "First").json()
    second = walk_in(doc_headers, dept, "Second").json()               # the test clock hasn't moved
    assert second["token_number"] != first["token_number"]
    assert live_queue(dept) == ["First", "Second"]


def test_call_next_sees_the_walk_in_and_completes_it(clinic, set_time):
    dept, _, doc_headers = clinic
    a = walk_in(doc_headers, dept).json()
    called = client.post(f"/api/departments/{dept['id']}/call-next?room=1", headers=doc_headers)
    assert called.status_code == 200 and called.json()["number"] == a["token_number"]
    client.post(f"/api/departments/{dept['id']}/finish?room=1", headers=doc_headers)
    days = client.get("/api/doctor/appointments", headers=doc_headers).json()
    assert days[0]["appointments"][0]["status"] == "completed"


def test_who_may_add_walk_ins(clinic):
    dept, doc, doc_headers = clinic
    email = f"pt{next(_n)}@walkin.example"
    client.post("/api/auth/signup", json={"full_name": "P", "email": email, "password": PASSWORD})
    assert walk_in(login_headers(email, PASSWORD), dept).status_code == 403          # patients can't
    assert walk_in({}, dept).status_code == 401
    assert walk_in(doc_headers, dept, name="").status_code == 422                    # a name is needed
    other = client.post("/api/departments", headers=ADMIN, json={"code": f"X{next(_n)}", "name": "Elsewhere", "doctors": 1}).json()
    r = walk_in(doc_headers, other)
    assert r.status_code == 400 and "no OPD sessions" in r.json()["detail"]           # not their department
    r = walk_in(ADMIN, dept, doctor_id=doc)                                          # an admin, for a doctor
    assert r.status_code == 201 and r.json()["doctor_id"] == doc


def test_doctor_page_has_the_walk_in_form():
    assert 'id="walkin-form"' in client.get("/doctor-appointments.html").text
    assert "/doctor/walk-ins" in client.get("/doctor-appointments.js").text
