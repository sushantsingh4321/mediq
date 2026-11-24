"""
SMS hook for appointment messages: a STUB for now.

notify.py calls send_sms() every time a patient gets a message. Today it only
writes a line to the server log and keeps the last messages in OUTBOX, so you
can see what WOULD have been sent (and tests can check it). Nothing leaves the
server and nothing costs money.

Later: send it for real, for example with Twilio like the call-back feature
(services/telephony.py already has an account and a DRY_RUN switch). Only this
file needs to change; every caller stays the same.
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime

# uvicorn prints this logger's INFO lines (same as services/telephony.py), so you see them in the terminal
log = logging.getLogger("uvicorn.error")

# The last 200 messages "sent", in memory only: for tests and a quick look while
# developing. On Vercel each copy of the app has its own (and loses it), which is
# fine: the log line is the record, and the real messages live in the database.
OUTBOX: deque["Sms"] = deque(maxlen=200)


@dataclass
class Sms:
    to: str | None
    text: str
    at: datetime


def send_sms(to: str | None, text: str) -> bool:
    """Pretend to send. Returns False (nothing was really sent)."""
    OUTBOX.append(Sms(to, text, datetime.now()))
    log.info("SMS not sent (stub) to %s: %s", to or "(no phone number)", text)
    return False
