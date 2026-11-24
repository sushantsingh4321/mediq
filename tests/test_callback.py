"""
Tests for "Request Call Back" (routers/callback.py + services/telephony.py).

Every test runs in DRY_RUN mode (see conftest.py): nobody is ever dialled.
We pretend to be Twilio by POSTing to the webhooks ourselves.
Run from the mediq/ folder with:   pytest
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from backend.app.main import app
from helpers import admin_headers
from backend.app.database import SessionLocal
from backend.app.db_models import CallbackRow
from backend.app.routers.callback import normalize_indian_mobile

# Logged in as admin: these endpoints need a login since step 4 (accounts)
client = TestClient(app, headers=admin_headers())


def ask(mobile, name="Asha", consent=True):
    """Helper: a patient requests a call back."""
    return client.post("/api/callback", json={"name": name, "mobile": mobile, "consent": consent})


def staff_view(callback_id):
    """Helper: find one request on the staff list."""
    return next(c for c in client.get("/api/callback").json() if c["id"] == callback_id)


# ---------- phone number rules ----------

def test_indian_numbers_are_converted_to_plus91():
    for typed in ["9876543210", "98765 43210", "+91 98765-43210", "919876543210", "09876543210"]:
        assert normalize_indian_mobile(typed) == "+919876543210"


def test_bad_numbers_are_rejected():
    for typed in ["12345", "5876543210", "98765432101", "+44 7700 900123", "phone"]:
        assert normalize_indian_mobile(typed) is None
    assert ask("12345").status_code == 400


# ---------- making a request ----------

def test_request_is_saved_and_call_logged_in_dry_run():
    r = ask("98000 00001")
    assert r.status_code == 201
    body = r.json()
    assert body["mobile"] == "+919800000001" and body["status"] == "calling"

    saved = staff_view(body["id"])
    assert saved["dry_run"] is True
    assert saved["call_sid"].startswith("DRYRUN-")      # the fake provider was used
    assert "nobody was dialled" in saved["note"]


def test_consent_and_name_are_required():
    assert ask("9800000002", consent=False).status_code == 400
    assert ask("9800000002", name="  ").status_code == 400


def test_one_request_per_number_every_10_minutes():
    first = ask("9800000003")
    assert first.status_code == 201

    # Same number typed differently is still the same number
    again = ask("+91 98000 00003")
    assert again.status_code == 429
    assert "Retry-After" in again.headers

    # Pretend the first request was 11 minutes ago (change the saved row): allowed again
    with SessionLocal() as db:
        row = db.get(CallbackRow, first.json()["id"])
        row.created_at -= timedelta(minutes=11)
        db.commit()
    assert ask("9800000003").status_code == 201


# ---------- pretending to be Twilio ----------

def test_full_call_patient_connected():
    cb_id = ask("9800000004", name="Ravi").json()["id"]

    # Desk answers: we must tell Twilio to dial the patient
    r = client.post(f"/api/callback/{cb_id}/twiml", data={"CallStatus": "in-progress"})
    assert r.headers["content-type"].startswith("application/xml")
    assert "<Dial" in r.text and "<Number>+919800000004</Number>" in r.text
    assert f"/api/callback/{cb_id}/dial-status" in r.text

    # Patient answers and the call finishes
    client.post(f"/api/callback/{cb_id}/dial-status", data={"DialCallStatus": "completed"})
    assert staff_view(cb_id)["status"] == "done"

    # The desk call ending afterwards must NOT change "done" to "failed"
    client.post(f"/api/callback/{cb_id}/status", data={"CallStatus": "completed"})
    assert staff_view(cb_id)["status"] == "done"


def test_patient_does_not_answer():
    cb_id = ask("9800000005").json()["id"]
    client.post(f"/api/callback/{cb_id}/twiml")
    client.post(f"/api/callback/{cb_id}/dial-status", data={"DialCallStatus": "no-answer"})
    view = staff_view(cb_id)
    assert view["status"] == "failed" and "no-answer" in view["note"]


def test_desk_does_not_answer():
    cb_id = ask("9800000006").json()["id"]
    client.post(f"/api/callback/{cb_id}/status", data={"CallStatus": "no-answer"})
    view = staff_view(cb_id)
    assert view["status"] == "failed" and "desk did not answer" in view["note"]


# ---------- real mode (no calls are placed in these tests) ----------

def test_missing_twilio_settings_fail_safely(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
    r = ask("9800000007")
    assert r.status_code == 201                         # request is kept for staff...
    view = staff_view(r.json()["id"])
    assert view["status"] == "failed" and "TWILIO_ACCOUNT_SID" in view["note"]  # ...with the reason


def test_webhooks_need_a_real_twilio_signature(monkeypatch):
    cb_id = ask("9800000008").json()["id"]               # made in dry run

    # Switch to real mode with fake credentials (webhooks never place calls)
    token = "test-auth-token"
    for key, value in {"DRY_RUN": "false", "TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": token,
                       "TWILIO_FROM_NUMBER": "+10000000000", "DESK_NUMBER": "+910000000000",
                       "PUBLIC_BASE_URL": "https://example.test"}.items():
        monkeypatch.setenv(key, value)

    path = f"/api/callback/{cb_id}/dial-status"
    params = {"DialCallStatus": "completed"}

    # No signature, or a wrong one: refused
    assert client.post(path, data=params).status_code == 403
    assert client.post(path, data=params, headers={"X-Twilio-Signature": "fake"}).status_code == 403

    # Correct signature (computed the way Twilio does it): accepted
    good = RequestValidator(token).compute_signature("https://example.test" + path, params)
    assert client.post(path, data=params, headers={"X-Twilio-Signature": good}).status_code == 200
    assert staff_view(cb_id)["status"] == "done"
