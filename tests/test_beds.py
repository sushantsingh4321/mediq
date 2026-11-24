"""
Tests for Module 1: bed availability (backend/app/routers/beds.py).
Run from the mediq/ folder with:   pytest
"""

from fastapi.testclient import TestClient

from backend.app.main import app
from helpers import admin_headers

# Logged in as admin: these endpoints need a login since step 4 (accounts)
client = TestClient(app, headers=admin_headers())


def make_ward(name, beds):
    """Helper: create a fresh ward for one test and return it."""
    res = client.post("/api/wards", json={"name": name, "total_beds": beds})
    assert res.status_code == 201
    return res.json()


def ward_view(ward_id):
    """Helper: find one ward in GET /api/wards."""
    return next(w for w in client.get("/api/wards").json() if w["id"] == ward_id)


def test_admit_fills_lowest_free_bed_then_ward_is_full():
    ward = make_ward("Test Ward A", 2)

    a = client.post(f"/api/wards/{ward['id']}/admit", json={"patient_name": "A"}).json()
    b = client.post(f"/api/wards/{ward['id']}/admit", json={"patient_name": "B"}).json()
    assert a["bed_number"] == 1 and b["bed_number"] == 2

    # Both beds taken: the next admit is refused with 409 Conflict
    full = client.post(f"/api/wards/{ward['id']}/admit", json={"patient_name": "C"})
    assert full.status_code == 409

    view = ward_view(ward["id"])
    assert (view["total"], view["occupied"], view["free"]) == (2, 2, 0)


def test_discharge_frees_the_bed_for_the_next_patient():
    ward = make_ward("Test Ward B", 2)
    client.post(f"/api/wards/{ward['id']}/admit", json={"patient_name": "A"})
    client.post(f"/api/wards/{ward['id']}/admit", json={"patient_name": "B"})

    res = client.post(f"/api/wards/{ward['id']}/discharge?bed=1")
    assert res.status_code == 200 and res.json()["discharged"] == "A"

    # The freed bed 1 is reused first
    c = client.post(f"/api/wards/{ward['id']}/admit", json={"patient_name": "C"}).json()
    assert c["bed_number"] == 1


def test_admit_to_a_specific_bed():
    ward = make_ward("Test Ward C", 3)
    r = client.post(f"/api/wards/{ward['id']}/admit", json={"patient_name": "A", "bed_number": 3})
    assert r.json()["bed_number"] == 3
    # Same bed again -> 409, a bed that doesn't exist -> 404
    assert client.post(f"/api/wards/{ward['id']}/admit",
                       json={"patient_name": "B", "bed_number": 3}).status_code == 409
    assert client.post(f"/api/wards/{ward['id']}/admit",
                       json={"patient_name": "B", "bed_number": 9}).status_code == 404


def test_bed_errors():
    ward = make_ward("Test Ward D", 1)
    assert client.post(f"/api/wards/{ward['id']}/discharge?bed=1").status_code == 404  # already free
    assert client.post("/api/wards/999/admit", json={"patient_name": "X"}).status_code == 404
    assert client.post("/api/wards", json={"name": "Bad", "total_beds": 0}).status_code == 422
    assert client.post("/api/wards", json={"name": "test ward d", "total_beds": 2}).status_code == 400


def test_availability_and_city_summary_have_counts_but_no_names():
    ward = make_ward("Test Ward E", 4)
    before = client.get("/api/hospital/summary").json()["facilities"]["free_beds"]
    client.post(f"/api/wards/{ward['id']}/admit", json={"patient_name": "Secret Name"})

    summary = client.get("/api/hospital/summary")
    assert summary.json()["facilities"]["free_beds"] == before - 1
    assert "Secret Name" not in summary.text

    avail = client.get("/api/wards/availability")
    mine = next(w for w in avail.json() if w["ward"] == "Test Ward E")
    assert mine == {"ward": "Test Ward E", "total": 4, "occupied": 1, "free": 3}
    assert "Secret Name" not in avail.text
