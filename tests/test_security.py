"""
Tests for step 2: password hashing and login tokens (backend/app/security.py).
Run from the mediq/ folder with:   pytest
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from backend.app.security import (
    InvalidToken, create_access_token, decode_access_token, hash_password, verify_password,
)


# ---------- passwords ----------

def test_password_is_hashed_not_stored():
    hashed = hash_password("correct horse 42")
    assert hashed != "correct horse 42"
    assert "correct horse" not in hashed
    assert hashed.startswith("$2b$12$")          # bcrypt, 12 rounds


def test_right_and_wrong_password():
    hashed = hash_password("correct horse 42")
    assert verify_password("correct horse 42", hashed) is True
    assert verify_password("correct horse 43", hashed) is False
    assert verify_password("", hashed) is False


def test_same_password_gives_different_hashes():
    # Random salt: two users with the same password don't get the same hash
    a, b = hash_password("same-password"), hash_password("same-password")
    assert a != b
    assert verify_password("same-password", a) and verify_password("same-password", b)


def test_password_longer_than_bcrypt_allows_is_refused():
    with pytest.raises(ValueError):
        hash_password("x" * 73)
    assert verify_password("x" * 73, hash_password("x" * 72)) is False


def test_garbage_hash_does_not_crash():
    assert verify_password("anything", "not-a-bcrypt-hash") is False


# ---------- tokens ----------

def test_token_round_trip():
    token = create_access_token(user_id=7, role="doctor")
    payload = decode_access_token(token)
    assert payload["sub"] == "7" and payload["role"] == "doctor"
    assert payload["jti"]                        # unique id, used for logout later


def test_token_expires_after_60_minutes():
    payload = decode_access_token(create_access_token(1, "patient"))
    lifetime = payload["exp"] - payload["iat"]
    assert lifetime == 60 * 60


def test_expired_token_is_rejected():
    token = create_access_token(1, "patient", expires_in=timedelta(seconds=-1))
    with pytest.raises(InvalidToken, match="expired"):
        decode_access_token(token)


def test_tampered_token_is_rejected():
    # Try to turn a patient into an admin by editing the token: the signature breaks
    token = create_access_token(1, "patient")
    header, _, signature = token.split(".")
    fake_payload = jwt.encode({"sub": "1", "role": "admin", "jti": "x",
                               "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                              "some-other-key-only-used-to-build-a-payload-123",
                              algorithm="HS256").split(".")[1]
    with pytest.raises(InvalidToken):
        decode_access_token(f"{header}.{fake_payload}.{signature}")


def test_token_signed_with_another_key_is_rejected():
    forged = jwt.encode({"sub": "1", "role": "admin", "jti": "x",
                         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                        "an-attackers-own-key-that-is-long-enough-1234", algorithm="HS256")
    with pytest.raises(InvalidToken):
        decode_access_token(forged)


def test_unsigned_token_is_rejected():
    # The classic "alg: none" trick: a token with no signature at all
    unsigned = jwt.encode({"sub": "1", "role": "admin", "jti": "x",
                           "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                          None, algorithm="none")
    with pytest.raises(InvalidToken):
        decode_access_token(unsigned)


def test_garbage_token_is_rejected():
    with pytest.raises(InvalidToken):
        decode_access_token("not.a.token")
