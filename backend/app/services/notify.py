"""
Tell a patient that something happened to their booking.

    notify(db, appointment, "accepted")

does two things:
  1. saves a NotificationRow: the in-app banner on the patient's pages shows it
     until they press "Got it" (GET /api/notifications/me)
  2. passes the same text to the SMS hook (services/sms.py, a stub for now)

It doesn't commit: the caller saves it together with the change it describes,
so there's never a message about something that didn't happen.

Patients get a message for what OTHERS did (the doctor accepted, rejected or
called them; the system marked them missed) and a confirmation when they book.
Not for their own cancel or check-in: they just did that themselves.
"""

from sqlalchemy.orm import Session

from ..db_models import AppointmentRow, NotificationRow, User
from . import sms


def _when(a: AppointmentRow) -> str:
    return f"{a.date:%a %d %b}, {a.slot_start:%H:%M}"


MESSAGES = {
    "booked": lambda a: f"Booked: {a.doctor.full_name}, {_when(a)}. Your token is {a.token.number}. "
                        "On the day, press \"I've arrived\" when you reach the hospital.",
    "requested": lambda a: f"Booking request sent to {a.doctor.full_name} for {_when(a)}. "
                           "You'll see here when the doctor answers.",
    "accepted": lambda a: f"{a.doctor.full_name} accepted your booking for {_when(a)}. Your token is {a.token.number}.",
    "rejected": lambda a: f"{a.doctor.full_name} couldn't accept your booking for {_when(a)}. "
                          f"Reason: {a.reject_reason}",
    "called": lambda a: f"It's your turn: please go to Room {a.token.room} now ({a.token.number}).",
    "no_show": lambda a: f"You didn't check in for {_when(a)} with {a.doctor.full_name}, so the booking was "
                         "marked as missed. Please book again if you still need to be seen.",
}


def notify(db: Session, a: AppointmentRow, event: str) -> NotificationRow | None:
    if a.patient_id is None:                 # a walk-in without an account: nobody to tell in the app
        return None
    text = MESSAGES[event](a)
    note = NotificationRow(user_id=a.patient_id, appointment_id=a.id, event=event, message=text,
                           created_at=a.updated_at)
    db.add(note)
    patient = db.get(User, a.patient_id)
    sms.send_sms(patient.phone if patient else None, text)
    return note
