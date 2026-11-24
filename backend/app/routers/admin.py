"""
Admin console: one place to see how the whole hospital is doing.

URLs (ADMIN ONLY):
    GET /api/admin/overview    counts from every module in one answer

The console page (frontend/admin.html) also uses the admin endpoints that
already exist: accounts (/api/auth/users), enquiries (/api/enquiries) and
call-backs (/api/callback).
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..db_models import Role, User
from ..deps import admin_only
from ..models import TokenStatus
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
