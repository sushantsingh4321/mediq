"""
Patient self-booking (Module 5): the rules. The URLs are in routers/appointments.py.

  Slots      A doctor's OPD session (Module 2, e.g. Monday 09:00-13:00) is cut
             into 10-minute slots: 09:00, 09:10, ... 12:50. A slot is FREE if no
             active booking holds it and it hasn't started yet.
  Booking    a patient takes one free slot. Only one active booking per patient,
             per doctor, per day. auto_accept on -> "accepted", off -> "requested".
  Token      an accepted booking gets a queue token straight away (GEN-012),
             status "booked": not in the live queue until the patient arrives.
             It is queued by slot time, then priority (store.QUEUE_ORDER).
  Accept     (auto_accept off) the doctor accepts a "requested" booking -> token.
  Reject     the doctor says no, with a reason; the token is cancelled.
  Cancel     the patient may cancel a requested/accepted booking up to 1 hour
             before the slot starts; the token is cancelled.
  Check-in   "I've arrived": from 1 hour before the slot until 15 minutes after
             it (the doctor may check a patient in any time that day). The token
             goes from "booked" into the live queue ("waiting").
  No-show    an accepted booking not checked in by 15 minutes after its slot
             becomes "no_show" and its token is cancelled (sweep_no_shows).
  Completed  when the doctor finishes the patient (Call next / Finish),
             store.complete_appointments marks the booking "completed".
  Walk-in    the doctor adds someone who just turned up (no reception desk any
             more): a booking that is already checked in, with its token
             straight in the live queue, queued by arrival time.

"Now" is hospital time from routers/schedule.py (now_local), the same clock the
OPD duty check uses, so tests can set the time in one place.

Errors are BookingError with a message saying what went wrong and what to do;
the router turns them into 400 (or 409 for "someone was faster").
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db_models import AppointmentRow, DepartmentRow, OpdSlot, Role, TokenRow, User
from ..models import ACTIVE_APPOINTMENT_STATUSES, AppointmentSource, AppointmentStatus, TokenStatus
from ..routers import schedule
from ..store import new_token_row
from .notify import notify

SLOT_MINUTES = 10               # default slot length
BOOK_AHEAD_DAYS = 30            # how far ahead patients may book
CANCEL_BEFORE = timedelta(hours=1)
CHECK_IN_EARLY = timedelta(hours=1)        # "I've arrived" opens 1 hour before the slot
NO_SHOW_AFTER = timedelta(minutes=15)      # ...and closes 15 minutes after it


class BookingError(Exception):
    """A booking rule said no. str(error) is a message a person can act on."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def now() -> datetime:
    """Hospital time without the timezone attached (how the tables store it)."""
    return schedule.now_local().replace(tzinfo=None)


# ---------------------------------------------------------------- slots

@dataclass
class Slot:
    start: time
    end: time
    room: int
    department_id: int
    free: bool
    why_not: str = ""            # "booked", "past"


def sessions_on(db: Session, doctor_id: int, day: date, department_id: int | None = None) -> list[OpdSlot]:
    """The doctor's OPD sessions on that weekday (optionally in one department), earliest first."""
    query = select(OpdSlot).where(OpdSlot.doctor_id == doctor_id, OpdSlot.weekday == day.weekday())
    if department_id is not None:
        query = query.where(OpdSlot.department_id == department_id)
    return list(db.scalars(query.order_by(OpdSlot.start_time)))


def cut_into_slots(start: time, end: time, minutes: int = SLOT_MINUTES) -> list[tuple[time, time]]:
    """09:00-09:35 -> [(09:00, 09:10), (09:10, 09:20), (09:20, 09:30)]: a slot never runs past the end."""
    out, day = [], date(2000, 1, 1)                       # any date: we only need the clock maths
    t, finish = datetime.combine(day, start), datetime.combine(day, end)
    step = timedelta(minutes=minutes)
    while t + step <= finish:
        out.append((t.time(), (t + step).time()))
        t += step
    return out


def taken_starts(db: Session, doctor_id: int, day: date) -> set[time]:
    """Start times already held by an active booking with this doctor that day."""
    return set(db.scalars(select(AppointmentRow.slot_start).where(
        AppointmentRow.doctor_id == doctor_id, AppointmentRow.date == day,
        AppointmentRow.status.in_(ACTIVE_APPOINTMENT_STATUSES))))


def check_bookable_day(day: date) -> None:
    today = now().date()
    if day < today:
        raise BookingError("That date has already passed. Pick today or a later day.")
    if day > today + timedelta(days=BOOK_AHEAD_DAYS):
        raise BookingError(f"You can book up to {BOOK_AHEAD_DAYS} days ahead. Pick an earlier date.")


def slots_for(db: Session, doctor_id: int, day: date, department_id: int | None = None) -> list[Slot]:
    """Every slot of the doctor's sessions that day, each marked free or not."""
    check_bookable_day(day)
    taken, moment = taken_starts(db, doctor_id, day), now()
    out = []
    for session in sessions_on(db, doctor_id, day, department_id):
        for start, end in cut_into_slots(session.start_time, session.end_time):
            if datetime.combine(day, start) <= moment:
                why = "past"
            elif start in taken:
                why = "booked"
            else:
                why = ""
            out.append(Slot(start, end, session.room, session.department_id, free=not why, why_not=why))
    return out


# ---------------------------------------------------------------- booking

def get_doctor(db: Session, doctor_id: int) -> User:
    doctor = db.get(User, doctor_id)
    if doctor is None or doctor.role != Role.DOCTOR:
        raise BookingError("That doctor wasn't found. Choose a doctor from the list.", 404)
    return doctor


def book(db: Session, *, patient: User, doctor_id: int, department_id: int, day: date,
         slot_start: time, reason: str) -> AppointmentRow:
    """A patient books one free slot. Returns the saved booking (accepted or requested)."""
    doctor = get_doctor(db, doctor_id)
    reason = reason.strip()
    if len(reason) < 3:
        raise BookingError("Tell the doctor briefly why you're coming, for example \"fever for 3 days\".")
    if db.get(DepartmentRow, department_id) is None:
        raise BookingError("That department wasn't found.", 404)

    slot = next((s for s in slots_for(db, doctor_id, day, department_id) if s.start == slot_start), None)
    if slot is None:
        raise BookingError(f"{doctor.full_name} has no {slot_start:%H:%M} slot in this department on "
                           f"{day:%a %d %b}. Pick one of the times shown.")
    if slot.why_not == "past":
        raise BookingError("That time has already started. Pick a later slot.")
    if slot.why_not == "booked":
        raise BookingError("Sorry, someone has just booked that slot. Pick another time.", 409)

    already = db.scalar(select(AppointmentRow).where(
        AppointmentRow.patient_id == patient.id, AppointmentRow.doctor_id == doctor_id,
        AppointmentRow.date == day, AppointmentRow.status.in_(ACTIVE_APPOINTMENT_STATUSES)))
    if already is not None:
        raise BookingError(f"You already have a booking with {doctor.full_name} on {day:%a %d %b} at "
                           f"{already.slot_start:%H:%M}. Cancel it first to choose another time.", 409)

    accepted = doctor.auto_accept

    def build() -> AppointmentRow:
        moment = now()
        a = AppointmentRow(
            patient_id=patient.id, patient_name=patient.full_name, doctor_id=doctor_id,
            department_id=department_id, date=day, slot_start=slot.start, slot_end=slot.end, reason=reason,
            status=AppointmentStatus.ACCEPTED if accepted else AppointmentStatus.REQUESTED,
            source=AppointmentSource.ONLINE, created_at=moment, updated_at=moment)
        db.add(a)
        if accepted:
            give_token(db, a)
        db.flush()                    # ids for the token and the message
        notify(db, a, "booked" if accepted else "requested")
        return a

    def explain_clash() -> None:
        # The database refused the save. Was it our slot rules (LEARN.md 18.2)?
        if slot_start in taken_starts(db, doctor_id, day):
            raise BookingError("Sorry, someone has just booked that slot. Pick another time.", 409)
        if has_active_booking(db, patient.id, doctor_id, day):
            raise BookingError("You already have a booking with this doctor that day.", 409)

    return save_with_retry(db, build, explain_clash)


def has_active_booking(db: Session, patient_id: int, doctor_id: int, day: date) -> bool:
    return db.scalar(select(AppointmentRow.id).where(
        AppointmentRow.patient_id == patient_id, AppointmentRow.doctor_id == doctor_id,
        AppointmentRow.date == day, AppointmentRow.status.in_(ACTIVE_APPOINTMENT_STATUSES))) is not None


def save_with_retry(db: Session, build, explain_clash=lambda: None, attempts: int = 3):
    """
    build() adds rows to the session; then we commit. If the database refuses
    (IntegrityError), either a real rule was broken (explain_clash raises a
    BookingError) or two tokens got the same number at the same instant; then
    we simply build and try again.
    """
    for _ in range(attempts):
        try:
            # build() may already talk to the database (db.flush() to get ids), so
            # the refusal can come from build() OR from commit(): catch both.
            result = build()
            db.commit()
            return result
        except IntegrityError:
            db.rollback()
            explain_clash()
    raise BookingError("The hospital system is busy. Please try again in a moment.", 503)


# ---------------------------------------------------------------- tokens

def give_token(db: Session, a: AppointmentRow) -> TokenRow:
    """
    Make the queue token for an accepted booking, in the same save as the booking.
    "booked" = the patient isn't here yet, so it is NOT in the live queue (step 5:
    "I've arrived" moves it in). Queued by slot time, then priority.
    """
    dept = db.get(DepartmentRow, a.department_id)
    token = new_token_row(db, dept.id, dept.code, a.patient_name, status=TokenStatus.BOOKED,
                          scheduled_at=starts_at(a), priority=a.priority)
    a.token = token
    return token


def cancel_token(a: AppointmentRow) -> None:
    """The booking is off: its token leaves the queue for good (unless the patient is already being seen)."""
    if a.token is not None and a.token.status in (TokenStatus.BOOKED, TokenStatus.WAITING):
        a.token.status = TokenStatus.CANCELLED


# ---------------------------------------------------------------- the doctor's answers

def accept(db: Session, a: AppointmentRow) -> AppointmentRow:
    """auto_accept off: the doctor accepts a waiting request -> accepted + token."""
    if a.status != AppointmentStatus.REQUESTED:
        raise BookingError(f"This booking is already {a.status.value.replace('_', ' ')}.", 409)
    if starts_at(a) <= now():
        raise BookingError("This booking's time has already passed, so it can't be accepted now.", 409)

    def build():
        a.status, a.updated_at = AppointmentStatus.ACCEPTED, now()
        give_token(db, a)
        db.flush()
        notify(db, a, "accepted")
        return a

    return save_with_retry(db, build)


def reject(db: Session, a: AppointmentRow, reason: str) -> AppointmentRow:
    """The doctor says no, with a reason the patient will see. The token is cancelled."""
    reason = reason.strip()
    if len(reason) < 3:
        raise BookingError("Write a short reason for the patient, for example \"On leave that day\".")
    if a.status not in (AppointmentStatus.REQUESTED, AppointmentStatus.ACCEPTED):
        raise BookingError(f"This booking is {a.status.value.replace('_', ' ')}, so it can't be rejected.", 409)
    a.status, a.reject_reason, a.updated_at = AppointmentStatus.REJECTED, reason, now()
    cancel_token(a)
    notify(db, a, "rejected")
    db.commit()
    return a


def set_auto_accept(db: Session, doctor: User, on: bool) -> User:
    if doctor.role != Role.DOCTOR:
        raise BookingError("Only doctors have this setting.", 403)
    doctor.auto_accept = on
    db.commit()
    return doctor


# ---------------------------------------------------------------- cancelling

def starts_at(a: AppointmentRow) -> datetime:
    return datetime.combine(a.date, a.slot_start)


def cancel_closes_at(a: AppointmentRow) -> datetime:
    return starts_at(a) - CANCEL_BEFORE


def can_cancel(a: AppointmentRow) -> bool:
    return (a.status in (AppointmentStatus.REQUESTED, AppointmentStatus.ACCEPTED)
            and now() <= cancel_closes_at(a))


def cancel(db: Session, a: AppointmentRow) -> AppointmentRow:
    if a.status not in (AppointmentStatus.REQUESTED, AppointmentStatus.ACCEPTED):
        raise BookingError(f"This booking is {a.status.value.replace('_', ' ')}, so it can't be cancelled.", 409)
    if now() > cancel_closes_at(a):
        raise BookingError(f"Bookings can be cancelled up to 1 hour before. This one starts at "
                           f"{a.slot_start:%H:%M}, so cancelling closed at {cancel_closes_at(a):%H:%M}. "
                           "Please call the hospital instead.", 409)
    a.status, a.updated_at = AppointmentStatus.CANCELLED, now()
    cancel_token(a)
    db.commit()
    return a


# ---------------------------------------------------------------- arriving

def check_in_opens_at(a: AppointmentRow) -> datetime:
    return starts_at(a) - CHECK_IN_EARLY


def missed_after(a: AppointmentRow) -> datetime:
    return starts_at(a) + NO_SHOW_AFTER


def can_check_in(a: AppointmentRow) -> bool:
    """Can the PATIENT press "I've arrived" right now?"""
    return a.status == AppointmentStatus.ACCEPTED and check_in_opens_at(a) <= now() <= missed_after(a)


def check_in(db: Session, a: AppointmentRow, by_doctor: bool) -> AppointmentRow:
    """
    The patient is at the hospital: booking -> checked_in, token -> waiting (in the live queue).
    Patients: from 1 hour before to 15 minutes after the slot.
    Doctors: any time on the day, and they may also check in someone marked no-show
    (the patient turned up late and the doctor will still see them).
    """
    moment = now()
    allowed = (AppointmentStatus.ACCEPTED, AppointmentStatus.NO_SHOW) if by_doctor else (AppointmentStatus.ACCEPTED,)
    if a.status not in allowed:
        if a.status == AppointmentStatus.CHECKED_IN:
            raise BookingError("Already checked in. Please wait to be called.", 409)
        if a.status == AppointmentStatus.NO_SHOW:
            raise BookingError("This booking was marked as missed: check-in closed 15 minutes after the "
                               "appointment time. Please speak to the doctor's assistant or book again.", 409)
        raise BookingError(f"This booking is {a.status.value.replace('_', ' ')}, so it can't be checked in.", 409)
    if a.date != moment.date():
        raise BookingError(f"Check-in is only on the day of the appointment ({a.date:%a %d %b}).", 409)
    if not by_doctor and moment < check_in_opens_at(a):
        raise BookingError(f"Check-in opens at {check_in_opens_at(a):%H:%M}, 1 hour before your appointment. "
                           "Press \"I've arrived\" when you are at the hospital.", 409)
    if not by_doctor and moment > missed_after(a):
        raise BookingError("Check-in closed 15 minutes after your appointment time. "
                           "Please speak to the doctor's assistant or book again.", 409)
    if a.token is None:                       # shouldn't happen for an accepted booking, but be safe
        give_token(db, a)
    a.status, a.checked_in_at, a.updated_at = AppointmentStatus.CHECKED_IN, moment, moment
    a.token.status = TokenStatus.WAITING
    db.commit()
    return a


def sweep_no_shows(db: Session) -> int:
    """
    Mark accepted bookings whose check-in window has closed as "no_show" and
    cancel their tokens. There is no background timer: this runs whenever
    someone looks (my appointments, the doctor's list, check-in, Call next),
    which gives the same result. Returns how many were marked.
    """
    moment = now()
    late = [a for a in db.scalars(select(AppointmentRow).where(
                AppointmentRow.status == AppointmentStatus.ACCEPTED, AppointmentRow.date <= moment.date()))
            if missed_after(a) < moment]
    for a in late:
        a.status, a.updated_at = AppointmentStatus.NO_SHOW, moment
        cancel_token(a)
        notify(db, a, "no_show")
    if late:
        db.commit()
    return len(late)


# ---------------------------------------------------------------- walk-ins

def add_walk_in(db: Session, *, doctor: User, department_id: int, patient_name: str,
                reason: str = "") -> AppointmentRow:
    """
    Someone turned up without a booking and the doctor will see them.
    They are HERE, so the booking starts "checked_in" and the token "waiting"
    (in the live queue at once). Their "slot" is the moment they arrived, so
    they queue after earlier booked slots and before later ones.
    """
    if doctor.role != Role.DOCTOR:
        raise BookingError("Walk-ins are added for a doctor. Log in as the doctor who will see the patient.", 403)
    name = patient_name.strip()
    if not name:
        raise BookingError("Enter the patient's name.")
    dept = db.get(DepartmentRow, department_id)
    if dept is None:
        raise BookingError("That department wasn't found.", 404)
    works_there = db.scalar(select(OpdSlot.id).where(OpdSlot.doctor_id == doctor.id,
                                                     OpdSlot.department_id == department_id).limit(1))
    if works_there is None:
        raise BookingError(f"You have no OPD sessions in {dept.name}. Pick the department you work in.")

    moment = now()
    taken = taken_starts(db, doctor.id, moment.date())
    start = datetime.combine(moment.date(), moment.time())
    while start.time() in taken:               # a booking (or walk-in) at this exact instant: 1 µs later
        start += timedelta(microseconds=1)
    end = min(start + timedelta(minutes=SLOT_MINUTES), datetime.combine(moment.date(), time.max))

    def build() -> AppointmentRow:
        a = AppointmentRow(patient_id=None, patient_name=name, doctor_id=doctor.id, department_id=department_id,
                           date=moment.date(), slot_start=start.time(), slot_end=end.time(),
                           reason=reason.strip() or "Walk-in", status=AppointmentStatus.CHECKED_IN,
                           source=AppointmentSource.WALK_IN, checked_in_at=moment, created_at=moment,
                           updated_at=moment)
        db.add(a)
        token = give_token(db, a)
        token.status = TokenStatus.WAITING     # already here: straight into the live queue
        return a

    return save_with_retry(db, build)
