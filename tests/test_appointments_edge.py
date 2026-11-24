"""
Self-booking step 9: the edge cases the other test files don't reach.
Clock: Monday 30 Nov 2026. Run from the mediq/ folder with:   pytest
"""

import itertools
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import schedule as schedule_module
from backend.app.services import appointments as svc
from helpers import admin_headers, login_headers

client = TestClient(app)
ADMIN = admin_headers()
PASSWORD = "edge-password-1"
_n = itertools.count(1)


@pytest.fixture
def set_time(monkeypatch):
    def setter(hhmm):
        h, m = map(int, hhmm.split(":"))
        moment = datetime(2026, 11, 30, h, m, tzinfo=ZoneInfo("Asia/Kolkata"))
        monkeypatch.setattr(schedule_module, "now_local", lambda: moment)
    setter("08:00")
    return setter


def patient():
    email = f"edge{next(_n)}@edge.example"
    client.post("/api/auth/signup", json={"full_name": f"Edge {next(_n)}", "email": email, "password": PASSWORD})
    return login_headers(email, PASSWORD)


@pytest.fixture
def clinic(set_time):
    n = next(_n)
    dept = client.post("/api/departments", headers=ADMIN, json={"code": f"E{n}", "name": f"Edge {n}", "doctors": 1}).json()
    email = f"edgedoc{n}@edge.example"
    doc = client.post("/api/auth/users", headers=ADMIN, json={"full_name": f"Dr. Edge {n}", "email": email,
                                                              "password": PASSWORD, "role": "doctor"}).json()
    client.post("/api/schedule", headers=ADMIN, json={"doctor_id": doc["id"], "department_id": dept["id"],
                "weekday": 0, "start_time": "09:00", "end_time": "10:00", "room": 1})
    return dept, doc["id"], login_headers(email, PASSWORD)


def book(headers, dept, doc, start):
    return client.post("/api/appointments", headers=headers, json={"doctor_id": doc, "department_id": dept["id"],
                       "date": "2026-11-30", "slot_start": start, "reason": "Check-up"})


def test_two_people_pressing_book_at_the_same_instant(clinic, monkeypatch):
    """
    Pretend the second patient's Python check ran BEFORE the first booking was
    saved (it saw every slot free). Then only the database's unique index stands
    between them, and it must still refuse, with the same friendly 409.
    """
    dept, doc, _ = clinic
    assert book(patient(), dept, doc, "09:30").status_code == 201
    real_slots_for = svc.slots_for

    def stale_view(db, doctor_id, day, department_id=None):
        slots = real_slots_for(db, doctor_id, day, department_id)
        for s in slots:
            s.free, s.why_not = True, ""                 # "everything looked free when I checked"
        return slots

    monkeypatch.setattr(svc, "slots_for", stale_view)
    r = book(patient(), dept, doc, "09:30")
    assert r.status_code == 409 and "someone has just booked" in r.json()["detail"]
    days = client.get("/api/doctor/appointments", headers=ADMIN, params={"doctor_id": doc}).json()
    assert len(days[0]["appointments"]) == 1             # only one booking was saved


def test_no_cancelling_or_rejecting_once_checked_in(clinic, set_time):
    dept, doc, doc_headers = clinic
    me = patient()
    a = book(me, dept, doc, "09:00").json()
    set_time("08:30")
    assert client.post(f"/api/appointments/{a['id']}/checkin", headers=me).status_code == 200
    r = client.post(f"/api/appointments/{a['id']}/cancel", headers=me)
    assert r.status_code == 409 and "checked in" in r.json()["detail"]
    r = client.post(f"/api/appointments/{a['id']}/reject", headers=doc_headers, json={"reason": "Changed my mind"})
    assert r.status_code == 409 and "checked in" in r.json()["detail"]
