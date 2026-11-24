"""
Self-booking step 3: the patient side (services/appointments.py, routers/appointments.py).
Slots from the doctor's schedule, booking, double-booking, "my appointments", cancelling.

"Now" is fixed to Monday 30 Nov 2026, 08:00 hospital time, so the tests give the
same answer on any day. Run from the mediq/ folder with:   pytest
"""

import itertools
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.app.database import SessionLocal
from backend.app.db_models import User
from backend.app.main import app
from backend.app.routers import schedule as schedule_module
from helpers import admin_headers, login_headers

client = TestClient(app)
ADMIN = admin_headers()
PASSWORD = "patient-password-1"
MONDAY = "2026-11-30"
_n = itertools.count(1)


def at(text):
    """Pretend it is this hospital time, e.g. at("2026-11-30 08:00")."""
    moment = datetime.fromisoformat(text).replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    return lambda: moment


@pytest.fixture(autouse=True)
def monday_morning(monkeypatch):
    monkeypatch.setattr(schedule_module, "now_local", at(f"{MONDAY} 08:00"))


def patient():
    email = f"booker{next(_n)}@appt.example"
    client.post("/api/auth/signup", json={"full_name": f"Patient {email[:8]}", "email": email, "password": PASSWORD})
    return login_headers(email, PASSWORD)


@pytest.fixture
def clinic():
    """A department and a doctor working Mondays 09:00-10:00 in Room 4. Returns (dept_id, doctor_id, doctor headers)."""
    n = next(_n)
    dept = client.post("/api/departments", headers=ADMIN, json={"code": f"B{n}", "name": f"Booking {n}",
                                                                 "doctors": 4}).json()
    email = f"doc{n}@appt.example"
    doctor = client.post("/api/auth/users", headers=ADMIN, json={"full_name": f"Dr. Book {n}", "email": email,
                                                                 "password": PASSWORD, "role": "doctor"}).json()
    assert client.post("/api/schedule", headers=ADMIN, json={
        "doctor_id": doctor["id"], "department_id": dept["id"], "weekday": 0,
        "start_time": "09:00", "end_time": "10:00", "room": 4}).status_code == 201
    return dept["id"], doctor["id"], login_headers(email, PASSWORD)


def book(headers, dept, doctor, start="09:00", day=MONDAY, reason="Fever for 3 days"):
    return client.post("/api/appointments", headers=headers, json={
        "doctor_id": doctor, "department_id": dept, "date": day, "slot_start": start, "reason": reason})


# ---------------------------------------------------------------- doctors and slots

def test_doctors_are_listed_by_department(clinic):
    dept, doctor, _ = clinic
    found = client.get(f"/api/doctors?department_id={dept}").json()       # no login needed
    assert [d["id"] for d in found] == [doctor]
    assert found[0]["sessions"][0] == {"weekday": 0, "weekday_name": "Monday", "start_time": "09:00:00",
                                       "end_time": "10:00:00", "room": 4}
    assert "email" not in found[0]


def test_a_session_is_cut_into_ten_minute_slots(clinic):
    dept, doctor, _ = clinic
    day = client.get(f"/api/doctors/{doctor}/slots?date={MONDAY}&department_id={dept}").json()
    assert day["slot_minutes"] == 10
    assert [s["start"][:5] for s in day["slots"]] == ["09:00", "09:10", "09:20", "09:30", "09:40", "09:50"]
    assert all(s["free"] and s["room"] == 4 for s in day["slots"])
    # Tuesday: no session, so no slots
    assert client.get(f"/api/doctors/{doctor}/slots?date=2026-12-01").json()["slots"] == []


def test_past_and_booked_slots_are_not_free(clinic, monkeypatch):
    dept, doctor, _ = clinic
    assert book(patient(), dept, doctor, "09:40").status_code == 201
    monkeypatch.setattr(schedule_module, "now_local", at(f"{MONDAY} 09:15"))
    slots = {s["start"][:5]: s["why_not"] for s in
             client.get(f"/api/doctors/{doctor}/slots?date={MONDAY}").json()["slots"]}
    assert slots == {"09:00": "past", "09:10": "past", "09:20": "", "09:30": "", "09:40": "booked", "09:50": ""}


def test_dates_must_be_today_to_30_days_ahead(clinic):
    _, doctor, _ = clinic
    assert client.get(f"/api/doctors/{doctor}/slots?date=2026-11-29").status_code == 400        # yesterday
    r = client.get(f"/api/doctors/{doctor}/slots?date=2027-01-04")                               # 35 days
    assert r.status_code == 400 and "30 days" in r.json()["detail"]


# ---------------------------------------------------------------- booking

def test_booking_a_free_slot(clinic):
    dept, doctor, _ = clinic
    me = patient()
    r = book(me, dept, doctor, "09:20")
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "accepted"                        # auto_accept is on by default
    assert a["slot_start"] == "09:20:00" and a["slot_end"] == "09:30:00" and a["room"] == 4
    assert a["source"] == "online" and a["can_cancel"] is True
    assert [x["id"] for x in client.get("/api/appointments/me", headers=me).json()] == [a["id"]]


def test_double_booking_is_blocked(clinic):
    dept, doctor, _ = clinic
    assert book(patient(), dept, doctor, "09:30").status_code == 201
    r = book(patient(), dept, doctor, "09:30")              # another patient, same slot
    assert r.status_code == 409 and "someone has just booked" in r.json()["detail"]


def test_one_booking_per_patient_per_doctor_per_day(clinic):
    dept, doctor, _ = clinic
    me = patient()
    assert book(me, dept, doctor, "09:00").status_code == 201
    r = book(me, dept, doctor, "09:10")
    assert r.status_code == 409 and "already have a booking" in r.json()["detail"]


def test_only_real_future_slots_can_be_booked(clinic, monkeypatch):
    dept, doctor, _ = clinic
    me = patient()
    assert book(me, dept, doctor, "09:05").status_code == 400            # not a slot boundary
    assert book(me, dept, doctor, "11:00").status_code == 400            # outside the session
    assert book(me, dept, doctor, "09:00", reason="x").status_code == 422   # reason too short
    monkeypatch.setattr(schedule_module, "now_local", at(f"{MONDAY} 09:15"))
    r = book(me, dept, doctor, "09:10")
    assert r.status_code == 400 and "already started" in r.json()["detail"]


def test_doctor_with_auto_accept_off_gets_requests(clinic):
    dept, doctor, _ = clinic
    with SessionLocal() as db:                               # the doctor's switch (its page comes in step 4)
        db.get(User, doctor).auto_accept = False
        db.commit()
    assert book(patient(), dept, doctor, "09:50").json()["status"] == "requested"


def test_only_patients_book_and_only_their_own_list(clinic):
    dept, doctor, doctor_headers = clinic
    assert book({}, dept, doctor).status_code == 401                     # not logged in
    assert book(doctor_headers, dept, doctor).status_code == 403         # doctors don't book
    assert client.get("/api/appointments/me", headers=doctor_headers).status_code == 403
    a, b = patient(), patient()
    book(a, dept, doctor, "09:00")
    assert client.get("/api/appointments/me", headers=b).json() == []   # b doesn't see a's booking


# ---------------------------------------------------------------- cancelling

def test_cancel_up_to_one_hour_before(clinic, monkeypatch):
    dept, doctor, _ = clinic
    me = patient()
    first = book(me, dept, doctor, "09:00").json()
    # 08:00 is exactly 1 hour before 09:00: still allowed
    r = client.post(f"/api/appointments/{first['id']}/cancel", headers=me)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert book(patient(), dept, doctor, "09:00").status_code == 201    # the slot is free again

    second = book(me, dept, doctor, "09:50").json()
    monkeypatch.setattr(schedule_module, "now_local", at(f"{MONDAY} 08:51"))   # 59 minutes before
    r = client.post(f"/api/appointments/{second['id']}/cancel", headers=me)
    assert r.status_code == 409 and "1 hour before" in r.json()["detail"]
    assert client.get("/api/appointments/me", headers=me).json()[0]["can_cancel"] is False


def test_cancel_rules(clinic):
    dept, doctor, _ = clinic
    me, other = patient(), patient()
    a = book(me, dept, doctor, "09:10").json()
    assert client.post(f"/api/appointments/{a['id']}/cancel", headers=other).status_code == 404   # not theirs
    assert client.post(f"/api/appointments/{a['id']}/cancel", headers=me).status_code == 200
    r = client.post(f"/api/appointments/{a['id']}/cancel", headers=me)                             # twice
    assert r.status_code == 409 and "cancelled" in r.json()["detail"]


# ---------------------------------------------------------------- the pages

def test_patient_pages_are_served_and_linked():
    for page, script in [("/book.html", "book.js"), ("/my-appointments.html", "my-appointments.js")]:
        html = client.get(page).text
        assert '<script src="core.js"></script>' in html and 'id="app-bar"' in html, page
        assert html.index('src="patient.js"') < html.index(f'src="{script}"'), page
        assert client.get(f"/{script}").status_code == 200
    assert 'href="/book.html">Book Appointment' in client.get("/site.js").text      # no longer "coming soon"
    assert 'patient: "/my-appointments.html"' in client.get("/core.js").text      # where patients land
