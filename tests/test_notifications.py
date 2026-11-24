"""
Self-booking step 6: notifications. An in-app message (banner) for each thing
that happens to a booking, and the same text handed to the SMS hook (a stub).
Clock: Monday 30 Nov 2026, set per test. Run from the mediq/ folder with:   pytest
"""

import itertools
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.routers import schedule as schedule_module
from backend.app.services import sms
from helpers import admin_headers, login_headers

client = TestClient(app)
ADMIN = admin_headers()
PASSWORD = "notify-password-1"
_n = itertools.count(1)


@pytest.fixture
def set_time(monkeypatch):
    def setter(hhmm):
        h, m = map(int, hhmm.split(":"))
        moment = datetime(2026, 11, 30, h, m, tzinfo=ZoneInfo("Asia/Kolkata"))
        monkeypatch.setattr(schedule_module, "now_local", lambda: moment)
    setter("08:00")
    return setter


def patient(phone=None):
    n = next(_n)
    email = f"note{n}@notify.example"
    body = {"full_name": f"Note Patient {n}", "email": email, "password": PASSWORD}
    if phone:
        body["phone"] = phone
    client.post("/api/auth/signup", json=body)
    return login_headers(email, PASSWORD)


@pytest.fixture
def clinic(set_time):
    n = next(_n)
    dept = client.post("/api/departments", headers=ADMIN, json={"code": f"N{n}", "name": f"Notify {n}", "doctors": 1}).json()
    email = f"notedoc{n}@notify.example"
    doc = client.post("/api/auth/users", headers=ADMIN, json={"full_name": f"Dr. Note {n}", "email": email,
                                                              "password": PASSWORD, "role": "doctor"}).json()
    client.post("/api/schedule", headers=ADMIN, json={"doctor_id": doc["id"], "department_id": dept["id"],
                "weekday": 0, "start_time": "09:00", "end_time": "10:00", "room": 1})
    return dept, doc["id"], login_headers(email, PASSWORD)


def book(headers, dept, doc, start="09:00"):
    r = client.post("/api/appointments", headers=headers, json={"doctor_id": doc, "department_id": dept["id"],
                    "date": "2026-11-30", "slot_start": start, "reason": "Check-up"})
    assert r.status_code == 201, r.text
    return r.json()


def messages(headers, unread_only=True):
    return client.get(f"/api/notifications/me?unread_only={str(unread_only).lower()}", headers=headers).json()


# ---------------------------------------------------------------- one message per event

def test_booking_confirmation_and_the_sms_hook(clinic):
    dept, doc, _ = clinic
    me = patient(phone="9876543210")
    a = book(me, dept, doc, "09:20")
    [note] = messages(me)
    assert note["event"] == "booked" and note["appointment_id"] == a["id"]
    assert a["token_number"] in note["message"] and "09:20" in note["message"]
    # The SMS hook got the same text, but sent nothing (it's a stub)
    assert sms.OUTBOX[-1].text == note["message"] and sms.OUTBOX[-1].to == "+919876543210"


def test_request_then_accept(clinic):
    dept, doc, doc_headers = clinic
    client.patch("/api/doctor/settings", headers=doc_headers, json={"auto_accept": False})
    me = patient()
    a = book(me, dept, doc)
    assert [n["event"] for n in messages(me)] == ["requested"]
    client.post(f"/api/appointments/{a['id']}/accept", headers=doc_headers)
    newest = messages(me)[0]
    assert newest["event"] == "accepted" and "accepted your booking" in newest["message"]


def test_rejection_message_carries_the_reason(clinic):
    dept, doc, doc_headers = clinic
    me = patient()
    a = book(me, dept, doc)
    client.post(f"/api/appointments/{a['id']}/reject", headers=doc_headers, json={"reason": "On leave that day"})
    newest = messages(me)[0]
    assert newest["event"] == "rejected" and "Reason: On leave that day" in newest["message"]


def test_your_turn_when_called(clinic, set_time):
    dept, doc, doc_headers = clinic
    me = patient()
    a = book(me, dept, doc, "09:00")
    set_time("08:30")
    client.post(f"/api/appointments/{a['id']}/checkin", headers=me)
    set_time("09:01")
    client.post(f"/api/departments/{dept['id']}/call-next?room=1", headers=doc_headers)
    newest = messages(me)[0]
    assert newest["event"] == "called" and "It's your turn: please go to Room 1" in newest["message"]


def test_missed_booking_message(clinic, set_time):
    dept, doc, _ = clinic
    me = patient()
    book(me, dept, doc, "09:00")
    set_time("09:16")
    client.get("/api/appointments/me", headers=me)          # looking runs the no-show check
    assert messages(me)[0]["event"] == "no_show"


def test_no_message_for_what_you_did_yourself(clinic, set_time):
    dept, doc, _ = clinic
    me = patient()
    a = book(me, dept, doc, "09:30")
    client.post(f"/api/appointments/{a['id']}/cancel", headers=me)
    assert [n["event"] for n in messages(me)] == ["booked"]  # nothing new for the cancel


# ---------------------------------------------------------------- reading them

def test_got_it_hides_a_message_and_only_your_own(clinic):
    dept, doc, _ = clinic
    me, other = patient(), patient()
    book(me, dept, doc, "09:40")
    [note] = messages(me)
    assert client.post(f"/api/notifications/{note['id']}/read", headers=other).status_code == 404
    assert client.post(f"/api/notifications/{note['id']}/read", headers=me).json()["read_at"] is not None
    assert messages(me) == []                                   # unread: none
    assert len(messages(me, unread_only=False)) == 1            # still in the history
    assert client.get("/api/notifications/me").status_code == 401


def test_read_all(clinic, set_time):
    dept, doc, doc_headers = clinic
    me = patient()
    a = book(me, dept, doc, "09:50")
    client.post(f"/api/appointments/{a['id']}/reject", headers=doc_headers, json={"reason": "Fully booked"})
    assert len(messages(me)) == 2
    assert client.post("/api/notifications/read-all", headers=me).json() == {"marked_read": 2}
    assert messages(me) == []


def test_patient_pages_show_the_banners():
    js = client.get("/patient.js").text
    assert "/notifications/me" in js and "Got it" in js and "/notifications/read-all" in js
