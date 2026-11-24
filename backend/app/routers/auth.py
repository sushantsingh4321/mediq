"""
User accounts: sign up, log in, "who am I?", log out.

URLs:
    POST /api/auth/signup   create a PATIENT account (and log in straight away)
    POST /api/auth/login    email + password  ->  login token
    GET  /api/auth/me       the logged-in user   (needs a token)
    POST /api/auth/logout   cancel this token    (needs a token)
    POST /api/auth/users    ADMIN ONLY: create a doctor / pharmacist / admin account
    GET  /api/auth/users    ADMIN ONLY: list all accounts
    PATCH /api/auth/users/{id}  ADMIN ONLY: change someone's role

Passwords are hashed with bcrypt and tokens are JWTs: see security.py.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal, get_db
from ..db_models import OpdSlot, RevokedToken, Role, User
from ..deps import admin_only, get_current_user, get_token_payload
from ..security import BCRYPT_MAX_BYTES, DUMMY_HASH, create_access_token, hash_password, verify_password
from .callback import normalize_indian_mobile

router = APIRouter(prefix="/api/auth", tags=["accounts"])
log = logging.getLogger("uvicorn.error")

MIN_PASSWORD_LENGTH = 8


# ---------------------------------------------------------------- models (JSON shapes)

class SignupRequest(BaseModel):
    full_name: str = Field(..., max_length=100, examples=["Asha Patel"])
    email: EmailStr = Field(..., examples=["asha@mediq.example"])
    phone: str | None = Field(None, max_length=20, examples=["98765 43210"],
                              description="Optional Indian mobile number")
    password: str = Field(..., max_length=200, examples=["a-long-password"],
                          description=f"At least {MIN_PASSWORD_LENGTH} characters")
    # Note: there is NO "role" field. Anything extra a caller sends (like
    # "role": "admin") is simply ignored, so sign-ups are always patients.


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=200)


class UserOut(BaseModel):
    """A user as the API shows it. hashed_password is deliberately NOT here."""
    model_config = {"from_attributes": True}   # lets Pydantic read a SQLAlchemy User object

    id: int
    full_name: str
    email: str
    phone: str | None
    role: Role
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def mark_as_utc(cls, value: datetime) -> datetime:
        # We save times in UTC, but SQLite forgets the time zone. Without this
        # the browser would read 15:55 UTC as 15:55 India time (5.5 hours off).
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int          # seconds until the token stops working
    user: UserOut


# ---------------------------------------------------------------- helpers

def clean_email(email: str) -> str:
    """Asha@Example.com and asha@example.com are the same person: store lowercase."""
    return email.strip().lower()


def check_password_rules(password: str):
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400,
                            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise HTTPException(status_code=400,
                            detail=f"Password is too long (max {BCRYPT_MAX_BYTES} characters).")


def token_response(user: User) -> TokenResponse:
    minutes = get_settings().access_token_minutes
    return TokenResponse(access_token=create_access_token(user.id, user.role.value),
                         expires_in=minutes * 60, user=UserOut.model_validate(user))


def create_user(db: Session, *, full_name: str, email: str, password: str,
                phone: str | None = None, role: Role = Role.PATIENT) -> User:
    """
    Check the details and save a new user. Used by signup now, and later by
    "admin creates a doctor" and the first-run admin (step 4).
    """
    full_name = full_name.strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Please enter your full name.")
    check_password_rules(password)

    normalized_phone = None
    if phone and phone.strip():
        normalized_phone = normalize_indian_mobile(phone)
        if normalized_phone is None:
            raise HTTPException(status_code=400, detail="Please enter a valid 10-digit Indian mobile number.")

    email = clean_email(email)
    if db.scalar(select(User).where(User.email == email)) is not None:
        # 409 Conflict: the request is fine, but it clashes with existing data
        raise HTTPException(status_code=409, detail="An account with this email already exists. Try logging in.")

    user = User(full_name=full_name, email=email, phone=normalized_phone,
                hashed_password=hash_password(password), role=role)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two sign-ups with the same email at the same moment: the database's
        # unique rule catches the second one even though our check above passed.
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists. Try logging in.")
    db.refresh(user)
    return user


# ---------------------------------------------------------------- endpoints

@router.post("/signup", response_model=TokenResponse, status_code=201)
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    """Anyone can sign up. New accounts are ALWAYS patients."""
    user = create_user(db, full_name=data.full_name, email=data.email,
                       password=data.password, phone=data.phone, role=Role.PATIENT)
    return token_response(user)  # logged in straight away


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == clean_email(data.email)))
    # Always run ONE bcrypt check, even for an unknown email (against DUMMY_HASH),
    # so both cases take the same time and give the same message. That way the
    # login form can't be used to find out who has an account.
    password_ok = verify_password(data.password, user.hashed_password if user else DUMMY_HASH)
    if user is None or not password_ok:
        raise HTTPException(status_code=401, detail="Incorrect email or password.",
                            headers={"WWW-Authenticate": "Bearer"})
    return token_response(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """Who am I? The frontend uses this to show your name in the header."""
    return user


@router.post("/logout")
def logout(payload: dict = Depends(get_token_payload), db: Session = Depends(get_db)):
    """Cancel the token that was sent. The browser should also forget it."""
    now = datetime.now(timezone.utc)
    # Tidy up: tokens that have expired anyway don't need to be remembered.
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at < now))
    db.add(RevokedToken(jti=payload["jti"],
                        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc)))
    db.commit()
    return {"detail": "You have been logged out."}


# ---------------------------------------------------------------- admin: staff accounts

class StaffCreate(BaseModel):
    """What an admin sends to create an account with any role."""
    full_name: str = Field(..., max_length=100, examples=["Dr. Meera Rao"])
    email: EmailStr = Field(..., examples=["meera.rao@mediq.example"])
    phone: str | None = Field(None, max_length=20)
    password: str = Field(..., max_length=200, description=f"At least {MIN_PASSWORD_LENGTH} characters")
    role: Role = Field(..., examples=["doctor"])


@router.post("/users", response_model=UserOut, status_code=201, dependencies=[Depends(admin_only)])
def create_staff_account(data: StaffCreate, db: Session = Depends(get_db)):
    """ADMIN ONLY: create a doctor, pharmacist, admin (or patient) account."""
    return create_user(db, full_name=data.full_name, email=data.email, password=data.password,
                       phone=data.phone, role=data.role)


@router.get("/users", response_model=list[UserOut], dependencies=[Depends(admin_only)])
def list_accounts(db: Session = Depends(get_db)):
    """ADMIN ONLY: every account, newest first."""
    return db.scalars(select(User).order_by(User.id.desc())).all()


# ---------------------------------------------------------------- first admin

def seed_first_admin():
    """
    On start-up: if there is no admin yet and ADMIN_EMAIL + ADMIN_PASSWORD are in
    .env, create that admin. Never changes an existing account.
    """
    s = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.role == Role.ADMIN)) is not None:
            return                                  # we already have an admin
        if not (s.admin_email and s.admin_password):
            log.warning("No admin account yet. Set ADMIN_EMAIL and ADMIN_PASSWORD in .env "
                        "and restart to create one.")
            return
        try:
            create_user(db, full_name=s.admin_name, email=s.admin_email,
                        password=s.admin_password, role=Role.ADMIN)
            log.info("Created the first admin account: %s", clean_email(s.admin_email))
        except HTTPException as e:                  # e.g. password too short, email taken
            log.warning("Could not create the admin from .env: %s", e.detail)


class RoleChange(BaseModel):
    role: Role


@router.patch("/users/{user_id}", response_model=UserOut)
def change_role(user_id: int, data: RoleChange, db: Session = Depends(get_db),
                admin: User = Depends(admin_only)):
    """
    ADMIN ONLY: change someone's role (e.g. make a pharmacist an admin).
    It applies on their very next request, because roles are read from the
    database every time (see deps.py).
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.id == admin.id and data.role != Role.ADMIN:
        # Otherwise an admin could lock everyone out by demoting the only admin.
        raise HTTPException(status_code=400, detail="You can't remove your own admin role. Ask another admin.")
    if user.role == Role.DOCTOR and data.role != Role.DOCTOR:
        sessions = db.scalars(select(OpdSlot).where(OpdSlot.doctor_id == user.id)).all()
        if sessions:
            raise HTTPException(status_code=409,
                                detail=f"{user.full_name} still has {len(sessions)} OPD session(s). "
                                       "Remove them on the Doctor schedule page first.")
    user.role = data.role
    db.commit()
    return user
