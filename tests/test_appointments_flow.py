"""
Self-booking step 5: the token flow on the day.
Expected wait, "I've arrived" (check-in), only checked-in tokens in the live
queue, Call next, completed, and no-show after 15 minutes.

The clock is set per test with set_time("09:00") (Monday 30 Nov 2026, hospital time).
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
PASSWORD = "flow-password-1"
_n = itertools.count(1)


@pytest.fixture
def set_time(monkeypatch):
    def setter(hhmm, day=30):
        h, m = map(int, hhmm.split(":"))
        moment = datetime(2026, 11, day, h, m, tzinfo=ZoneInfo("Asia/Kolkata"))
        monkeypatch.setattr(schedule_module, "now_local", lambda: moment)
    setter("08:00")
    return setter


def patient():
    email = f"flow{next(_n)}@flow.example"
    client.post("/api/auth/signup", json={"full_name": f"Flow Patient {next(_n)}", "email": email, "password": PASSWORD})
    return login_headers(email, PASSWORD)


@pytest.fixture
def clinic(set_time):
    """A department and a doctor on duty Mondays 09:00-10:00 in Room 1. Returns (dept, doctor_id, doctor headers)."""
    n = next(_n)
    dept = client.post("/api/departments", headers=ADMIN, json={"code": f"F{n}", "name": f"Flow {n}",
                                                                 "doctors": 1, "avg_consult_minutes": 10}).json()
    email = f"flowdoc{n}@flow.example"
    doc = client.post("/api/auth/users", headers=ADMIN, json={"full_name": f"Dr. Flow {n}", "email": email,
                                                              "password": PASSWORD, "role": "doctor"}).json()
    client.post("/api/schedule", headers=ADMIN, json={"doctor_id": doc["id"], "department_id": dept["id"],
                "weekday": 0, "start_time": "09:00", "end_time": "10:00", "room": 1})
    return dept, doc["id"], login_headers(email, PASSWORD)


def book(headers, dept, doctor_id, start):
    r = client.post("/api/appointments", headers=headers, json={
        "doctor_id": doctor_id, "department_id": dept["id"], "date": "2026-11-30", "slot_start": start,
        "reason": "Check-up"})
    assert r.status_code == 201, r.text
    return r.json()


def mine(headers):
    return client.get("/api/appointments/me", headers=headers).json()[0]


def check_in(headers, appt):
    return client.post(f"/api/appointments/{appt['id']}/checkin", headers=headers)


def live_queue(dept):
    return [t["number"] for t in client.get(f"/api/departments/{dept['id']}/queue", headers=ADMIN).json()]


# ---------------------------------------------------------------- check-in

def test_check_in_opens_one_hour_before(clinic, set_time):
    dept, doc, _ = clinic
    me = patient()
    a = book(me, dept, doc, "09:20")
    assert mine(me)["can_check_in"] is False
    r = check_in(me, a)                                         # 08:00: too early
    assert r.status_code == 409 and "opens at 08:20" in r.json()["detail"]
    set_time("08:20")
    assert mine(me)["can_check_in"] is True
    r = check_in(me, a)
    assert r.status_code == 200 and r.json()["status"] == "checked_in" and r.json()["token_status"] == "waiting"
    assert check_in(me, a).status_code == 409                   # twice


def test_only_checked_in_tokens_are_in_the_live_queue(clinic, set_time):
    dept, doc, _ = clinic
    here, away = patient(), patient()
    a = book(here, dept, doc, "09:00")
    book(away, dept, doc, "09:10")
    assert live_queue(dept) == []                               # both booked, nobody here yet
    set_time("08:30")
    check_in(here, a)
    assert live_queue(dept) == [a["token_number"]]


def test_expected_wait_from_the_queue_maths(clinic, set_time):
    dept, doc, _ = clinic
    first, second = patient(), patient()
    a = book(first, dept, doc, "09:00")
    b = book(second, dept, doc, "09:20")
    assert mine(second)["people_ahead"] == 0                    # nobody checked in yet
    set_time("08:30")
    check_in(first, a)
    view = mine(second)                                         # "if you checked in now"
    assert view["people_ahead"] == 1 and view["estimated_wait_minutes"] == 10.0   # 1 doctor, 10 min each
    set_time("08:45")
    check_in(second, b)
    assert mine(second)["people_ahead"] == 1


def test_call_next_takes_the_earlier_slot_first_and_completes_the_booking(clinic, set_time):
    dept, doc, doc_headers = clinic
    early, late = patient(), patient()
    a_late = book(late, dept, doc, "09:30")
    a_early = book(early, dept, doc, "09:10")
    set_time("08:40")
    check_in(late, a_late)                                      # the 09:30 patient arrives first...
    check_in(early, a_early)
    set_time("09:05")
    called = client.post(f"/api/departments/{dept['id']}/call-next?room=1", headers=doc_headers)
    assert called.status_code == 200 and called.json()["number"] == a_early["token_number"]   # ...but 09:10 goes first
    assert mine(early)["token_room"] == 1 and mine(early)["token_status"] == "in_consultation"
    client.post(f"/api/departments/{dept['id']}/call-next?room=1", headers=doc_headers)
    assert mine(early)["status"] == "completed"                 # seen -> the booking is completed
    client.post(f"/api/departments/{dept['id']}/finish?room=1", headers=doc_headers)
    assert mine(late)["status"] == "completed"


# ---------------------------------------------------------------- no-show

def test_no_show_after_15_minutes(clinic, set_time):
    dept, doc, doc_headers = clinic
    me = patient()
    a = book(me, dept, doc, "09:00")
    set_time("09:15")
    assert mine(me)["status"] == "accepted"                     # exactly 15 minutes: still on time
    set_time("09:16")
    seen = mine(me)
    assert seen["status"] == "no_show" and seen["token_status"] == "cancelled"
    r = check_in(me, a)
    assert r.status_code == 409 and "missed" in r.json()["detail"]
    # The patient turns up late; the doctor decides to see them anyway
    r = check_in(doc_headers, a)
    assert r.status_code == 200 and r.json()["status"] == "checked_in" and r.json()["token_status"] == "waiting"


def test_call_next_never_calls_a_no_show(clinic, set_time):
    dept, doc, doc_headers = clinic
    book(patient(), dept, doc, "09:00")
    set_time("09:20")
    r = client.post(f"/api/departments/{dept['id']}/call-next?room=1", headers=doc_headers)
    assert r.status_code == 404                                 # nobody waiting: the 09:00 patient never came


# ---------------------------------------------------------------- who may check in

def test_who_may_check_in(clinic, set_time):
    dept, doc, doc_headers = clinic
    me, stranger = patient(), patient()
    a = book(me, dept, doc, "09:00")
    set_time("08:30")
    assert check_in(stranger, a).status_code == 404             # someone else's booking
    other_doctor = client.post("/api/auth/users", headers=ADMIN, json={
        "full_name": "Dr. Other", "email": f"other{next(_n)}@flow.example", "password": PASSWORD, "role": "doctor"}).json()
    other_headers = login_headers(other_doctor["email"], PASSWORD)
    assert check_in(other_headers, a).status_code == 404        # another doctor
    r = check_in(doc_headers, a)                                # the booking's doctor
    assert r.status_code == 200


def test_check_in_only_on_the_day(clinic, set_time):
    dept, doc, _ = clinic
    me = patient()
    a = book(me, dept, doc, "09:00")
    set_time("09:00", day=29)                                   # Sunday, the day before
    r = check_in(me, a)
    assert r.status_code == 409 and "only on the day" in r.json()["detail"]


def test_pages_have_the_arrival_buttons():
    assert "data-checkin" in client.get("/my-appointments.js").text          # "I've arrived"
    assert "It's your turn" in client.get("/my-appointments.js").text
    assert "data-checkin" in client.get("/doctor-appointments.js").text      # the doctor's "Check in"


def test_patient_sees_their_own_name_on_their_token(clinic):
    dept, doc, _ = clinic
    me = patient()
    a = book(me, dept, doc, "09:40")
    own = client.get(f"/api/tokens/{a['token_id']}", headers=me).json()
    assert own["patient_name"] == a["patient_name"]                       # full name for the owner
    assert client.get(f"/api/tokens/{a['token_id']}").json()["patient_name"] != a["patient_name"]   # initials for others
