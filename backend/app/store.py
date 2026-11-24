"""
Where the OPD queue data lives.

Version 1 kept everything in Python memory (dicts and lists), so data was LOST
when the server restarted. Because all storage went through this one class, we
could swap it for a real database without changing the API code much: the
methods below have the same names as before, but now read and write the
`departments` and `tokens` tables (db_models.py).

Each method opens its own short database session (`with SessionLocal() as db`)
and gives back Pydantic models (Department, Token), just like before.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import SessionLocal
from .db_models import AppointmentRow, DepartmentRow, TokenRow
from .models import AppointmentStatus
from .models import Department, DepartmentCreate, Token, TokenStatus


# The queue order (Module 5): slot time (or, without a booking, the time the token
# was made), then higher priority first, then the token number.
# 10:20 booking, 10:20 booking with priority 1, 10:25 walk-in  ->  priority one, other 10:20, walk-in.
QUEUE_ORDER = (func.coalesce(TokenRow.scheduled_at, TokenRow.created_at), TokenRow.priority.desc(), TokenRow.id)

def queue_key(t: Token) -> tuple:
    """The same order as QUEUE_ORDER, for a token already loaded into Python."""
    return (t.scheduled_at or t.created_at, -t.priority, t.id)


def complete_appointments(db: Session, token_ids: list[int], when: datetime) -> None:
    """A token is DONE: the booking it came from (if any) is now "completed"."""
    for a in db.scalars(select(AppointmentRow).where(AppointmentRow.token_id.in_(token_ids),
                                                     AppointmentRow.status == AppointmentStatus.CHECKED_IN)):
        a.status, a.updated_at = AppointmentStatus.COMPLETED, when


# Tokens that are really in the building and in the queue (booked = not arrived yet)
LIVE_STATUSES = (TokenStatus.WAITING, TokenStatus.IN_CONSULTATION)


def new_token_row(db: Session, dept_id: int, dept_code: str, patient_name: str, *,
                  status: TokenStatus = TokenStatus.WAITING, scheduled_at: datetime | None = None,
                  priority: int = 0) -> TokenRow:
    """
    Add the department's next token (GEN-007) to an OPEN session, without saving.
    The caller commits, so a token and its appointment can be saved together.
    If two tokens get the same number at the same instant, the commit fails
    (unique rule on department + seq) and the caller simply tries again.
    """
    last = db.scalar(select(func.max(TokenRow.seq)).where(TokenRow.department_id == dept_id))
    seq = (last or 0) + 1
    row = TokenRow(department_id=dept_id, seq=seq, number=f"{dept_code}-{seq:03d}", patient_name=patient_name,
                   status=status, created_at=datetime.now(), scheduled_at=scheduled_at, priority=priority)
    db.add(row)
    return row


class DatabaseStore:
    # ----- departments -----
    @property
    def departments(self) -> dict[int, Department]:
        """All departments as {id: Department}, so old code like store.departments.get(1) still works."""
        with SessionLocal() as db:
            rows = db.scalars(select(DepartmentRow).order_by(DepartmentRow.id)).all()
            return {r.id: Department.model_validate(r) for r in rows}

    def add_department(self, data: DepartmentCreate) -> Department:
        with SessionLocal() as db:
            row = DepartmentRow(**data.model_dump())
            db.add(row)
            db.commit()
            return Department.model_validate(row)

    def update_department(self, dept_id: int, data: DepartmentCreate) -> Department:
        with SessionLocal() as db:
            row = db.get(DepartmentRow, dept_id)
            for field, value in data.model_dump().items():
                setattr(row, field, value)
            db.commit()
            return Department.model_validate(row)

    # ----- tokens -----
    def add_token(self, patient_name: str, dept: Department) -> Token:
        """Give the next number in this department: GEN-001, GEN-002..."""
        for _attempt in range(3):
            with SessionLocal() as db:
                row = new_token_row(db, dept.id, dept.code, patient_name)
                try:
                    db.commit()
                    return Token.model_validate(row)
                except IntegrityError:
                    # Two people pressed "Give token" at the same moment and got
                    # the same number; the database's unique rule refused one. Try again.
                    db.rollback()
        raise RuntimeError("Could not create a token number, please try again")

    def get_token(self, token_id: int) -> Token | None:
        with SessionLocal() as db:
            row = db.get(TokenRow, token_id)
            return Token.model_validate(row) if row else None

    def tokens_in(self, dept_id: int, status: TokenStatus | None = None) -> list[Token]:
        """Tokens of one department, in queue order (QUEUE_ORDER above)."""
        with SessionLocal() as db:
            query = select(TokenRow).where(TokenRow.department_id == dept_id)
            if status is not None:
                query = query.where(TokenRow.status == status)
            return [Token.model_validate(r) for r in db.scalars(query.order_by(*QUEUE_ORDER))]

    def arrivals_since(self, dept_id: int, minutes: int) -> int:
        cutoff = datetime.now() - timedelta(minutes=minutes)
        with SessionLocal() as db:
            # Booked tokens haven't "arrived" yet, and cancelled ones never will
            return db.scalar(select(func.count()).select_from(TokenRow).where(
                TokenRow.department_id == dept_id, TokenRow.created_at >= cutoff,
                TokenRow.status.not_in((TokenStatus.BOOKED, TokenStatus.CANCELLED))))

    def count_by_status(self) -> dict[TokenStatus, int]:
        """{WAITING: 4, IN_CONSULTATION: 2, DONE: 10} for the whole hospital (admin console)."""
        counts = {s: 0 for s in TokenStatus}
        with SessionLocal() as db:
            for status, n in db.execute(select(TokenRow.status, func.count()).group_by(TokenRow.status)):
                counts[status] = n
        return counts

    # ----- the doctor's buttons (each is ONE save, so it can't half-happen) -----
    def finish_room(self, dept_id: int, room: int, when: datetime) -> Token | None:
        """Mark the patient in this room as DONE. Returns them, or None if the room was empty."""
        with SessionLocal() as db:
            row = db.scalars(select(TokenRow).where(
                TokenRow.department_id == dept_id, TokenRow.room == room,
                TokenRow.status == TokenStatus.IN_CONSULTATION)).first()
            if row is None:
                return None
            row.status, row.finished_at = TokenStatus.DONE, when
            complete_appointments(db, [row.id], when)
            db.commit()
            return Token.model_validate(row)

    def call_next(self, dept_id: int, room: int, when: datetime) -> Token | None:
        """
        1. the patient now in this room (if any) is DONE
        2. the first WAITING token in queue order moves into this room
        Returns that token, or None if nobody is waiting (step 1 still happens).
        """
        with SessionLocal() as db:
            finished = []
            for row in db.scalars(select(TokenRow).where(
                    TokenRow.department_id == dept_id, TokenRow.room == room,
                    TokenRow.status == TokenStatus.IN_CONSULTATION)):
                row.status, row.finished_at = TokenStatus.DONE, when
                finished.append(row.id)
            complete_appointments(db, finished, when)
            nxt = db.scalars(select(TokenRow).where(
                TokenRow.department_id == dept_id, TokenRow.status == TokenStatus.WAITING)
                .order_by(*QUEUE_ORDER).limit(1)).first()
            if nxt is not None:
                nxt.status, nxt.room, nxt.called_at = TokenStatus.IN_CONSULTATION, room, when
            db.commit()
            return Token.model_validate(nxt) if nxt else None


# One shared store for the whole app.
store = DatabaseStore()
