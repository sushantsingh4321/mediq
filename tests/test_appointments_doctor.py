"""
Self-booking step 4: the doctor side. Tokens for bookings, the doctor's list,
accept / reject, and the auto_accept switch.
"Now" is fixed to Monday 30 Nov 2026, 08:00. Run from the mediq/ folder with:   pytest
"""

import itertools
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.app.database import SessionLocal
from backend.app.db_models import TokenRow
from backend.app.main import app
from backend.app.models import TokenStatus
from backend.app.routers import schedule as schedule_module
from backend.app.store import store
from helpers import admin_headers, login_headers

client = TestClient(app)
ADMIN = admin_headers()
PASSWORD = "doctor-side-pass-1"
MONDAY, TUESDAY = "2026-11-30", "2026-12-01"
_n = itertools.count(1)


@pytest.fixture(autouse=True)
def monday_morning(monkeypatch):
    moment = datetime(2026, 11, 30, 8, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    monkeypatch.setattr(schedule_module, "now_local", lambda: moment)


def patient():
    email = f"pt{next(_n)}@docside.example"
    client.post("/api/auth/signup", json={"full_name": f"Patient {email[:4]}", "email": email, "password": PASSWORD})
    return login_headers(email, PASSWORD)


def doctor(dept_id, name="Dr. Side", room=1):
    """A doctor working Monday and Tuesday 09:00-10:00 in this room. Returns (id, headers).
    (Two doctors can't share a room at the same time: the schedule refuses that.)"""
    email = f"dr{next(_n)}@docside.example"
    d = client.post("/api/auth/users", headers=ADMIN, json={"full_name": name, "email": email,
                                                            "password": PASSWORD, "role": "doctor"}).json()
    for weekday in (0, 1):
        client.post("/api/schedule", headers=ADMIN, json={"doctor_id": d["id"], "department_id": dept_id,
                    "weekday": weekday, "start_time": "09:00", "end_time": "10:00", "room": room})
    return d["id"], login_headers(email, PASSWORD)


@pytest.fixture
def dept():
    n = next(_n)
    return client.post("/api/departments", headers=ADMIN, json={"code": f"D{n}", "name": f"Doc side {n}",
                                                                 "doctors": 3}).json()


def book(headers, dept_id, doctor_id, start="09:00", day=MONDAY):
    r = client.post("/api/appointments", headers=headers, json={
        "doctor_id": doctor_id, "department_id": dept_id, "date": day, "slot_start": start, "reason": "Check-up"})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- tokens

def test_booking_auto_creates_a_token_shown_to_the_patient(dept):
    doc_id, _ = doctor(dept["id"])
    me = patient()
    a = book(me, dept["id"], doc_id, "09:20")
    assert a["status"] == "accepted"
    assert a["token_number"] == f"{dept['code']}-001" and a["token_status"] == "booked"
    assert client.get("/api/appointments/me", headers=me).json()[0]["token_number"] == a["token_number"]
    # "booked" = not here yet: NOT in the live queue, so "Call next" can't call them
    assert client.get(f"/api/departments/{dept['id']}/queue", headers=ADMIN).json() == []
    assert client.get(f"/api/departments/{dept['id']}/stats").json()["waiting"] == 0


def test_tokens_are_ordered_by_slot_time_then_priority(dept):
    first_doc, _ = doctor(dept["id"])
    second_doc, _ = doctor(dept["id"], room=2)
    late = book(patient(), dept["id"], first_doc, "09:40")       # booked first, but later slot
    early = book(patient(), dept["id"], first_doc, "09:10")
    same_time = book(patient(), dept["id"], second_doc, "09:10")  # same slot time, other doctor
    with SessionLocal() as db:                                    # give one of the 09:10s priority
        db.get(TokenRow, same_time["token_id"]).priority = 1
        db.commit()
    order = [t.number for t in store.tokens_in(dept["id"], TokenStatus.BOOKED)]
    assert order == [same_time["token_number"], early["token_number"], late["token_number"]]


# ---------------------------------------------------------------- the doctor's list

def test_doctor_sees_only_their_own_bookings_grouped_by_date(dept):
    mine, my_headers = doctor(dept["id"])
    other, _ = doctor(dept["id"], room=2)
    book(patient(), dept["id"], mine, "09:30")
    book(patient(), dept["id"], mine, "09:00", day=TUESDAY)
    book(patient(), dept["id"], mine, "09:10")
    book(patient(), dept["id"], other, "09:00")
    days = client.get("/api/doctor/appointments", headers=my_headers).json()
    assert [d["date"] for d in days] == [MONDAY, TUESDAY]
    assert [a["slot_start"][:5] for a in days[0]["appointments"]] == ["09:10", "09:30"]
    assert all(a["doctor_id"] == mine for d in days for a in d["appointments"])
    assert client.get("/api/doctor/appointments", headers=patient()).status_code == 403


# ---------------------------------------------------------------- reject

def test_only_the_right_doctor_can_reject(dept):
    mine, my_headers = doctor(dept["id"])
    _, other_headers = doctor(dept["id"])
    me = patient()
    a = book(me, dept["id"], mine, "09:50")
    url = f"/api/appointments/{a['id']}/reject"
    body = {"reason": "In surgery that morning. Please book Tuesday."}
    assert client.post(url, json=body, headers=other_headers).status_code == 403      # another doctor
    assert client.post(url, json=body, headers=me).status_code == 403                 # the patient
    assert client.post(url, json={"reason": ""}, headers=my_headers).status_code == 422
    r = client.post(url, json=body, headers=my_headers)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["token_status"] == "cancelled"                                    # the token is cancelled
    seen = client.get("/api/appointments/me", headers=me).json()[0]
    assert seen["status"] == "rejected" and seen["reject_reason"] == body["reason"]
    assert client.post(url, json=body, headers=my_headers).status_code == 409         # already rejected
    assert book(patient(), dept["id"], mine, "09:50")["status"] == "accepted"         # the slot is free again


def test_patient_cancelling_cancels_the_token(dept):
    doc_id, _ = doctor(dept["id"])
    me = patient()
    a = book(me, dept["id"], doc_id, "09:40")
    r = client.post(f"/api/appointments/{a['id']}/cancel", headers=me).json()
    assert r["status"] == "cancelled" and r["token_status"] == "cancelled"


# ---------------------------------------------------------------- auto_accept off: manual accept

def test_manual_accept_when_auto_accept_is_off(dept):
    doc_id, doc_headers = doctor(dept["id"])
    assert client.get("/api/doctor/settings", headers=doc_headers).json() == {"auto_accept": True}
    r = client.patch("/api/doctor/settings", headers=doc_headers, json={"auto_accept": False})
    assert r.json() == {"auto_accept": False}

    me = patient()
    a = book(me, dept["id"], doc_id, "09:30")
    assert a["status"] == "requested" and a["token_number"] is None      # no token until accepted

    _, other_headers = doctor(dept["id"])
    assert client.post(f"/api/appointments/{a['id']}/accept", headers=other_headers).status_code == 403
    r = client.post(f"/api/appointments/{a['id']}/accept", headers=doc_headers)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert r.json()["token_number"] == f"{dept['code']}-001" and r.json()["token_status"] == "booked"
    assert client.post(f"/api/appointments/{a['id']}/accept", headers=doc_headers).status_code == 409


def test_a_request_can_be_rejected_too(dept):
    doc_id, doc_headers = doctor(dept["id"])
    client.patch("/api/doctor/settings", headers=doc_headers, json={"auto_accept": False})
    a = book(patient(), dept["id"], doc_id, "09:00")
    r = client.post(f"/api/appointments/{a['id']}/reject", headers=doc_headers, json={"reason": "Fully booked"})
    assert r.json()["status"] == "rejected" and r.json()["token_number"] is None


def test_settings_are_for_doctors_only():
    assert client.patch("/api/doctor/settings", headers=patient(), json={"auto_accept": False}).status_code == 403
    r = client.patch("/api/doctor/settings", headers=ADMIN, json={"auto_accept": False})
    assert r.status_code == 403 and "Only doctors" in r.json()["detail"]


def test_doctor_page_is_served_and_linked():
    html = client.get("/doctor-appointments.html").text
    assert '<script src="core.js"></script>' in html and 'src="doctor-appointments.js"' in html
    assert 'href="/doctor-appointments.html"' in client.get("/index.html").text      # from the Doctor's desk
    js = client.get("/doctor-appointments.js").text
    assert "/doctor/settings" in js and "/reject" in js and "/accept" in js
