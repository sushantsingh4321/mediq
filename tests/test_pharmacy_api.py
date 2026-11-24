"""
Pharmacy step 3: the API (routers/pharmacy.py) and the pharmacist role.
The rules themselves are tested in test_pharmacy_rules.py; here we check the
URLs work end to end, return useful JSON and let the right people in.
Run from the mediq/ folder with:   pytest
"""

import itertools
from datetime import timedelta

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.pharmacy import today_local
from helpers import admin_headers, login_headers

client = TestClient(app)
PASSWORD = "staff-password-1"
_n = itertools.count(1)


def account(role):
    email = f"api-{role}-{next(_n)}@example.com"
    r = client.post("/api/auth/users", headers=admin_headers(), json={
        "full_name": f"Test {role.title()}", "email": email, "password": PASSWORD, "role": role})
    assert r.status_code == 201, r.text
    return login_headers(email, PASSWORD)


PHARMACIST = account("pharmacist")
DOCTOR = account("doctor")
PATIENT = account("patient")


def add_medicine(**extra):
    body = {"brand_name": f"Api Med {next(_n)}", "generic_name": "Apicillin", "strength": "500 mg",
            "dosage_form": "capsule", "category": "antibiotic", "manufacturer": "Test Pharma",
            "gst_percent": 12, "reorder_level": 20, **extra}
    r = client.post("/api/pharmacy/medicines", json=body, headers=PHARMACIST)
    assert r.status_code == 201, r.text
    return r.json()


def receive(medicine_id, batch_no, days_to_expiry=365, quantity=100, **extra):
    today = today_local()
    body = {"medicine_id": medicine_id, "batch_no": batch_no, "mfg_date": str(today - timedelta(days=60)),
            "expiry_date": str(today + timedelta(days=days_to_expiry)), "quantity": quantity,
            "purchase_price": 1.00, "mrp": 2.50, "selling_price": 2.00, **extra}
    return client.post("/api/pharmacy/stock/receive", json=body, headers=PHARMACIST)


# ---------------------------------------------------------------- roles

def test_the_pharmacist_role_exists_and_lands_in_the_right_places():
    me = client.get("/api/auth/me", headers=PHARMACIST).json()
    assert me["role"] == "pharmacist"
    # Pharmacy work: pharmacist yes; patient no; not logged in -> 401
    assert client.get("/api/pharmacy/suppliers", headers=PHARMACIST).status_code == 200
    assert client.get("/api/pharmacy/suppliers", headers=PATIENT).status_code == 403
    assert client.get("/api/pharmacy/suppliers").status_code == 401
    # Doctors can read prescriptions and alerts, but not run the counter
    assert client.get("/api/pharmacy/alerts", headers=DOCTOR).status_code == 200
    assert client.post("/api/pharmacy/dispense", json={"items": [{"medicine_id": 1, "quantity": 1}]},
                       headers=DOCTOR).status_code == 403
    # Only doctors write prescriptions
    assert client.post("/api/pharmacy/prescriptions", headers=PHARMACIST, json={
        "patient_name": "X", "items": [{"medicine_id": 1, "dose": "1-0-1", "duration_days": 1,
                                        "quantity": 2}]}).status_code == 403


def test_anyone_can_search_the_catalogue_by_brand_or_generic_name():
    med = add_medicine(brand_name=f"Searchol {next(_n)}", generic_name="Findamycin")
    receive(med["id"], "S1")
    for q in ["searchol", "FINDAMYCIN"]:                    # brand or generic, any case
        found = client.get(f"/api/pharmacy/medicines?q={q}").json()      # no login
        hit = next(m for m in found if m["id"] == med["id"])
        assert hit["stock"] == 100 and hit["selling_price"] == 2.0       # money comes as a number
        assert "purchase_price" not in hit                               # cost price stays private


# ---------------------------------------------------------------- catalogue

def test_medicine_validation_and_soft_delete():
    med = add_medicine(schedule="H", prescription_required=False)
    assert med["prescription_required"] is True             # Schedule H always needs one
    bad = client.post("/api/pharmacy/medicines", headers=PHARMACIST, json={
        **{k: med[k] for k in ["generic_name", "strength", "dosage_form", "category", "manufacturer"]},
        "brand_name": "Odd GST", "gst_percent": 7})
    assert bad.status_code == 422 and "slabs" in bad.text
    dup = client.post("/api/pharmacy/medicines", headers=PHARMACIST, json={
        **{k: med[k] for k in ["brand_name", "generic_name", "strength", "dosage_form", "category",
                               "manufacturer"]}})
    assert dup.status_code == 400 and "already in the catalogue" in dup.json()["detail"]

    assert client.delete(f"/api/pharmacy/medicines/{med['id']}", headers=PHARMACIST).status_code == 204
    names = [m["id"] for m in client.get(f"/api/pharmacy/medicines?q={med['brand_name']}").json()]
    assert med["id"] not in names                            # hidden from search...
    detail = client.get(f"/api/pharmacy/medicines/{med['id']}", headers=PHARMACIST).json()
    assert detail["is_active"] is False                      # ...but still on record


def test_suppliers_crud_and_gstin_check():
    r = client.post("/api/pharmacy/suppliers", headers=PHARMACIST,
                    json={"name": f"Supplier {next(_n)}", "gstin": "27abcde1234f1z5", "phone": "9876543210"})
    assert r.status_code == 201 and r.json()["gstin"] == "27ABCDE1234F1Z5"   # saved in capitals
    sid = r.json()["id"]
    assert client.post("/api/pharmacy/suppliers", headers=PHARMACIST,
                       json={"name": "Bad GSTIN", "gstin": "12345"}).status_code == 422
    r = client.put(f"/api/pharmacy/suppliers/{sid}", headers=PHARMACIST, json={"name": "Renamed Supplier"})
    assert r.json()["name"] == "Renamed Supplier"
    # A supplier with batches is kept for the records
    med = add_medicine()
    assert receive(med["id"], "SUP1", supplier_id=sid).status_code == 201
    r = client.delete(f"/api/pharmacy/suppliers/{sid}", headers=PHARMACIST)
    assert r.status_code == 400 and "kept" in r.json()["detail"]


# ---------------------------------------------------------------- prescription -> dispense -> bill

def test_doctor_prescribes_and_pharmacist_dispenses_with_fefo_and_gst():
    amox = add_medicine(schedule="H", gst_percent=12)
    receive(amox["id"], "LATE", days_to_expiry=400, quantity=50)
    receive(amox["id"], "SOON", days_to_expiry=100, quantity=6)

    # Without a prescription: refused with a clear message (400, not a crash)
    r = client.post("/api/pharmacy/dispense", headers=PHARMACIST,
                    json={"items": [{"medicine_id": amox["id"], "quantity": 10}]})
    assert r.status_code == 400 and "needs a doctor's prescription" in r.json()["detail"]

    rx = client.post("/api/pharmacy/prescriptions", headers=DOCTOR, json={
        "patient_name": "Asha Patel", "notes": "Throat infection",
        "items": [{"medicine_id": amox["id"], "dose": "1-0-1", "frequency": "twice a day",
                   "duration_days": 5, "quantity": 10, "instructions": "after food"}]}).json()
    assert rx["status"] == "open" and rx["doctor_name"] == "Test Doctor"
    assert rx["items"][0]["remaining"] == 10

    bill = client.post("/api/pharmacy/dispense", headers=PHARMACIST, json={"prescription_id": rx["id"]})
    assert bill.status_code == 201, bill.text
    bill = bill.json()
    assert [(line["batch_no"], line["quantity"]) for line in bill["lines"]] == [("SOON", 6), ("LATE", 4)]
    assert bill["subtotal"] == 20.0 and bill["gst_amount"] == 2.4 and bill["total"] == 22.4
    assert bill["patient_name"] == "Asha Patel" and bill["bill_number"].startswith("PH-")

    after = client.get(f"/api/pharmacy/prescriptions/{rx['id']}", headers=PHARMACIST).json()
    assert after["status"] == "dispensed" and after["items"][0]["remaining"] == 0
    open_ids = [p["id"] for p in client.get("/api/pharmacy/prescriptions?open_only=true",
                                            headers=PHARMACIST).json()]
    assert rx["id"] not in open_ids
    # The bill can be fetched again (for printing)
    assert client.get(f"/api/pharmacy/dispensations/{bill['id']}", headers=PHARMACIST).json()["total"] == 22.4

    # And the diary has the "out" lines
    moves = client.get(f"/api/pharmacy/stock/movements?medicine_id={amox['id']}", headers=PHARMACIST).json()
    assert sorted(m["quantity"] for m in moves if m["type"] == "out") == [-6, -4]


def test_receive_refuses_expired_stock_with_a_clear_message():
    med = add_medicine()
    r = receive(med["id"], "EXP", days_to_expiry=0)
    assert r.status_code == 400 and "return it to the supplier" in r.json()["detail"]


# ---------------------------------------------------------------- purchase orders

def test_purchase_order_draft_ordered_received():
    sid = client.post("/api/pharmacy/suppliers", headers=PHARMACIST,
                      json={"name": f"PO Supplier {next(_n)}"}).json()["id"]
    med = add_medicine()
    po = client.post("/api/pharmacy/purchase-orders", headers=PHARMACIST, json={
        "supplier_id": sid, "items": [{"medicine_id": med["id"], "quantity": 200, "unit_price": 1.1}]}).json()
    assert po["status"] == "draft" and po["estimated_total"] == 220.0

    today = today_local()
    line = {"item_id": po["items"][0]["id"], "batch_no": "PO1", "mfg_date": str(today - timedelta(days=10)),
            "expiry_date": str(today + timedelta(days=700)), "mrp": 2.5, "selling_price": 2.0}
    # Can't receive a draft: it must be ordered first
    assert client.post(f"/api/pharmacy/purchase-orders/{po['id']}/receive", headers=PHARMACIST,
                       json={"lines": [line]}).status_code == 400
    assert client.post(f"/api/pharmacy/purchase-orders/{po['id']}/order",
                       headers=PHARMACIST).json()["status"] == "ordered"

    # A bad line (expired) means NOTHING is received
    bad = {**line, "expiry_date": str(today - timedelta(days=1))}
    assert client.post(f"/api/pharmacy/purchase-orders/{po['id']}/receive", headers=PHARMACIST,
                       json={"lines": [bad]}).status_code == 400
    assert client.get(f"/api/pharmacy/medicines/{med['id']}", headers=PHARMACIST).json()["batches"] == []

    done = client.post(f"/api/pharmacy/purchase-orders/{po['id']}/receive", headers=PHARMACIST,
                       json={"lines": [line]}).json()
    assert done["status"] == "received"
    batches = client.get(f"/api/pharmacy/medicines/{med['id']}", headers=PHARMACIST).json()["batches"]
    assert [(b["batch_no"], b["quantity"], b["purchase_price"]) for b in batches] == [("PO1", 200, 1.1)]


# ---------------------------------------------------------------- alerts and report

def test_alerts_and_stock_report():
    low = add_medicine(reorder_level=50)
    receive(low["id"], "L1", days_to_expiry=20, quantity=10)       # low AND expiring within 30 days
    receive(low["id"], "L2", days_to_expiry=75, quantity=5)        # expiring within 90

    a = client.get("/api/pharmacy/alerts", headers=PHARMACIST).json()
    assert any(x["medicine_id"] == low["id"] and x["stock"] == 15 for x in a["low_stock"])
    mine = {x["batch_no"]: x["window"] for x in a["expiring"] if x["medicine_id"] == low["id"]}
    assert mine == {"L1": 30, "L2": 90}
    assert a["counts"]["expiring_90"] >= a["counts"]["expiring_60"] >= a["counts"]["expiring_30"] >= 1

    report = client.get("/api/pharmacy/stock/report", headers=PHARMACIST).json()
    row = next(r for r in report["rows"] if r["medicine_id"] == low["id"])
    assert row["in_date_units"] == 15 and row["low_stock"] and row["value_at_cost"] == 15.0
    assert report["low_stock_count"] >= 1
