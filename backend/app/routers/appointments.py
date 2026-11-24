"""
Module 5: patients book their own appointments. The rules are in
services/appointments.py; this file is the URLs.

    GET  /api/doctors?department_id=3          doctors with OPD sessions there (anyone)
    GET  /api/doctors/{id}/slots?date=...      that day's 10-minute slots, free or not (anyone)
    POST /api/appointments                     PATIENT: book a free slot
    GET  /api/appointments/me                  PATIENT: my bookings, newest day first
    POST /api/appointments/{id}/cancel         PATIENT (the owner): cancel, up to 1 hour before
    POST /api/appointments/{id}/checkin        PATIENT (the owner) or the booking's DOCTOR: "I've arrived"

    GET   /api/doctor/appointments             DOCTOR: my bookings, grouped by date
    POST  /api/appointments/{id}/accept        DOCTOR (whose booking it is): accept a request
    POST  /api/appointments/{id}/reject        DOCTOR (whose booking it is): reject, with a reason
    GET   /api/doctor/settings                 DOCTOR: my auto_accept switch
    PATCH /api/doctor/settings                 DOCTOR: turn auto_accept on or off
    POST  /api/doctor/walk-ins                 DOCTOR: add a patient who just turned up

Anyone may look at doctors and free times (no patient details in them);
booking, "my appointments" and cancelling need the patient's own login;
accepting and rejecting need the login of the doctor the booking is WITH.
"""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..db_models import AppointmentRow, OpdSlot, Role, User
from ..deps import doctor_only, patient_only, require_roles
from ..models import ACTIVE_APPOINTMENT_STATUSES, AppointmentSource, AppointmentStatus, TokenStatus
from ..queue_view import to_view
from ..store import store as token_store
from ..services import appointments as svc
from ..store import store
from .schedule import WEEKDAYS

router = APIRouter(tags=["appointments"])


# ---------------------------------------------------------------- shapes

class SessionOut(BaseModel):
    weekday: int
    weekday_name: str
    start_time: time
    end_time: time
    room: int


class BookableDoctor(BaseModel):
    """Public: the name and when they work. Never the email or phone."""
    id: int
    full_name: str
    department_id: int
    sessions: list[SessionOut]


class SlotOut(BaseModel):
    start: time
    end: time
    room: int
    department_id: int
    free: bool
    why_not: str        # "" when free, "booked" or "past"


class DaySlots(BaseModel):
    doctor_id: int
    doctor_name: str
    date: date
    slot_minutes: int
    slots: list[SlotOut]


class AppointmentIn(BaseModel):
    doctor_id: int
    department_id: int
    date: date
    slot_start: time = Field(..., examples=["10:20"])
    reason: str = Field(..., min_length=3, max_length=500, examples=["Fever and sore throat for 3 days"])


class AppointmentOut(BaseModel):
    id: int
    patient_name: str
    doctor_id: int
    doctor_name: str
    department_id: int
    department_name: str
    room: int | None             # from the doctor's session that day
    date: date
    slot_start: time
    slot_end: time
    reason: str
    status: AppointmentStatus
    source: AppointmentSource
    reject_reason: str | None
    priority: int
    token_id: int | None
    token_number: str | None     # "GEN-012", once accepted
    token_status: TokenStatus | None
    token_room: int | None           # set once the doctor calls them in
    people_ahead: int | None         # checked in: in the queue; booked (today): if they checked in now
    estimated_wait_minutes: float | None
    can_check_in: bool               # may the PATIENT press "I've arrived" now?
    check_in_opens_at: datetime
    missed_after: datetime           # not checked in by then -> no_show
    checked_in_at: datetime | None
    can_cancel: bool
    cancel_closes_at: datetime
    created_at: datetime
    updated_at: datetime


def room_for(db: Session, a: AppointmentRow) -> int | None:
    for s in svc.sessions_on(db, a.doctor_id, a.date, a.department_id):
        if s.start_time <= a.slot_start < s.end_time:
            return s.room
    return None


def appointment_out(db: Session, a: AppointmentRow) -> AppointmentOut:
    dept = store.departments.get(a.department_id)
    # Live queue numbers only for today's bookings that are still on their way in
    live = None
    if a.token is not None and a.date == svc.now().date() and a.token.status in (TokenStatus.BOOKED, TokenStatus.WAITING):
        live = to_view(token_store.get_token(a.token.id))
    return AppointmentOut(
        id=a.id, patient_name=a.patient_name, doctor_id=a.doctor_id, doctor_name=a.doctor.full_name,
        department_id=a.department_id, department_name=dept.name if dept else "Unknown", room=room_for(db, a),
        date=a.date, slot_start=a.slot_start, slot_end=a.slot_end, reason=a.reason, status=a.status,
        source=a.source, reject_reason=a.reject_reason, priority=a.priority, token_id=a.token_id,
        token_number=a.token.number if a.token else None, token_status=a.token.status if a.token else None,
        token_room=a.token.room if a.token else None,
        people_ahead=live.people_ahead if live else None,
        estimated_wait_minutes=live.estimated_wait_minutes if live else None,
        can_check_in=svc.can_check_in(a), check_in_opens_at=svc.check_in_opens_at(a),
        missed_after=svc.missed_after(a), checked_in_at=a.checked_in_at,
        can_cancel=svc.can_cancel(a),
        cancel_closes_at=svc.cancel_closes_at(a), created_at=a.created_at, updated_at=a.updated_at)


def run(action):
    """Turn a broken booking rule into an HTTP error with its plain-words message."""
    try:
        return action()
    except svc.BookingError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from None


# ---------------------------------------------------------------- anyone: doctors and free times

@router.get("/api/doctors", response_model=list[BookableDoctor])
def bookable_doctors(department_id: int = Query(...), db: Session = Depends(get_db)):
    """Doctors who have at least one weekly OPD session in this department."""
    rows = db.scalars(select(OpdSlot).where(OpdSlot.department_id == department_id)
                      .order_by(OpdSlot.weekday, OpdSlot.start_time)).all()
    doctors: dict[int, BookableDoctor] = {}
    for s in rows:
        d = doctors.setdefault(s.doctor_id, BookableDoctor(
            id=s.doctor_id, full_name=s.doctor.full_name, department_id=department_id, sessions=[]))
        d.sessions.append(SessionOut(weekday=s.weekday, weekday_name=WEEKDAYS[s.weekday],
                                     start_time=s.start_time, end_time=s.end_time, room=s.room))
    return sorted(doctors.values(), key=lambda d: d.full_name)


@router.get("/api/doctors/{doctor_id}/slots", response_model=DaySlots)
def doctor_slots(doctor_id: int, date: date, department_id: int | None = None, db: Session = Depends(get_db)):
    doctor = run(lambda: svc.get_doctor(db, doctor_id))
    slots = run(lambda: svc.slots_for(db, doctor_id, date, department_id))
    return DaySlots(doctor_id=doctor.id, doctor_name=doctor.full_name, date=date,
                    slot_minutes=svc.SLOT_MINUTES, slots=[SlotOut(**vars(s)) for s in slots])


# ---------------------------------------------------------------- patients

@router.post("/api/appointments", response_model=AppointmentOut, status_code=201)
def book(data: AppointmentIn, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    a = run(lambda: svc.book(db, patient=user, doctor_id=data.doctor_id, department_id=data.department_id,
                             day=data.date, slot_start=data.slot_start, reason=data.reason))
    return appointment_out(db, a)


@router.get("/api/appointments/me", response_model=list[AppointmentOut])
def my_appointments(user: User = Depends(patient_only), db: Session = Depends(get_db)):
    """Upcoming first (soonest at the top), then past ones, most recent first."""
    svc.sweep_no_shows(db)
    rows = db.scalars(select(AppointmentRow).where(AppointmentRow.patient_id == user.id)).all()
    today = svc.now().date()
    upcoming = sorted((a for a in rows if a.date >= today), key=lambda a: (a.date, a.slot_start))
    past = sorted((a for a in rows if a.date < today), key=lambda a: (a.date, a.slot_start), reverse=True)
    return [appointment_out(db, a) for a in upcoming + past]


@router.post("/api/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel(appointment_id: int, user: User = Depends(patient_only), db: Session = Depends(get_db)):
    a = db.get(AppointmentRow, appointment_id)
    # Someone else's booking: answer "not found", so ids can't be used to probe other people's bookings
    if a is None or (a.patient_id != user.id and user.role != Role.ADMIN):
        raise HTTPException(status_code=404, detail="Booking not found")
    return appointment_out(db, run(lambda: svc.cancel(db, a)))


# ---------------------------------------------------------------- doctors

class RejectIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=300, examples=["On leave that day. Please book Dr. Patel."])


class DayOfAppointments(BaseModel):
    date: date
    appointments: list[AppointmentOut]


class DoctorSettings(BaseModel):
    auto_accept: bool


def own_booking(db: Session, appointment_id: int, user: User) -> AppointmentRow:
    """The booking, if it is WITH this doctor (admins may act on any)."""
    a = db.get(AppointmentRow, appointment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    if a.doctor_id != user.id and user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="This booking is with another doctor.")
    return a


@router.get("/api/doctor/appointments", response_model=list[DayOfAppointments])
def doctor_appointments(start: date | None = None, days: int = Query(14, ge=1, le=60),
                        include_closed: bool = True, doctor_id: int | None = None,
                        user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """
    A doctor's own bookings from `start` (default: today) for `days` days, one
    group per date, each day in slot order. include_closed=false hides
    rejected / cancelled / completed / no-show ones. An admin may pass doctor_id.
    """
    svc.sweep_no_shows(db)
    who = doctor_id if (user.role == Role.ADMIN and doctor_id) else user.id
    first = start or svc.now().date()
    query = select(AppointmentRow).where(AppointmentRow.doctor_id == who, AppointmentRow.date >= first,
                                         AppointmentRow.date < first + timedelta(days=days))
    if not include_closed:
        query = query.where(AppointmentRow.status.in_(ACTIVE_APPOINTMENT_STATUSES))
    groups: dict[date, list[AppointmentOut]] = {}
    for a in db.scalars(query.order_by(AppointmentRow.date, AppointmentRow.slot_start, AppointmentRow.priority.desc())):
        groups.setdefault(a.date, []).append(appointment_out(db, a))
    return [DayOfAppointments(date=d, appointments=items) for d, items in groups.items()]


@router.post("/api/appointments/{appointment_id}/accept", response_model=AppointmentOut)
def accept(appointment_id: int, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    a = own_booking(db, appointment_id, user)
    return appointment_out(db, run(lambda: svc.accept(db, a)))


@router.post("/api/appointments/{appointment_id}/reject", response_model=AppointmentOut)
def reject(appointment_id: int, data: RejectIn, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    a = own_booking(db, appointment_id, user)
    return appointment_out(db, run(lambda: svc.reject(db, a, data.reason)))


@router.get("/api/doctor/settings", response_model=DoctorSettings)
def my_settings(user: User = Depends(doctor_only)):
    return DoctorSettings(auto_accept=user.auto_accept)


@router.patch("/api/doctor/settings", response_model=DoctorSettings)
def change_settings(data: DoctorSettings, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """Off: new bookings wait as "requested" until you accept them. Bookings already made don't change."""
    doctor = run(lambda: svc.set_auto_accept(db, db.get(User, user.id), data.auto_accept))
    return DoctorSettings(auto_accept=doctor.auto_accept)


@router.post("/api/appointments/{appointment_id}/checkin", response_model=AppointmentOut)
def check_in(appointment_id: int, user: User = Depends(require_roles(Role.PATIENT, Role.DOCTOR)),
             db: Session = Depends(get_db)):
    """"I've arrived": the patient (their own booking) or the booking's doctor (admins: any)."""
    svc.sweep_no_shows(db)
    a = db.get(AppointmentRow, appointment_id)
    is_patient = a is not None and a.patient_id == user.id
    is_doctor = a is not None and (a.doctor_id == user.id or user.role == Role.ADMIN)
    if a is None or not (is_patient or is_doctor):
        raise HTTPException(status_code=404, detail="Booking not found")
    return appointment_out(db, run(lambda: svc.check_in(db, a, by_doctor=is_doctor)))


class WalkInIn(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=100, examples=["Ravi Kumar"])
    department_id: int
    reason: str = Field("", max_length=500, examples=["Chest pain since morning"])
    doctor_id: int | None = None        # admins only: which doctor will see them


@router.post("/api/doctor/walk-ins", response_model=AppointmentOut, status_code=201)
def add_walk_in(data: WalkInIn, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """
    The reception desk is gone, so the doctor adds walk-ins. The patient is
    checked in at once and their token is in the live queue.
    """
    doctor = db.get(User, data.doctor_id) if (user.role == Role.ADMIN and data.doctor_id) else db.get(User, user.id)
    if doctor is None:
        raise HTTPException(status_code=404, detail="Doctor not found")
    a = run(lambda: svc.add_walk_in(db, doctor=doctor, department_id=data.department_id,
                                    patient_name=data.patient_name, reason=data.reason))
    return appointment_out(db, a)
