"""
Tests for Module 3: ambulance dispatch (routers/ambulance.py).
Run from the mediq/ folder with:   pytest
"""

import itertools

from fastapi.testclient import TestClient

from backend.app.main import app
from helpers import admin_headers, login_headers

client = TestClient(app)
ADMIN = admin_headers()
_n = itertools.count(10)   # unique ambulance codes per test (AMB-10, AMB-11...)


def staff(role, email):
    client.post("/api/auth/users", headers=ADMIN, json={
        "full_name": f"Amb {role}", "email": email, "password": "staff-password-1", "role": role})
    return login_headers(email, "staff-password-1")


STAFF = staff("doctor", "dispatch@amb.example")   # doctors (and admins) run dispatch
PATIENT_EMAIL = "patient@amb.example"
client.post("/api/auth/signup", json={"full_name": "P", "email": PATIENT_EMAIL, "password": "patient-password-1"})
PATIENT = login_headers(PATIENT_EMAIL, "patient-password-1")


def new_ambulance(**extra):
    body = {"code": f"AMB-{next(_n)}", "vehicle_number": "MH 12 XX 9999",
            "driver_name": "Test Driver", "driver_phone": "9000099999", **extra}
    r = client.post("/api/ambulances", headers=ADMIN, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def new_trip(headers=STAFF, **extra):
    body = {"patient_name": "Ravi", "contact_phone": "98765 43210", "pickup": "12 MG Road", **extra}
    return client.post("/api/ambulances/trips", headers=headers, json=body)


def ambulance(amb_id):
    return next(a for a in client.get("/api/ambulances", headers=STAFF).json() if a["id"] == amb_id)


def park_all_but(*keep_ids):
    """Put every other available ambulance into maintenance, so 'first free' is predictable."""
    for a in client.get("/api/ambulances", headers=ADMIN).json():
        if a["id"] not in keep_ids and a["status"] == "available":
            client.patch(f"/api/ambulances/{a['id']}", headers=ADMIN, json={"status": "maintenance"})


# ---------- the fleet ----------

def test_demo_fleet_and_public_counts():
    fleet = client.get("/api/ambulances", headers=STAFF).json()
    assert {"AMB-01", "AMB-02", "AMB-03", "AMB-04"} <= {a["code"] for a in fleet}
    counts = client.get("/api/ambulances/availability").json()        # public, no login
    assert set(counts) == {"available", "on_trip", "maintenance"}
    assert "driver" not in str(counts)                                   # numbers only


def test_who_can_do_what():
    assert client.get("/api/ambulances").status_code == 401
    assert client.get("/api/ambulances", headers=PATIENT).status_code == 403
    assert new_trip(headers=PATIENT).status_code == 403                  # no prank dispatches
    body = {"code": "AMB-X1", "vehicle_number": "x", "driver_name": "x", "driver_phone": "9000011111"}
    assert client.post("/api/ambulances", headers=STAFF, json=body).status_code == 403   # admin adds vehicles


def test_add_ambulance_rules():
    amb = new_ambulance(driver_phone="+91 90000 12345")
    assert amb["status"] == "available" and amb["driver_phone"] == "+919000012345"
    dup = client.post("/api/ambulances", headers=ADMIN, json={
        "code": amb["code"].lower(), "vehicle_number": "x", "driver_name": "x", "driver_phone": "9000011111"})
    assert dup.status_code == 409
    assert client.post("/api/ambulances", headers=ADMIN, json={
        "code": "AMB-BAD", "vehicle_number": "x", "driver_name": "x", "driver_phone": "123"}).status_code == 400


# ---------- a whole trip ----------

def test_request_assign_complete():
    amb = new_ambulance(location="Bay 1")
    trip = new_trip(pickup="5 Lake Road", destination="mediQ Lakeside Hospital").json()
    assert trip["status"] == "requested" and trip["ambulance_id"] is None
    assert trip["contact_phone"] == "+919876543210"

    assigned = client.post(f"/api/ambulances/trips/{trip['id']}/assign", headers=STAFF,
                           json={"ambulance_id": amb["id"]}).json()
    assert assigned["status"] == "assigned" and assigned["ambulance_code"] == amb["code"]
    a = ambulance(amb["id"])
    assert a["status"] == "on_trip" and a["current_trip"]["id"] == trip["id"]

    done = client.post(f"/api/ambulances/trips/{trip['id']}/complete", headers=STAFF).json()
    assert done["status"] == "completed" and done["finished_at"]
    a = ambulance(amb["id"])
    assert a["status"] == "available" and a["current_trip"] is None
    assert a["location"] == "mediQ Lakeside Hospital"                   # it's now where it dropped the patient


def test_assign_first_free_when_none_chosen():
    amb = new_ambulance()
    park_all_but(amb["id"])
    trip = new_trip().json()
    r = client.post(f"/api/ambulances/trips/{trip['id']}/assign", headers=STAFF, json={})
    assert r.status_code == 200 and r.json()["ambulance_id"] == amb["id"]

    # Now none is free
    another = new_trip().json()
    busy = client.post(f"/api/ambulances/trips/{another['id']}/assign", headers=STAFF, json={})
    assert busy.status_code == 409 and "No ambulance is available" in busy.json()["detail"]


def test_busy_or_maintenance_ambulance_cannot_be_sent():
    amb = new_ambulance()
    first = new_trip().json()
    client.post(f"/api/ambulances/trips/{first['id']}/assign", headers=STAFF, json={"ambulance_id": amb["id"]})
    second = new_trip().json()
    r = client.post(f"/api/ambulances/trips/{second['id']}/assign", headers=STAFF, json={"ambulance_id": amb["id"]})
    assert r.status_code == 409 and "on trip" in r.json()["detail"]

    spare = new_ambulance()
    client.patch(f"/api/ambulances/{spare['id']}", headers=STAFF, json={"status": "maintenance"})
    r = client.post(f"/api/ambulances/trips/{second['id']}/assign", headers=STAFF, json={"ambulance_id": spare["id"]})
    assert r.status_code == 409 and "maintenance" in r.json()["detail"]


def test_cancel_frees_the_ambulance():
    amb = new_ambulance(location="Bay 3")
    trip = new_trip().json()
    client.post(f"/api/ambulances/trips/{trip['id']}/assign", headers=STAFF, json={"ambulance_id": amb["id"]})
    r = client.post(f"/api/ambulances/trips/{trip['id']}/cancel", headers=STAFF)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    a = ambulance(amb["id"])
    assert a["status"] == "available" and a["location"] == "Bay 3"       # never left, so same place
    # Can't complete or cancel it again
    assert client.post(f"/api/ambulances/trips/{trip['id']}/complete", headers=STAFF).status_code == 409
    assert client.post(f"/api/ambulances/trips/{trip['id']}/cancel", headers=STAFF).status_code == 409


def test_status_and_location_updates():
    amb = new_ambulance()
    r = client.patch(f"/api/ambulances/{amb['id']}", headers=STAFF, json={"location": "Ring Road junction"})
    assert r.json()["location"] == "Ring Road junction"
    # on_trip only happens through "assign"
    assert client.patch(f"/api/ambulances/{amb['id']}", headers=STAFF, json={"status": "on_trip"}).status_code == 400
    # Can't send an ambulance to maintenance in the middle of a trip
    trip = new_trip().json()
    client.post(f"/api/ambulances/trips/{trip['id']}/assign", headers=STAFF, json={"ambulance_id": amb["id"]})
    assert client.patch(f"/api/ambulances/{amb['id']}", headers=STAFF, json={"status": "maintenance"}).status_code == 409


def test_trip_list_filters_and_validation():
    open_trip = new_trip().json()
    open_ids = [t["id"] for t in client.get("/api/ambulances/trips?status=requested,assigned", headers=STAFF).json()]
    assert open_trip["id"] in open_ids
    assert client.get("/api/ambulances/trips?status=flying", headers=STAFF).status_code == 422
    assert new_trip(contact_phone="123").status_code == 400
    assert new_trip(pickup="x").status_code == 422


def test_city_summary_shares_only_the_count():
    summary = client.get("/api/hospital/summary").json()
    assert isinstance(summary["facilities"]["available_ambulances"], int)
    text = str(summary)
    assert "Ramesh" not in text and "MH 12" not in text and "+91" not in text
