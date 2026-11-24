"""
Security helpers: password hashing and login tokens.

1. PASSWORDS are never stored. We store a bcrypt HASH: a one-way scramble.
       hash_password("secret123")  ->  "$2b$12$Qx0...long random-looking text..."
   You can't turn the hash back into the password. To check a login we hash
   what the user typed and compare (bcrypt.checkpw does this safely).
   Each hash includes a random "salt", so two people with the same password
   get different hashes.

2. LOGIN TOKENS are JWTs (JSON Web Tokens). After a correct login the server
   gives the browser a token, a signed note that says:
       {"sub": "7", "role": "doctor", "exp": <in 60 minutes>}
   The browser sends it back with every request. The SIGNATURE (made with
   SECRET_KEY) proves the server wrote it: change one letter of the note and
   the signature no longer matches. The note is signed, NOT encrypted, so never
   put secrets in it.
"""

import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import get_settings

log = logging.getLogger("uvicorn.error")

ALGORITHM = "HS256"                 # HMAC-SHA256: sign and check with the same secret key
BCRYPT_MAX_BYTES = 72               # bcrypt only looks at the first 72 bytes of a password


class InvalidToken(Exception):
    """The token is missing, expired, tampered with, or signed with another key."""


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    """Return a bcrypt hash of the password, ready to save in users.hashed_password."""
    data = password.encode("utf-8")
    if len(data) > BCRYPT_MAX_BYTES:
        # bcrypt would silently ignore the rest, so we refuse instead.
        raise ValueError(f"Password is too long (max {BCRYPT_MAX_BYTES} bytes)")
    # gensalt() makes a new random salt; 12 "rounds" = deliberately slow (~0.2 s)
    # so an attacker who steals the database can't try billions of guesses.
    return bcrypt.hashpw(data, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """True if `password` is the one that produced `hashed`."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:  # too long, or not a valid bcrypt hash
        return False


# A hash of a random password. Login uses it when the email doesn't exist, so
# "unknown email" takes as long as "wrong password" and can't be told apart by timing.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


# ---------------------------------------------------------------- secret key

_fallback_key: str | None = None


def get_secret_key() -> str:
    """
    SECRET_KEY from .env. If it's missing we make a random one for this run and
    warn: everything still works, but everyone is logged out on every restart.
    (We never fall back to a fixed, guessable key.)
    """
    global _fallback_key
    key = get_settings().secret_key
    if key:
        if len(key) < 32:
            log.warning("SECRET_KEY is shorter than 32 characters; please make a longer one.")
        return key
    if os.getenv("VERCEL"):
        # Serverless: many short-lived copies of the app run at once. Each would
        # invent its OWN random key, so a login made on one copy would fail on
        # the next click if it reaches another. Stop with a clear message instead.
        raise RuntimeError("SECRET_KEY is not set. Add it in Vercel: Project > Settings > "
                           "Environment Variables (see DEPLOY.md), then redeploy.")
    if _fallback_key is None:
        _fallback_key = secrets.token_urlsafe(48)
        log.warning("SECRET_KEY is not set in .env: using a temporary random key. "
                    "Logins will stop working when the server restarts.")
    return _fallback_key


# ---------------------------------------------------------------- tokens

def create_access_token(user_id: int, role: str, expires_in: timedelta | None = None) -> str:
    """Make a signed login token for one user, valid for ACCESS_TOKEN_MINUTES."""
    now = datetime.now(timezone.utc)
    if expires_in is None:
        expires_in = timedelta(minutes=get_settings().access_token_minutes)
    payload = {
        "sub": str(user_id),        # "subject": who this token is for
        "role": role,
        "iat": now,                 # issued at
        "exp": now + expires_in,    # expires at (PyJWT checks this for us)
        "jti": uuid.uuid4().hex,    # a unique id for this token (used by logout, step 3)
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Check the signature and expiry. Return the payload, or raise InvalidToken."""
    try:
        return jwt.decode(
            token,
            get_secret_key(),
            algorithms=[ALGORITHM],                     # accept ONLY our algorithm
            options={"require": ["sub", "exp", "jti"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise InvalidToken("Your session has expired. Please log in again.") from e
    except jwt.InvalidTokenError as e:
        raise InvalidToken("Invalid login token. Please log in again.") from e
