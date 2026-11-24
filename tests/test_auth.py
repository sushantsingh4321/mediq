"""
Tests for step 3: signup, login, me, logout (routers/auth.py).
They use the separate test database from conftest.py.
Run from the mediq/ folder with:   pytest
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.db_models import RevokedToken, User
from backend.app.main import app
from backend.app.security import create_access_token

client = TestClient(app)

PASSWORD = "good-password-1"


def signup(email, password=PASSWORD, **extra):
    """Helper: sign up a new account."""
    return client.post("/api/auth/signup", json={"full_name": "Asha Patel", "email": email,
                                                 "password": password, **extra})


def login(email, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- signup ----------

def test_signup_creates_a_patient_and_logs_in():
    r = signup("asha@mediq.example", phone="98765 43210")
    assert r.status_code == 201
    body = r.json()
    assert body["token_type"] == "bearer" and body["access_token"]
    assert body["expires_in"] == 60 * 60
    assert body["user"]["role"] == "patient"
    assert body["user"]["phone"] == "+919876543210"
    assert "password" not in str(body) and "hashed" not in str(body)


def test_password_is_stored_hashed():
    signup("hash.check@mediq.example")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "hash.check@mediq.example"))
    assert user.hashed_password != PASSWORD and user.hashed_password.startswith("$2b$")


def test_signup_cannot_choose_admin_role():
    r = signup("sneaky@mediq.example", role="admin")
    assert r.status_code == 201 and r.json()["user"]["role"] == "patient"


def test_duplicate_email_is_refused_even_with_different_capitals():
    assert signup("dup@mediq.example").status_code == 201
    again = signup("DUP@Mediq.Example")
    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]


def test_signup_rules():
    short = signup("short@mediq.example", password="1234567")
    assert short.status_code == 400 and "at least 8" in short.json()["detail"]
    assert signup("ok8@mediq.example", password="12345678").status_code == 201   # exactly 8 is fine
    assert signup("not-an-email").status_code == 422
    assert signup("phone@mediq.example", phone="12345").status_code == 400
    assert client.post("/api/auth/signup", json={"full_name": "  ", "email": "blank@mediq.example",
                                                 "password": PASSWORD}).status_code == 400


# ---------- login ----------

def test_login_returns_a_working_token():
    signup("login@mediq.example")
    r = login("Login@MEDIQ.example")                      # email capitals don't matter
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers=auth_header(r.json()["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == "login@mediq.example"


def test_wrong_password_and_unknown_email_get_the_same_answer():
    signup("wrongpw@mediq.example")
    wrong = login("wrongpw@mediq.example", "not-the-password")
    unknown = login("nobody@mediq.example")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "Incorrect email or password."


# ---------- me ----------

def test_me_needs_a_valid_token():
    assert client.get("/api/auth/me").status_code == 401
    bad = client.get("/api/auth/me", headers=auth_header("not.a.token"))
    assert bad.status_code == 401 and bad.headers["WWW-Authenticate"] == "Bearer"


# ---------- logout ----------

def test_logout_cancels_the_token():
    token = signup("logout@mediq.example").json()["access_token"]
    assert client.get("/api/auth/me", headers=auth_header(token)).status_code == 200

    assert client.post("/api/auth/logout", headers=auth_header(token)).status_code == 200
    after = client.get("/api/auth/me", headers=auth_header(token))
    assert after.status_code == 401 and "logged out" in after.json()["detail"]

    # Logging in again gives a new token that works
    fresh = login("logout@mediq.example").json()["access_token"]
    assert client.get("/api/auth/me", headers=auth_header(fresh)).status_code == 200


def test_logout_needs_a_token():
    assert client.post("/api/auth/logout").status_code == 401


# ---------- step 6: extra checks on real API calls ----------

def user_id(email):
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.email == email)).id


def test_expired_token_is_refused_by_the_api():
    signup("expired@mediq.example")
    old = create_access_token(user_id("expired@mediq.example"), "patient", expires_in=timedelta(seconds=-1))
    r = client.get("/api/auth/me", headers=auth_header(old))
    assert r.status_code == 401 and "expired" in r.json()["detail"]


def test_role_comes_from_the_database_not_the_token():
    # Even a correctly signed token that SAYS "admin" doesn't make a patient an admin:
    # every request looks the user up and uses the role stored in the database.
    signup("claims-admin@mediq.example")
    token = create_access_token(user_id("claims-admin@mediq.example"), "admin")
    assert client.get("/api/auth/me", headers=auth_header(token)).json()["role"] == "patient"
    assert client.get("/api/auth/users", headers=auth_header(token)).status_code == 403


def test_token_of_a_deleted_account_stops_working():
    token = signup("deleted@mediq.example").json()["access_token"]
    with SessionLocal() as db:
        db.delete(db.get(User, user_id("deleted@mediq.example")))
        db.commit()
    r = client.get("/api/auth/me", headers=auth_header(token))
    assert r.status_code == 401 and "no longer exists" in r.json()["detail"]


def test_logout_tidies_up_old_revoked_tokens():
    with SessionLocal() as db:
        db.add(RevokedToken(jti="old-one", expires_at=datetime.now(timezone.utc) - timedelta(hours=2)))
        db.commit()
    token = signup("tidy@mediq.example").json()["access_token"]
    client.post("/api/auth/logout", headers=auth_header(token))
    with SessionLocal() as db:
        assert db.get(RevokedToken, "old-one") is None      # expired anyway: removed
