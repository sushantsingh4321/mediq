"""
In-app messages (Module 5, step 6). The banner on the patient pages uses these.

    GET  /api/notifications/me?unread_only=true   my messages, newest first
    POST /api/notifications/{id}/read             "Got it": hide this one
    POST /api/notifications/read-all              hide them all

Any logged-in user, but only ever their OWN messages.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..db_models import NotificationRow, User
from ..deps import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    appointment_id: int | None
    event: str
    message: str
    created_at: datetime
    read_at: datetime | None


@router.get("/me", response_model=list[NotificationOut])
def my_notifications(unread_only: bool = True, limit: int = Query(20, ge=1, le=100),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(NotificationRow).where(NotificationRow.user_id == user.id)
    if unread_only:
        query = query.where(NotificationRow.read_at.is_(None))
    return db.scalars(query.order_by(NotificationRow.id.desc()).limit(limit)).all()


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    note = db.get(NotificationRow, notification_id)
    if note is None or note.user_id != user.id:          # someone else's: "not found"
        raise HTTPException(status_code=404, detail="Message not found")
    note.read_at = note.read_at or datetime.now()
    db.commit()
    return note


@router.post("/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = db.execute(update(NotificationRow).where(NotificationRow.user_id == user.id,
                                                      NotificationRow.read_at.is_(None))
                        .values(read_at=datetime.now()))
    db.commit()
    return {"marked_read": result.rowcount}
