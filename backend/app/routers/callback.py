"""
"Request Call Back": a patient leaves a number, the hospital desk is rung
first and then connected to the patient.

URLs:
    POST /api/callback                    patient asks for a call back
    GET  /api/callback                    staff list of all requests

    Webhooks: TWILIO calls these, not people (see services/telephony.py):
    POST /api/callback/{id}/twiml         desk answered: what should Twilio do now?
    POST /api/callback/{id}/dial-status   result of ringing the patient
    POST /api/callback/{id}/status        the desk call has ended

Status of a request:
    pending  saved, call not started yet
    calling  the desk is being rung / connected
    done     the patient was connected to the desk
    failed   something went wrong (see the note)
"""

import math
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal, get_db
from ..db_models import CallbackRow
from ..deps import admin_only
from ..models import CallbackStatus   # pending / calling / done / failed (moved to models.py)
from ..services.telephony import TelephonyError, get_provider

router = APIRouter(prefix="/api/callback", tags=["call back"])

RATE_LIMIT = timedelta(minutes=10)   # one request per phone number per 10 minutes


# ---------------------------------------------------------------- models

class CallbackCreate(BaseModel):
    """What the call-back form sends."""
    name: str = Field(..., min_length=1, max_length=100, examples=["Asha Patel"])
    mobile: str = Field(..., max_length=20, examples=["98765 43210"],
                        description="Indian mobile: 10 digits, +91 or 0 in front is fine")
    consent: bool = Field(..., description="Patient agreed to be called on this number")


class CallbackRequest(BaseModel):
    """A call-back request as stored by the server (staff can see all of this)."""
    model_config = ConfigDict(from_attributes=True)   # can be built from a CallbackRow

    id: int
    name: str
    mobile: str                     # always +91XXXXXXXXXX
    status: CallbackStatus
    note: str = ""                  # human-readable detail, e.g. "Patient did not answer"
    call_sid: str | None = None     # Twilio's id for the call
    dry_run: bool                   # True = nobody was actually dialled
    created_at: datetime
    updated_at: datetime


class CallbackReceipt(BaseModel):
    """What the PATIENT gets back: only their own request, nothing about anyone else."""
    id: int
    mobile: str
    status: CallbackStatus
    message: str


# ---------------------------------------------------------------- storage
# Saved in the database table "callback_requests" (CallbackRow in db_models.py).

def callback_counts() -> dict[str, int]:
    """{"pending": 0, "calling": 1, "done": 4, "failed": 0} for the admin console."""
    counts = {s.value: 0 for s in CallbackStatus}
    with SessionLocal() as db:
        for status, n in db.execute(select(CallbackRow.status, func.count()).group_by(CallbackRow.status)):
            counts[status.value] = n
    return counts


# ---------------------------------------------------------------- helpers

def normalize_indian_mobile(raw: str) -> str | None:
    """
    Turn what people type into +91XXXXXXXXXX, or None if it isn't an Indian mobile.

        "98765 43210"      -> "+919876543210"
        "+91 98765-43210"  -> "+919876543210"
        "09876543210"      -> "+919876543210"
        "12345"            -> None
    Indian mobile numbers have 10 digits and start with 6, 7, 8 or 9.
    """
    digits = re.sub(r"\D", "", raw)                 # keep only 0-9
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]                         # "91" country code typed
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]                         # leading 0 typed
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return None


def set_status(cb: CallbackRow, status: CallbackStatus, note: str = ""):
    """Change the status (the caller still has to db.commit() to save it)."""
    cb.status = status
    cb.updated_at = datetime.now()
    if note:
        cb.note = note


def get_callback_or_404(db: Session, callback_id: int) -> CallbackRow:
    cb = db.get(CallbackRow, callback_id)
    if cb is None:
        raise HTTPException(status_code=404, detail="Call-back request not found")
    return cb


async def read_webhook(request: Request) -> dict:
    """
    Read the form data Twilio sent, and refuse it (403) if the signature is wrong.
    Twilio signs the PUBLIC address it called, so we rebuild that address from
    PUBLIC_BASE_URL (our server may see a different one behind ngrok).
    """
    params = dict(await request.form())
    url = get_settings().public_base_url + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    if not get_provider().is_valid_webhook(url, params, request.headers.get("X-Twilio-Signature")):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    return params


def twiml(xml: str) -> Response:
    """Send TwiML back to Twilio (it's XML, not JSON)."""
    return Response(content=xml, media_type="application/xml")


# ---------------------------------------------------------------- endpoints for people

@router.post("", response_model=CallbackReceipt, status_code=201)
def request_callback(data: CallbackCreate, db: Session = Depends(get_db)):
    # 1. Check the input
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Please enter your name")
    if not data.consent:
        raise HTTPException(status_code=400, detail="Please tick the box so we may call you")
    mobile = normalize_indian_mobile(data.mobile)
    if mobile is None:
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit Indian mobile number")

    # 2. Rate limit: one request per number every 10 minutes.
    #    Stops double-clicks, and stops someone using us to ring a stranger again and again.
    now = datetime.now()
    latest = db.scalar(select(func.max(CallbackRow.created_at)).where(
        CallbackRow.mobile == mobile, CallbackRow.created_at > now - RATE_LIMIT))
    if latest is not None:
        wait = RATE_LIMIT - (now - latest)
        minutes = math.ceil(wait.total_seconds() / 60)
        # 429 Too Many Requests; Retry-After tells programs how many seconds to wait
        raise HTTPException(
            status_code=429,
            detail=f"We already have a call-back request for this number. Please try again in {minutes} min.",
            headers={"Retry-After": str(int(wait.total_seconds()))},
        )

    # 3. Save it as "pending"
    settings = get_settings()
    cb = CallbackRow(name=name, mobile=mobile, status=CallbackStatus.PENDING, note="",
                     dry_run=settings.dry_run, created_at=now, updated_at=now)
    db.add(cb)
    db.commit()            # saved before we phone anyone, so it gets its id

    # 4. Start the call. If that fails the request is still saved, so staff can
    #    see it on the staff page and call the patient by hand.
    try:
        cb.call_sid = get_provider().start_bridge_call(cb.id)
        set_status(cb, CallbackStatus.CALLING,
                   "DRY RUN: call logged, nobody was dialled" if settings.dry_run
                   else "Ringing the hospital desk")
        message = "Thank you. Our team is calling you shortly."
    except TelephonyError as e:
        set_status(cb, CallbackStatus.FAILED, str(e))
        message = "Thank you. We couldn't start the call automatically, but our team has your request and will call you."
    db.commit()

    return CallbackReceipt(id=cb.id, mobile=cb.mobile, status=cb.status, message=message)


@router.get("", response_model=list[CallbackRequest], dependencies=[Depends(admin_only)])
def list_callbacks(db: Session = Depends(get_db)):
    """Staff list, newest first. Contains names and numbers: never share it publicly."""
    return db.scalars(select(CallbackRow).order_by(CallbackRow.id.desc())).all()


# ---------------------------------------------------------------- webhooks for Twilio

@router.post("/{callback_id}/twiml", include_in_schema=False)
async def twiml_when_desk_answers(callback_id: int, request: Request, db: Session = Depends(get_db)):
    """Step 2: the desk picked up. Tell Twilio to dial the patient."""
    await read_webhook(request)
    cb = get_callback_or_404(db, callback_id)
    provider = get_provider()
    if cb.status != CallbackStatus.CALLING:
        return twiml(provider.hangup_twiml())   # already finished: nothing to connect
    set_status(cb, CallbackStatus.CALLING, "Desk answered, ringing the patient")
    db.commit()
    return twiml(provider.bridge_twiml(cb.id, cb.name, cb.mobile))


@router.post("/{callback_id}/dial-status", include_in_schema=False)
async def dial_finished(callback_id: int, request: Request, db: Session = Depends(get_db)):
    """Step 4a: Twilio tells us whether the PATIENT answered."""
    params = await read_webhook(request)
    cb = get_callback_or_404(db, callback_id)
    result = params.get("DialCallStatus", "unknown")   # completed, busy, no-answer, failed, canceled
    if result in ("completed", "answered"):
        set_status(cb, CallbackStatus.DONE, "Patient was connected to the desk")
    else:
        set_status(cb, CallbackStatus.FAILED, f"Patient did not answer ({result})")
    db.commit()
    return twiml(get_provider().hangup_twiml())


@router.post("/{callback_id}/status", include_in_schema=False)
async def desk_call_ended(callback_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Step 4b: the call to the DESK has ended. If the request is still "calling",
    the patient was never connected (desk busy, didn't answer, hung up early...).
    """
    params = await read_webhook(request)
    cb = get_callback_or_404(db, callback_id)
    if cb.status == CallbackStatus.CALLING:
        result = params.get("CallStatus", "unknown")
        if result == "completed":
            set_status(cb, CallbackStatus.FAILED, "Call ended before the patient was connected")
        else:
            set_status(cb, CallbackStatus.FAILED, f"Hospital desk did not answer ({result})")
        db.commit()
    return {"ok": True}
