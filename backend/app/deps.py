"""
"Who is making this request?": shared by every endpoint that needs a login.

The browser sends its login token in a header:
    Authorization: Bearer eyJhbGciOiJIUzI1NiIs...

An endpoint asks for the logged-in user like this:

    @router.get("/me")
    def me(user: User = Depends(get_current_user)): ...

FastAPI runs get_current_user first. If there's no valid token, the endpoint
never runs and the caller gets 401 Unauthorized.
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .db_models import RevokedToken, Role, User
from .security import InvalidToken, decode_access_token

# Reads the "Authorization: Bearer <token>" header. It also adds an
# "Authorize" button on /docs where you can paste a token to try endpoints.
bearer = HTTPBearer(auto_error=False, description="Paste the access_token from /api/auth/login")


def unauthorized(message: str) -> HTTPException:
    # 401 = "we don't know who you are". The WWW-Authenticate header is the
    # standard way to say "send a Bearer token".
    return HTTPException(status_code=401, detail=message, headers={"WWW-Authenticate": "Bearer"})


def get_token_payload(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                      db: Session = Depends(get_db)) -> dict:
    """Check the token: present, correctly signed, not expired, not logged out."""
    if credentials is None:
        raise unauthorized("Please log in first.")
    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidToken as e:
        raise unauthorized(str(e)) from e
    if db.get(RevokedToken, payload["jti"]) is not None:
        raise unauthorized("You have logged out. Please log in again.")
    return payload


def get_current_user(payload: dict = Depends(get_token_payload),
                     db: Session = Depends(get_db)) -> User:
    """The logged-in user, loaded fresh from the database on every request."""
    user = db.get(User, int(payload["sub"]))
    if user is None:  # account deleted after the token was made
        raise unauthorized("This account no longer exists.")
    return user


# ---------------------------------------------------------------- roles

def require_roles(*allowed: Role):
    """
    Build a check that only lets certain roles through. Admins always pass.

        @app.post("/api/departments/{id}/call-next",
                  dependencies=[Depends(require_roles(Role.DOCTOR))])

    No token / bad token  -> 401 Unauthorized  ("we don't know who you are")
    Wrong role            -> 403 Forbidden     ("we know you, but you can't do this")
    """
    def check(user: User = Depends(get_current_user)) -> User:
        if user.role == Role.ADMIN or user.role in allowed:
            return user
        needed = " or ".join(r.value for r in allowed) or "admin"
        raise HTTPException(status_code=403, detail=f"This needs a {needed} account.")
    return check


# Ready-made checks, so routers read like plain English.
admin_only = require_roles()                                   # only admins
doctor_only = require_roles(Role.DOCTOR)
reception_only = require_roles(Role.RECEPTIONIST)
any_staff = require_roles(Role.RECEPTIONIST, Role.DOCTOR)      # (and admins)
