"""
Admin console: one place to see how the whole hospital is doing.

URLs (ADMIN ONLY):
    GET /api/admin/overview    counts from every module in one answer
    GET /api/admin/activity    today's arrivals by hour, real waits, bookings ahead (the dashboard charts)

The console page (frontend/admin.html) also uses the admin endpoints that
already exist: accounts (/api/auth/users), enquiries (/api/enquiries) and
call-backs (/api/callback).
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..db_models import AppointmentRow, Role, TokenRow, User
from ..deps import admin_only
from ..models import ACTIVE_APPOINTMENT_STATUSES, TokenStatus
from ..store import store
from . import ambulance, beds, callback, schedule, website

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_only)])


class QueueCounts(BaseModel):
    waiting: int
    in_consultation: int
    done: int


class BedCounts(BaseModel):
    total: int
    occupied: int
    free: int


class Overview(BaseModel):
    generated_at: datetime
    queue: QueueCounts
    beds: BedCounts
    doctors_on_duty: int
    ambulances: ambulance.Availability   # available / on_trip / maintenance
    open_trips: int                      # requested + assigned
    callbacks: dict[str, int]       # {"pending": 0, "calling": 1, "done": 4, "failed": 0}
    enquiries_total: int
    enquiries_today: int
    accounts: dict[str, int]        # {"patient": 12, "doctor": 3, "pharmacist": 1, "admin": 1}


@router.get("/overview", response_model=Overview)
def overview(db: Session = Depends(get_db)):
    """Counts only (no names), gathered from every module."""
    # OPD queue (store.py)
    by_status = store.count_by_status()
    queue = QueueCounts(
        waiting=by_status[TokenStatus.WAITING],
        in_consultation=by_status[TokenStatus.IN_CONSULTATION],
        done=by_status[TokenStatus.DONE],
    )

    # Beds (Module 1)
    total, occupied, free = beds.bed_totals()

    # Doctors on duty now (Module 2, database)
    on_duty = schedule.on_duty(department_id=None, db=db).on_duty

    # Call-backs and enquiries
    enquiries_total, enquiries_today = website.enquiry_counts()

    # Accounts per role (database): SELECT role, COUNT(*) FROM users GROUP BY role
    per_role = {r.value: 0 for r in Role}
    for role, n in db.execute(select(User.role, func.count()).group_by(User.role)):
        per_role[role.value] = n

    return Overview(
        generated_at=datetime.now(),
        queue=queue,
        beds=BedCounts(total=total, occupied=occupied, free=free),
        doctors_on_duty=len(on_duty),
        ambulances=ambulance.counts(db),
        open_trips=db.scalar(select(func.count()).select_from(ambulance.TripRow)
                             .where(ambulance.TripRow.status.in_(ambulance.OPEN))),
        callbacks=callback.callback_counts(),
        enquiries_total=enquiries_total,
        enquiries_today=enquiries_today,
        accounts=per_role,
    )


# ---------------------------------------------------------------------------
# Activity: the dashboard's charts. Real rows only, nothing estimated.
# ---------------------------------------------------------------------------
# Times in the tokens table are the SERVER's clock (datetime.now()). The server may
# run in UTC (Vercel) while the hospital is in Asia/Kolkata, so we convert:
#   server time -> hospital time  with  .astimezone(hospital zone)

class HourCount(BaseModel):
    hour: int          # 0-23, hospital time
    arrivals: int


class DepartmentWait(BaseModel):
    department: str
    seen: int                         # patients called to a doctor today
    avg_wait_minutes: float | None    # arrival -> called; None if nobody was seen yet


class DayCount(BaseModel):
    date: date
    bookings: int


class Activity(BaseModel):
    generated_at: datetime
    arrivals_by_hour: list[HourCount]       # all 24 hours of today
    waits_today: list[DepartmentWait]       # one per department
    bookings_next_7_days: list[DayCount]    # today and the 6 days after


def hospital_zone() -> ZoneInfo:
    return ZoneInfo(get_settings().hospital_timezone)


def hospital_midnight_in_server_time() -> datetime:
    """Midnight today at the hospital, written the way the server stores times."""
    now_h = datetime.now(hospital_zone())
    midnight = now_h.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone().replace(tzinfo=None)    # .astimezone() with no zone = the server's zone


@router.get("/activity", response_model=Activity)
def activity(db: Session = Depends(get_db)):
    zone = hospital_zone()
    start = hospital_midnight_in_server_time()

    # A patient "arrives" when their token joins the queue: a walk-in's token is made
    # on arrival; a booked patient's token is made earlier, so use their check-in time.
    rows = db.execute(
        select(TokenRow, AppointmentRow.checked_in_at)
        .outerjoin(AppointmentRow, AppointmentRow.token_id == TokenRow.id)
        .where(TokenRow.status.not_in((TokenStatus.BOOKED, TokenStatus.CANCELLED)),
               or_(TokenRow.created_at >= start, AppointmentRow.checked_in_at >= start))
    ).all()

    per_hour = [0] * 24
    waits: dict[int, list[float]] = {}
    for token, checked_in_at in rows:
        arrived = checked_in_at or token.created_at
        if arrived < start:
            continue
        per_hour[arrived.astimezone(zone).hour] += 1
        if token.called_at is not None:
            minutes = max(0.0, (token.called_at - arrived).total_seconds() / 60)
            waits.setdefault(token.department_id, []).append(minutes)

    waits_today = []
    for dept_id, dept in store.departments.items():
        got = waits.get(dept_id, [])
        waits_today.append(DepartmentWait(department=dept.name, seen=len(got),
                                          avg_wait_minutes=round(sum(got) / len(got), 1) if got else None))

    # Active bookings for the next 7 days (appointment dates are already hospital dates)
    today = datetime.now(zone).date()
    last = today + timedelta(days=6)
    counts = dict(db.execute(
        select(AppointmentRow.date, func.count())
        .where(AppointmentRow.date >= today, AppointmentRow.date <= last,
               AppointmentRow.status.in_(ACTIVE_APPOINTMENT_STATUSES))
        .group_by(AppointmentRow.date)).all())

    return Activity(
        generated_at=datetime.now(),
        arrivals_by_hour=[HourCount(hour=h, arrivals=n) for h, n in enumerate(per_hour)],
        waits_today=waits_today,
        bookings_next_7_days=[DayCount(date=today + timedelta(days=i), bookings=counts.get(today + timedelta(days=i), 0))
                              for i in range(7)],
    )
