"""
Tests. Run from the mediq/ folder with:   pytest
A test is just a function that checks the code does what we expect.
"""

from fastapi.testclient import TestClient

from backend.app.main import app
from helpers import admin_headers, queue_token
from backend.app.queueing import estimate_wait_for_position, mmc_metrics

# Logged in as admin: these endpoints need a login since step 4 (accounts)
client = TestClient(app, headers=admin_headers())


# ---------- the maths ----------

def test_single_doctor_matches_mm1_formula():
    # For c = 1 the textbook M/M/1 answer is Wq = rho / (mu - lambda).
    # lambda = 4/hr, mu = 6/hr -> rho = 2/3, Wq = (2/3)/2 h = 20 minutes.
    m = mmc_metrics(arrival_rate=4, service_rate=6, servers=1)
    assert m["utilization"] == round(4 / 6, 4)
    assert m["avg_wait_minutes"] == 20.0


def test_more_doctors_means_shorter_wait():
    one = mmc_metrics(5, 6, 1)["avg_wait_minutes"]
    two = mmc_metrics(5, 6, 2)["avg_wait_minutes"]
    assert two < one


def test_overloaded_department_is_unstable():
    assert mmc_metrics(20, 6, 2)["stable"] is False


def test_position_estimate():
    # 6 people ahead, 3 doctors, 10 min each -> ~20 min
    assert estimate_wait_for_position(6, 3, 10) == 20.0


# ---------- the API ----------

def test_full_patient_journey():
    dept = client.post("/api/departments", json={
        "code": "ENT", "name": "ENT", "doctors": 1,
        "avg_consult_minutes": 10, "expected_patients_per_hour": 3}).json()

    a = queue_token("A", dept["id"])
    b = queue_token("B", dept["id"])
    assert a["number"] == "ENT-001" and b["number"] == "ENT-002"
    assert b["people_ahead"] == 1 and b["estimated_wait_minutes"] == 10.0

    # Doctor calls next: A goes in first (First-Come-First-Served)
    called = client.post(f"/api/departments/{dept['id']}/call-next?room=1").json()
    assert called["number"] == "ENT-001"
    assert client.get(f"/api/tokens/{b['id']}").json()["people_ahead"] == 0

    # Calling next again finishes A and brings in B
    client.post(f"/api/departments/{dept['id']}/call-next?room=1")
    assert client.get(f"/api/tokens/{a['id']}").json()["status"] == "done"
    stats = client.get(f"/api/departments/{dept['id']}/stats").json()
    assert stats["now_serving"] == ["ENT-002"] and stats["done_today"] == 1


def test_validation_errors():
    # The reception desk is gone: nobody can hand out tokens with POST /api/tokens any more
    assert client.post("/api/tokens", json={"patient_name": "X", "department_id": 1}).status_code in (404, 405)
    assert client.post("/api/departments", json={"code": "Z", "name": "Z", "doctors": 0}).status_code == 422


def test_city_summary_has_no_patient_names():
    body = client.get("/api/hospital/summary").text
    assert "hospital_id" in body and "patient_name" not in body
