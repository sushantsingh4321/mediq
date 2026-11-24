"""
Tests for Module 2: doctor schedule (routers/schedule.py) and its link to the queue.

"Now" is pinned with monkeypatch so the tests don't depend on the real clock.
2026-11-23 is a Monday. Run from the mediq/ folder with:   pytest
"""

import itertools
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import schedule as schedule_module
from helpers import admin_headers, login_headers, queue_token

client = TestClient(app)
ADMIN = admin_headers()
IST = ZoneInfo("Asia/Kolkata")
PASSWORD = "doctor-password-1"


def make_doctor(email, name):
    r = client.post("/api/auth/users", headers=ADMIN, json={
        "full_name": name, "email": email, "password": PASSWORD, "role": "doctor"})
    assert r.status_code == 201, r.text
    return r.json()["id"], login_headers(email, PASSWORD)


def make_department(code, doctors=2):
    return client.post("/api/departments", headers=ADMIN, json={
        "code": code, "name": f"Dept {code}", "doctors": doctors}).json()["id"]


def add(doctor_id, dept_id, weekday=0, start="09:00", end="13:00", room=1, headers=ADMIN):
    return client.post("/api/schedule", headers=headers, json={
        "doctor_id": doctor_id, "department_id": dept_id, "weekday": weekday,
        "start_time": start, "end_time": end, "room": room})


def pretend_now(monkeypatch, day, hour, minute=0):
    """Make the app believe it's 2026-11-<day> hour:minute in India."""
    moment = datetime(2026, 11, day, hour, minute, tzinfo=IST)
    monkeypatch.setattr(schedule_module, "now_local", lambda: moment)


# One doctor and one department for most tests
MEERA_ID, MEERA = make_doctor("meera@schedule.example", "Dr. Meera Rao")
DEPT = make_department("SCH", doctors=2)


# ---------- adding sessions ----------

def test_admin_adds_a_session_and_it_shows_in_the_timetable():
    r = add(MEERA_ID, DEPT, weekday=2, start="14:00", end="17:00", room=2)
    assert r.status_code == 201
    body = r.json()
    assert body["doctor_name"] == "Dr. Meera Rao" and body["weekday_name"] == "Wednesday"
    assert body["department_code"] == "SCH"

    timetable = client.get(f"/api/schedule?department_id={DEPT}").json()    # public
    assert any(s["id"] == body["id"] for s in timetable)
    assert "email" not in str(timetable)                                     # names only


def test_only_admin_can_change_the_schedule():
    assert add(MEERA_ID, DEPT, weekday=6, headers={}).status_code == 401
    assert add(MEERA_ID, DEPT, weekday=6, headers=MEERA).status_code == 403   # doctors can't edit
    slot = add(MEERA_ID, DEPT, weekday=6).json()
    assert client.delete(f"/api/schedule/{slot['id']}", headers=MEERA).status_code == 403
    assert client.delete(f"/api/schedule/{slot['id']}", headers=ADMIN).status_code == 204


def test_bad_sessions_are_refused():
    assert add(MEERA_ID, DEPT, weekday=7).status_code == 422                    # no 8th day
    assert add(MEERA_ID, DEPT, weekday=5, start="13:00", end="09:00").status_code == 400
    assert add(MEERA_ID, DEPT, weekday=5, room=3).status_code == 400            # dept has rooms 1-2
    assert add(MEERA_ID, 999, weekday=5).status_code == 404
    patient = client.post("/api/auth/signup", json={"full_name": "P", "email": "p@schedule.example",
                                                    "password": PASSWORD}).json()["user"]["id"]
    assert add(patient, DEPT, weekday=5).status_code == 400                     # not a doctor


def test_clashes_are_refused():
    other_id, _ = make_doctor("ravi@schedule.example", "Dr. Ravi Iyer")
    assert add(MEERA_ID, DEPT, weekday=4, start="09:00", end="12:00", room=1).status_code == 201
    # Same doctor, overlapping time (even in another room)
    clash = add(MEERA_ID, DEPT, weekday=4, start="11:00", end="14:00", room=2)
    assert clash.status_code == 409 and "already has a session" in clash.json()["detail"]
    # Another doctor, same room, overlapping time
    room_clash = add(other_id, DEPT, weekday=4, start="10:00", end="11:00", room=1)
    assert room_clash.status_code == 409 and "Room 1" in room_clash.json()["detail"]
    # Back-to-back is fine (12:00 end, 12:00 start)
    assert add(other_id, DEPT, weekday=4, start="12:00", end="15:00", room=1).status_code == 201


# ---------- who is on duty now ----------

def test_on_duty_now(monkeypatch):
    add(MEERA_ID, DEPT, weekday=0, start="09:00", end="13:00", room=1)       # Monday morning
    pretend_now(monkeypatch, 23, 10)                                         # Monday 10:00
    names = [s["doctor_name"] for s in client.get(f"/api/schedule/on-duty?department_id={DEPT}").json()["on_duty"]]
    assert names == ["Dr. Meera Rao"]

    pretend_now(monkeypatch, 23, 13)                                         # 13:00: session has ended
    assert client.get(f"/api/schedule/on-duty?department_id={DEPT}").json()["on_duty"] == []
    pretend_now(monkeypatch, 24, 10)                                         # Tuesday
    assert client.get(f"/api/schedule/on-duty?department_id={DEPT}").json()["on_duty"] == []


def test_doctor_list_is_public_and_has_names_only():
    doctors = client.get("/api/schedule/doctors").json()
    assert {"id": MEERA_ID, "full_name": "Dr. Meera Rao"} in doctors
    assert "@" not in str(doctors)


# ---------- the link with the queue ----------

_fixture_number = itertools.count(1)


@pytest.fixture
def queue_with_a_patient():
    """A fresh department with Dr. Patel on Thursdays 09:00-12:00 in Room 2, and one patient waiting."""
    n = next(_fixture_number)        # each test gets its own doctor and department
    doctor_id, doctor = make_doctor(f"patel{n}@schedule.example", "Dr. Anil Patel")
    dept = make_department(f"Q{n}", doctors=2)
    add(doctor_id, dept, weekday=3, start="09:00", end="12:00", room=2)
    queue_token("Waiting", dept)
    return dept, doctor


def test_on_duty_doctor_can_call_next(monkeypatch, queue_with_a_patient):
    dept, doctor = queue_with_a_patient
    pretend_now(monkeypatch, 26, 9, 30)                                      # Thursday 09:30
    r = client.post(f"/api/departments/{dept}/call-next?room=2", headers=doctor)
    assert r.status_code == 200 and r.json()["status"] == "in_consultation"


def test_off_duty_doctor_cannot_call_next(monkeypatch, queue_with_a_patient):
    dept, doctor = queue_with_a_patient
    pretend_now(monkeypatch, 26, 15)                                         # Thursday 15:00, after the session
    r = client.post(f"/api/departments/{dept}/call-next?room=2", headers=doctor)
    assert r.status_code == 403
    assert "not on OPD duty" in r.json()["detail"]
    assert "Thursday 09:00-12:00, Room 2" in r.json()["detail"]              # tells them when


def test_doctor_must_use_their_own_room(monkeypatch, queue_with_a_patient):
    dept, doctor = queue_with_a_patient
    pretend_now(monkeypatch, 26, 10)
    r = client.post(f"/api/departments/{dept}/call-next?room=1", headers=doctor)
    assert r.status_code == 403 and "Room 2" in r.json()["detail"]


def test_admin_can_always_call_next(monkeypatch, queue_with_a_patient):
    dept, _ = queue_with_a_patient
    pretend_now(monkeypatch, 22, 3)                                          # Sunday 3 a.m.
    assert client.post(f"/api/departments/{dept}/call-next?room=1", headers=ADMIN).status_code == 200


def test_deleting_a_doctor_removes_their_sessions():
    doctor_id, _ = make_doctor("leaving@schedule.example", "Dr. Leaving")
    add(doctor_id, DEPT, weekday=1, start="16:00", end="18:00", room=2)
    from backend.app.database import SessionLocal
    from backend.app.db_models import User
    with SessionLocal() as db:
        db.delete(db.get(User, doctor_id))
        db.commit()
    assert client.get(f"/api/schedule?doctor_id={doctor_id}").json() == []   # CASCADE
