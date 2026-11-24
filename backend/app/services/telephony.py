"""
Telephony service: the ONLY file in mediQ that knows about Twilio.

How a call-back works (a "bridged" call):

    1. mediQ asks Twilio: "ring the hospital DESK number".
    2. The desk picks up. Twilio asks our server what to do next
       (POST /api/callback/{id}/twiml) and we answer with TwiML, a small
       XML script:  <Say>...</Say> <Dial><Number>+91 patient</Number></Dial>
    3. Twilio rings the PATIENT and joins the two calls together.
    4. Twilio tells our server how it went (the "dial-status" and "status" webhooks).

The rest of mediQ only uses the methods below, never Twilio directly:

    provider.start_bridge_call(callback_id)              -> call id
    provider.bridge_twiml(callback_id, name, mobile)     -> instructions for step 2
    provider.hangup_twiml()                              -> "end the call"
    provider.is_valid_webhook(url, params, signature)    -> did Twilio really send this?

To switch to Exotel later: write an ExotelProvider class with the same
methods and return it from get_provider(). No router code changes.
"""

import logging

from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

from ..config import Settings, get_settings

# "uvicorn.error" is uvicorn's main logger, so our messages show up in the same
# terminal as the server's own messages (the name is historical, not an error).
log = logging.getLogger("uvicorn.error")


class TelephonyError(Exception):
    """The provider could not place the call (bad settings, Twilio said no...)."""


class TwilioProvider:
    """Places REAL calls through Twilio."""

    def __init__(self, settings: Settings):
        required = {
            "TWILIO_ACCOUNT_SID": settings.twilio_account_sid,
            "TWILIO_AUTH_TOKEN": settings.twilio_auth_token,
            "TWILIO_FROM_NUMBER": settings.twilio_from_number,
            "DESK_NUMBER": settings.desk_number,
            "PUBLIC_BASE_URL": settings.public_base_url,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise TelephonyError("Missing settings in .env: " + ", ".join(missing))
        self.s = settings
        self.client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

    def url(self, path: str) -> str:
        """Full public address of one of our webhooks, e.g. https://abc.ngrok.app/api/..."""
        return self.s.public_base_url + path

    # ---- step 1: ring the desk ----
    def start_bridge_call(self, callback_id: int) -> str:
        try:
            call = self.client.calls.create(
                to=self.s.desk_number,
                from_=self.s.twilio_from_number,
                url=self.url(f"/api/callback/{callback_id}/twiml"),   # step 2
                status_callback=self.url(f"/api/callback/{callback_id}/status"),  # step 4
                status_callback_event=["completed"],  # tell us once, when the desk call ends
                timeout=30,                           # seconds to wait for the desk to answer
            )
        except TwilioRestException as e:
            raise TelephonyError(f"Twilio refused the call: {e.msg}") from e
        log.info("Callback %s: ringing desk %s (Twilio call %s)", callback_id, self.s.desk_number, call.sid)
        return call.sid

    # ---- step 2: what to do when the desk answers ----
    def bridge_twiml(self, callback_id: int, patient_name: str, patient_mobile: str) -> str:
        r = VoiceResponse()  # builds the XML for us and escapes odd characters safely
        r.say(f"mediQ call back request from {patient_name}. Connecting you now.")
        dial = r.dial(
            caller_id=self.s.twilio_from_number,  # the number the patient sees
            timeout=30,                           # seconds to wait for the patient
            action=self.url(f"/api/callback/{callback_id}/dial-status"),  # step 4
            method="POST",
        )
        dial.number(patient_mobile)
        return str(r)

    def hangup_twiml(self) -> str:
        r = VoiceResponse()
        r.hangup()
        return str(r)

    # ---- security: only accept webhooks that really come from Twilio ----
    def is_valid_webhook(self, url: str, params: dict, signature: str | None) -> bool:
        """
        Twilio signs every webhook with your auth token (the X-Twilio-Signature
        header). Without this check, anyone could POST "call completed" to us.
        """
        return RequestValidator(self.s.twilio_auth_token).validate(url, params, signature or "")


class DryRunProvider(TwilioProvider):
    """
    DRY_RUN=true: builds the same TwiML but NEVER contacts Twilio.
    Used in development and by every test, so nobody's phone rings by accident.
    """

    def __init__(self, settings: Settings):
        self.s = settings  # no Twilio client, no credentials needed

    def start_bridge_call(self, callback_id: int) -> str:
        log.info("DRY RUN: callback %s would ring desk %s now. Nobody was dialled.",
                 callback_id, self.s.desk_number or "(DESK_NUMBER not set)")
        return f"DRYRUN-{callback_id}"

    def is_valid_webhook(self, url: str, params: dict, signature: str | None) -> bool:
        return True  # no real Twilio in a dry run, so there is no signature to check


def get_provider():
    """Pick the provider from the settings. Change this one function to add Exotel."""
    settings = get_settings()
    return DryRunProvider(settings) if settings.dry_run else TwilioProvider(settings)
