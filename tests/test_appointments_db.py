"""
Self-booking step 2: the appointments table and doctors' auto_accept
(db_models.py AppointmentRow, migration 0009). The booking API comes later;
here we check the DATABASE ITSELF keeps the important rules.
Run from the mediq/ folder with:   pytest
"""

import itertools
from datetime import date, datetime, time

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

import backend.app.main  # noqa: F401  (importing the app runs the migrations)
from backend.app.database import SessionLocal, engine
from backend.app.db_models import AppointmentRow, Role, User
from backend.app.models import AppointmentSource, AppointmentStatus

_n = itertools.count(1)
DAY = date(2027, 3, 2)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def user(db, role):
    u = User(full_name=f"{role.value} {next(_n)}", email=f"appt-db-{next(_n)}@example.com",
             hashed_password="x", role=role)
    db.add(u)
    db.commit()
    return u


def book(db, patient, doctor, start=time(10, 0), end=time(10, 10), status=AppointmentStatus.ACCEPTED,
         day=DAY, **extra):
    now = datetime.now()
    a = AppointmentRow(patient_id=patient.id if patient else None,
                       patient_name=patient.full_name if patient else "Walk-in", doctor_id=doctor.id,
                       department_id=1, date=day, slot_start=start, slot_end=end, status=status,
                       created_at=now, updated_at=now, **extra)
    db.add(a)
    db.commit()
    return a


def test_appointments_table_has_the_columns():
    columns = {c["name"] for c in inspect(engine).get_columns("appointments")}
    assert {"id", "patient_id", "doctor_id", "department_id", "date", "slot_start", "slot_end", "reason",
            "status", "token_id", "reject_reason", "created_at", "updated_at"} <= columns
    assert {"patient_name", "source", "priority", "checked_in_at"} <= columns      # extras for later steps


def test_doctors_auto_accept_by_default(db):
    doctor = user(db, Role.DOCTOR)
    assert doctor.auto_accept is True
    doctor.auto_accept = False
    db.commit()
    db.refresh(doctor)
    assert doctor.auto_accept is False


def test_new_booking_defaults(db):
    a = book(db, user(db, Role.PATIENT), user(db, Role.DOCTOR))
    assert a.source == AppointmentSource.ONLINE and a.priority == 0 and a.token_id is None


def test_no_double_booking_of_a_slot(db):
    doctor = user(db, Role.DOCTOR)
    first = book(db, user(db, Role.PATIENT), doctor)
    with pytest.raises(IntegrityError):                  # same doctor, day and start time
        book(db, user(db, Role.PATIENT), doctor)
    db.rollback()
    # Once the first booking is cancelled, the slot is free again
    first.status = AppointmentStatus.CANCELLED
    db.commit()
    book(db, user(db, Role.PATIENT), doctor)
    # Another doctor, or another time, was never a clash
    book(db, user(db, Role.PATIENT), user(db, Role.DOCTOR))
    book(db, user(db, Role.PATIENT), doctor, start=time(10, 10), end=time(10, 20))


def test_one_active_booking_per_patient_per_doctor_per_day(db):
    patient, doctor = user(db, Role.PATIENT), user(db, Role.DOCTOR)
    book(db, patient, doctor)
    with pytest.raises(IntegrityError):                  # a second slot with the same doctor that day
        book(db, patient, doctor, start=time(11, 0), end=time(11, 10))
    db.rollback()
    book(db, patient, user(db, Role.DOCTOR), start=time(11, 0), end=time(11, 10))   # another doctor: fine
    book(db, patient, doctor, day=date(2027, 3, 3))                                 # another day: fine


def test_walk_ins_without_an_account_dont_block_each_other(db):
    doctor = user(db, Role.DOCTOR)
    book(db, None, doctor, start=time(9, 0), end=time(9, 10), source=AppointmentSource.WALK_IN)
    book(db, None, doctor, start=time(9, 10), end=time(9, 20), source=AppointmentSource.WALK_IN)


def test_rejecting_needs_a_reason_and_slots_run_forwards(db):
    patient, doctor = user(db, Role.PATIENT), user(db, Role.DOCTOR)
    with pytest.raises(IntegrityError):
        book(db, patient, doctor, status=AppointmentStatus.REJECTED)               # no reason
    db.rollback()
    book(db, patient, doctor, status=AppointmentStatus.REJECTED, reject_reason="On leave that day")
    with pytest.raises(IntegrityError):
        book(db, patient, doctor, start=time(12, 0), end=time(11, 50))             # ends before it starts
    db.rollback()
