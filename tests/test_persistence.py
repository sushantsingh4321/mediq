"""
Everything is now saved in the database, not Python memory.

These tests do something through the API, then read the database file with a
BRAND-NEW connection (like a server that has just restarted) and check the data
is really there. Run from the mediq/ folder with:   pytest
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.app.database import DATABASE_URL
from backend.app.main import app
from helpers import admin_headers, queue_token

client = TestClient(app, headers=admin_headers())


def read_fresh(sql: str, **params):
    """Run SQL on a new connection to the same database file, as if after a restart."""
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params).all()
    finally:
        engine.dispose()


def test_queue_survives_a_restart():
    dept = client.post("/api/departments", json={"code": "PST", "name": "Persist", "doctors": 1}).json()
    token = queue_token("Saved Patient", dept["id"])
    client.post(f"/api/departments/{dept['id']}/call-next?room=1")   # admin may always call next

    rows = read_fresh("SELECT number, patient_name, status, room FROM tokens WHERE id = :id", id=token["id"])
    assert rows == [("PST-001", "Saved Patient", "in_consultation", 1)]
    assert read_fresh("SELECT code FROM departments WHERE id = :id", id=dept["id"]) == [("PST",)]


def test_token_numbers_continue_after_a_restart():
    dept = client.post("/api/departments", json={"code": "NUM", "name": "Numbers", "doctors": 1}).json()
    for _ in range(2):
        queue_token("x", dept["id"])
    third = queue_token("x", dept["id"])
    assert third["number"] == "NUM-003"   # counted from the database, not a memory counter


def test_beds_enquiries_and_callbacks_are_saved():
    ward = client.post("/api/wards", json={"name": "Persist Ward", "total_beds": 2}).json()
    client.post(f"/api/wards/{ward['id']}/admit", json={"patient_name": "Bed Patient"})
    client.post("/api/enquiries", json={"name": "Saved Enquiry", "country_code": "+91", "mobile": "9844444444",
                                        "speciality": "Neurology", "consent": True})
    client.post("/api/callback", json={"name": "Saved Callback", "mobile": "9844444445", "consent": True})

    assert read_fresh("SELECT number, patient_name FROM beds WHERE ward_id = :w ORDER BY number", w=ward["id"]) \
        == [(1, "Bed Patient"), (2, None)]
    assert read_fresh("SELECT speciality FROM enquiries WHERE name = 'Saved Enquiry'") == [("Neurology",)]
    assert read_fresh("SELECT mobile, status FROM callback_requests WHERE name = 'Saved Callback'") \
        == [("+919844444445", "calling")]
