"""
Database tables, written as Python classes (SQLAlchemy "ORM models").

Don't mix these up with models.py:
    models.py     Pydantic: the SHAPE of JSON going in and out of the API
    db_models.py  SQLAlchemy: the TABLES stored in the database

One class = one table, one attribute = one column. Changing a class here does
NOT change the database by itself: you also make a migration (see LEARN.md).
"""

import enum
from datetime import datetime, time, timezone

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .models import AmbulanceStatus, CallbackStatus, TokenStatus, TripStatus


class Role(str, enum.Enum):
    """What a user is allowed to do. New sign-ups are always patients."""
    PATIENT = "patient"
    RECEPTIONIST = "receptionist"
    DOCTOR = "doctor"
    ADMIN = "admin"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)          # 1, 2, 3... given by the database
    full_name: Mapped[str] = mapped_column(String(100))
    # unique=True: the DATABASE itself refuses a second account with the same email
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20))      # optional ("| None")
    # Never the real password: a one-way scrambled version (bcrypt, added in step 2)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        # Stored as plain text ("doctor"), and the database refuses any other value.
        Enum(Role, native_enum=False, length=20, create_constraint=True, name="user_role",
             values_callable=lambda roles: [r.value for r in roles]),
        default=Role.PATIENT,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    def __repr__(self) -> str:  # how a User prints while debugging
        return f"<User {self.id} {self.email} ({self.role.value})>"


class RevokedToken(Base):
    """
    Login tokens that were logged out before they expired.

    A JWT is valid until its expiry time on its own; the server can't "take it
    back". So on logout we write down its unique id (jti) here, and every request
    checks this list. Rows can be deleted once the token would have expired anyway.
    """
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class OpdSlot(Base):
    """
    One weekly OPD session of a doctor, e.g.
        Dr. Meera Rao, General Medicine, Room 2, every Monday 09:00-13:00

    weekday: 0 = Monday ... 6 = Sunday (Python's datetime.weekday() numbering).
    Times are hospital local time (HOSPITAL_TIMEZONE). Sessions can't cross
    midnight: a night shift is two sessions (22:00-23:59 and 00:00-06:00).
    """
    __tablename__ = "opd_slots"
    __table_args__ = (
        # The database itself refuses impossible rows.
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_opd_slots_weekday"),
        CheckConstraint("start_time < end_time", name="ck_opd_slots_start_before_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # A FOREIGN KEY: must be the id of a row in users. Delete the user and their
    # sessions go too (CASCADE).
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Departments still live in memory (store.py), so this is a plain number for now.
    department_id: Mapped[int] = mapped_column(index=True)
    weekday: Mapped[int]
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    room: Mapped[int]

    # slot.doctor gives the User object (SQLAlchemy looks it up for us).
    doctor: Mapped[User] = relationship()


# =====================================================================
# Data that used to live in Python memory (lost on every restart).
# The names end in "Row" so they don't clash with the Pydantic models of the
# same idea in models.py (Department, Token...): a Row is what's SAVED, the
# Pydantic model is what the API SENDS.
# =====================================================================

def _enum(enum_cls, name: str) -> Enum:
    """Store an Enum as plain text ("waiting"); the database refuses other values."""
    return Enum(enum_cls, native_enum=False, length=20, create_constraint=True, name=name,
                values_callable=lambda members: [m.value for m in members])


class DepartmentRow(Base):
    """An OPD department (was store.departments)."""
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(5), unique=True)      # GEN, PED...
    name: Mapped[str] = mapped_column(String(100))
    doctors: Mapped[int]                                           # rooms working in parallel (c)
    avg_consult_minutes: Mapped[float]
    expected_patients_per_hour: Mapped[float]


class TokenRow(Base):
    """One patient in the OPD queue (was store.tokens)."""
    __tablename__ = "tokens"
    __table_args__ = (
        # GEN-007 can only exist once per department
        UniqueConstraint("department_id", "seq", name="uq_tokens_department_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    seq: Mapped[int]                                   # 7 in GEN-007
    number: Mapped[str] = mapped_column(String(20))    # "GEN-007"
    patient_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[TokenStatus] = mapped_column(_enum(TokenStatus, "token_status"), index=True)
    room: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    called_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class WardRow(Base):
    """A hospital ward (Module 1, was bed_store.wards)."""
    __tablename__ = "wards"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # ward.beds: its beds in number order. Deleting a ward deletes its beds.
    beds: Mapped[list["BedRow"]] = relationship(order_by="BedRow.number", cascade="all, delete-orphan")


class BedRow(Base):
    """One numbered bed. Free when patient_name is empty."""
    __tablename__ = "beds"
    __table_args__ = (UniqueConstraint("ward_id", "number", name="uq_beds_ward_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ward_id: Mapped[int] = mapped_column(ForeignKey("wards.id", ondelete="CASCADE"), index=True)
    number: Mapped[int]
    patient_name: Mapped[str | None] = mapped_column(String(100))
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime)

    @property
    def occupied(self) -> bool:
        return self.patient_name is not None


class EnquiryRow(Base):
    """A "Quick enquiry" from the home page (was website.enquiries)."""
    __tablename__ = "enquiries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    country_code: Mapped[str] = mapped_column(String(6))
    mobile: Mapped[str] = mapped_column(String(15))
    speciality: Mapped[str] = mapped_column(String(100))
    consent: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime)


class CallbackRow(Base):
    """A "Request Call Back" (was callback.callbacks)."""
    __tablename__ = "callback_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    mobile: Mapped[str] = mapped_column(String(15), index=True)     # +91XXXXXXXXXX
    status: Mapped[CallbackStatus] = mapped_column(_enum(CallbackStatus, "callback_status"))
    note: Mapped[str] = mapped_column(String(300), default="")
    call_sid: Mapped[str | None] = mapped_column(String(64))
    dry_run: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


# =====================================================================
# Module 3: Ambulance
# =====================================================================

class AmbulanceRow(Base):
    """One ambulance, its driver and where it is."""
    __tablename__ = "ambulances"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)        # AMB-01
    vehicle_number: Mapped[str] = mapped_column(String(20))
    driver_name: Mapped[str] = mapped_column(String(100))
    driver_phone: Mapped[str] = mapped_column(String(15))             # +91XXXXXXXXXX
    status: Mapped[AmbulanceStatus] = mapped_column(_enum(AmbulanceStatus, "ambulance_status"), index=True)
    location: Mapped[str] = mapped_column(String(200))               # plain text, e.g. "Hospital bay 2"
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TripRow(Base):
    """One request for an ambulance, from "requested" to "completed"."""
    __tablename__ = "ambulance_trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Empty until an ambulance is assigned
    ambulance_id: Mapped[int | None] = mapped_column(ForeignKey("ambulances.id"), index=True)
    patient_name: Mapped[str] = mapped_column(String(100))
    contact_phone: Mapped[str] = mapped_column(String(15))
    pickup: Mapped[str] = mapped_column(String(200))
    destination: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[TripStatus] = mapped_column(_enum(TripStatus, "trip_status"), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)   # completed or cancelled

    ambulance: Mapped[AmbulanceRow | None] = relationship()
