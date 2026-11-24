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

from .database import SessionLocal
from .db_models import DepartmentRow, TokenRow
from .models import Department, DepartmentCreate, Token, TokenStatus


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
                last = db.scalar(select(func.max(TokenRow.seq)).where(TokenRow.department_id == dept.id))
                seq = (last or 0) + 1
                row = TokenRow(department_id=dept.id, seq=seq, number=f"{dept.code}-{seq:03d}",
                               patient_name=patient_name, status=TokenStatus.WAITING,
                               created_at=datetime.now())
                db.add(row)
                try:
                    db.commit()
                    return Token.model_validate(row)
                except IntegrityError:
                    # Two receptionists pressed "Give token" at the same moment and got
                    # the same number; the database's unique rule refused one. Try again.
                    db.rollback()
        raise RuntimeError("Could not create a token number, please try again")

    def get_token(self, token_id: int) -> Token | None:
        with SessionLocal() as db:
            row = db.get(TokenRow, token_id)
            return Token.model_validate(row) if row else None

    def tokens_in(self, dept_id: int, status: TokenStatus | None = None) -> list[Token]:
        """Tokens of one department, oldest first (First-Come-First-Served)."""
        with SessionLocal() as db:
            query = select(TokenRow).where(TokenRow.department_id == dept_id)
            if status is not None:
                query = query.where(TokenRow.status == status)
            return [Token.model_validate(r) for r in db.scalars(query.order_by(TokenRow.id))]

    def arrivals_since(self, dept_id: int, minutes: int) -> int:
        cutoff = datetime.now() - timedelta(minutes=minutes)
        with SessionLocal() as db:
            return db.scalar(select(func.count()).select_from(TokenRow).where(
                TokenRow.department_id == dept_id, TokenRow.created_at >= cutoff))

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
            db.commit()
            return Token.model_validate(row)

    def call_next(self, dept_id: int, room: int, when: datetime) -> Token | None:
        """
        1. the patient now in this room (if any) is DONE
        2. the oldest WAITING token moves into this room
        Returns that token, or None if nobody is waiting (step 1 still happens).
        """
        with SessionLocal() as db:
            for row in db.scalars(select(TokenRow).where(
                    TokenRow.department_id == dept_id, TokenRow.room == room,
                    TokenRow.status == TokenStatus.IN_CONSULTATION)):
                row.status, row.finished_at = TokenStatus.DONE, when
            nxt = db.scalars(select(TokenRow).where(
                TokenRow.department_id == dept_id, TokenRow.status == TokenStatus.WAITING)
                .order_by(TokenRow.id).limit(1)).first()
            if nxt is not None:
                nxt.status, nxt.room, nxt.called_at = TokenStatus.IN_CONSULTATION, room, when
            db.commit()
            return Token.model_validate(nxt) if nxt else None


# One shared store for the whole app.
store = DatabaseStore()
