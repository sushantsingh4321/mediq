"""
Module 2: Doctor schedule (weekly OPD sessions).

URLs:
    GET    /api/schedule              the weekly timetable (anyone; filter by department/doctor)
    GET    /api/schedule/on-duty      which doctors are in OPD right now (anyone)
    GET    /api/schedule/doctors      doctor names for the timetable form (anyone)
    POST   /api/schedule              ADMIN: add a session
    DELETE /api/schedule/{id}         ADMIN: remove a session

Link with the queue: main.py's call_next() calls check_on_duty(), so a doctor
can only call the next patient during their own session, in its department and room.

"Now" is hospital time (HOSPITAL_TIMEZONE, default Asia/Kolkata), not the
server's clock, which is often UTC on cloud servers.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..db_models import OpdSlot, Role, User
from ..deps import admin_only
from ..store import store

router = APIRouter(prefix="/api/schedule", tags=["doctor schedule"])

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------- models

class SlotCreate(BaseModel):
    doctor_id: int
    department_id: int
    weekday: int = Field(..., ge=0, le=6, description="0 = Monday ... 6 = Sunday")
    start_time: time = Field(..., examples=["09:00"])
    end_time: time = Field(..., examples=["13:00"])
    room: int = Field(..., ge=1)


class SlotOut(BaseModel):
    id: int
    doctor_id: int
    doctor_name: str
    department_id: int
    department_code: str
    department_name: str
    weekday: int
    weekday_name: str
    start_time: time
    end_time: time
    room: int


class OnDutyOut(BaseModel):
    hospital_time: datetime          # "now", in hospital time
    timezone: str
    on_duty: list[SlotOut]


class DoctorOut(BaseModel):
    """Public: only the name, never the email or phone."""
    id: int
    full_name: str


# ---------------------------------------------------------------- helpers

def now_local() -> datetime:
    """The current time at the hospital. Tests replace this to pick a moment."""
    return datetime.now(ZoneInfo(get_settings().hospital_timezone))


def to_out(slot: OpdSlot) -> SlotOut:
    dept = store.departments.get(slot.department_id)
    return SlotOut(
        id=slot.id, doctor_id=slot.doctor_id, doctor_name=slot.doctor.full_name,
        department_id=slot.department_id,
        department_code=dept.code if dept else "?", department_name=dept.name if dept else "Unknown",
        weekday=slot.weekday, weekday_name=WEEKDAYS[slot.weekday],
        start_time=slot.start_time, end_time=slot.end_time, room=slot.room,
    )


def overlaps(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    """09:00-13:00 and 12:00-15:00 overlap; 09:00-13:00 and 13:00-15:00 don't."""
    return a_start < b_end and b_start < a_end


def is_on(slot: OpdSlot, moment: datetime) -> bool:
    """Is this session happening at `moment`? (start included, end not)"""
    return slot.weekday == moment.weekday() and slot.start_time <= moment.time() < slot.end_time


def fmt(slot: OpdSlot) -> str:
    return f"{WEEKDAYS[slot.weekday]} {slot.start_time:%H:%M}-{slot.end_time:%H:%M}, Room {slot.room}"


def next_session(slots: list[OpdSlot], moment: datetime) -> OpdSlot | None:
    """The first session starting after `moment`, looking up to a week ahead."""
    def starts_in(slot: OpdSlot) -> timedelta:
        days = (slot.weekday - moment.weekday()) % 7
        start = datetime.combine(moment.date() + timedelta(days=days), slot.start_time, moment.tzinfo)
        return start - moment if start > moment else start + timedelta(days=7) - moment
    return min(slots, key=starts_in, default=None)


def check_on_duty(db: Session, doctor: User, department_id: int, room: int):
    """
    Used by call_next() in main.py. Raises 403 with a helpful message unless the
    doctor has a session RIGHT NOW in this department and this room.
    """
    moment = now_local()
    mine = db.scalars(select(OpdSlot).where(OpdSlot.doctor_id == doctor.id,
                                            OpdSlot.department_id == department_id)).all()
    current = [s for s in mine if is_on(s, moment)]
    if not current:
        dept = store.departments.get(department_id)
        dept_name = dept.name if dept else "this department"
        upcoming = next_session(mine, moment)
        hint = f" Your next session there: {fmt(upcoming)}." if upcoming else " You have no sessions there."
        raise HTTPException(status_code=403,
                            detail=f"You're not on OPD duty in {dept_name} right now "
                                   f"({moment:%A %H:%M} hospital time).{hint}")
    if all(s.room != room for s in current):
        raise HTTPException(status_code=403,
                            detail=f"You're on duty in Room {current[0].room} right now, not Room {room}.")


# ---------------------------------------------------------------- endpoints (anyone)

@router.get("", response_model=list[SlotOut])
def timetable(department_id: int | None = None, doctor_id: int | None = None,
              db: Session = Depends(get_db)):
    """The weekly timetable, sorted by day then start time. Filters are optional."""
    query = select(OpdSlot)
    if department_id is not None:
        query = query.where(OpdSlot.department_id == department_id)
    if doctor_id is not None:
        query = query.where(OpdSlot.doctor_id == doctor_id)
    query = query.order_by(OpdSlot.weekday, OpdSlot.start_time, OpdSlot.room)
    return [to_out(s) for s in db.scalars(query).all()]


@router.get("/on-duty", response_model=OnDutyOut)
def on_duty(department_id: int | None = None, db: Session = Depends(get_db)):
    """Doctors whose session is happening right now (hospital time)."""
    moment = now_local()
    query = select(OpdSlot).where(OpdSlot.weekday == moment.weekday())
    if department_id is not None:
        query = query.where(OpdSlot.department_id == department_id)
    current = [s for s in db.scalars(query).all() if is_on(s, moment)]
    current.sort(key=lambda s: (s.department_id, s.room))
    return OnDutyOut(hospital_time=moment, timezone=get_settings().hospital_timezone,
                     on_duty=[to_out(s) for s in current])


@router.get("/doctors", response_model=list[DoctorOut])
def doctors(db: Session = Depends(get_db)):
    """Doctor accounts (name only), for the timetable's "add session" form."""
    return db.scalars(select(User).where(User.role == Role.DOCTOR).order_by(User.full_name)).all()


# ---------------------------------------------------------------- endpoints (admin)

@router.post("", response_model=SlotOut, status_code=201, dependencies=[Depends(admin_only)])
def add_session(data: SlotCreate, db: Session = Depends(get_db)):
    doctor = db.get(User, data.doctor_id)
    if doctor is None or doctor.role != Role.DOCTOR:
        raise HTTPException(status_code=400, detail="Choose a doctor account (role: doctor).")
    dept = store.departments.get(data.department_id)
    if dept is None:
        raise HTTPException(status_code=404, detail=f"Department {data.department_id} not found")
    if not 1 <= data.room <= dept.doctors:
        raise HTTPException(status_code=400, detail=f"{dept.name} has rooms 1 to {dept.doctors}.")
    if data.start_time >= data.end_time:
        raise HTTPException(status_code=400, detail="The session must end after it starts (same day).")

    # Clashes: the same doctor can't be in two places, and two doctors can't share a room.
    same_day = db.scalars(select(OpdSlot).where(OpdSlot.weekday == data.weekday)).all()
    for s in same_day:
        if not overlaps(s.start_time, s.end_time, data.start_time, data.end_time):
            continue
        if s.doctor_id == data.doctor_id:
            raise HTTPException(status_code=409, detail=f"{doctor.full_name} already has a session then: {fmt(s)}.")
        if s.department_id == data.department_id and s.room == data.room:
            raise HTTPException(status_code=409,
                                detail=f"Room {s.room} in {dept.name} is already used then by {s.doctor.full_name}.")

    slot = OpdSlot(**data.model_dump())
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return to_out(slot)


@router.delete("/{slot_id}", status_code=204, dependencies=[Depends(admin_only)])
def remove_session(slot_id: int, db: Session = Depends(get_db)):
    slot = db.get(OpdSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(slot)
    db.commit()
