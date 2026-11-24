"""
Pydantic models = the SHAPE of the data going in and out of the API.

FastAPI reads these classes and automatically:
  - checks incoming JSON (wrong type or missing field -> clear 422 error)
  - converts outgoing data to JSON
  - documents everything at http://localhost:8000/docs
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TokenStatus(str, Enum):
    BOOKED = "booked"                    # made for an appointment; patient not here yet (NOT in the live queue)
    WAITING = "waiting"                  # in the queue
    IN_CONSULTATION = "in_consultation"  # with a doctor now
    DONE = "done"                        # consultation finished
    CANCELLED = "cancelled"              # its appointment was rejected or cancelled


class AppointmentStatus(str, Enum):
    r"""
    The life of one booking (Module 5: patient self-booking).

        requested --accept--> accepted --"I've arrived"--> checked_in --> completed
            |                    |  \--15 min after the slot, not arrived--> no_show
            |                    \--doctor rejects--> rejected (with a reason)
            \--patient cancels (up to 1 hour before)--> cancelled

    With auto_accept on (the default), a booking starts at "accepted".
    """
    REQUESTED = "requested"      # waiting for the doctor (auto_accept off)
    ACCEPTED = "accepted"        # confirmed; has a token
    REJECTED = "rejected"        # the doctor said no (reject_reason says why)
    CANCELLED = "cancelled"      # the patient cancelled
    CHECKED_IN = "checked_in"    # the patient is at the hospital: in the live queue
    COMPLETED = "completed"      # seen by the doctor
    NO_SHOW = "no_show"          # never checked in


# Bookings that still hold their slot. Used for "no double booking".
ACTIVE_APPOINTMENT_STATUSES = (AppointmentStatus.REQUESTED, AppointmentStatus.ACCEPTED,
                               AppointmentStatus.CHECKED_IN)


class AppointmentSource(str, Enum):
    ONLINE = "online"            # the patient booked it
    WALK_IN = "walk_in"          # the doctor added someone who just turned up


class CallbackStatus(str, Enum):
    """Status of a "Request Call Back" (routers/callback.py)."""
    PENDING = "pending"    # saved, call not started yet
    CALLING = "calling"    # the desk is being rung / connected
    DONE = "done"          # the patient was connected to the desk
    FAILED = "failed"      # something went wrong (see the note)


class AmbulanceStatus(str, Enum):
    """Module 3: what an ambulance is doing."""
    AVAILABLE = "available"      # at its location, ready to go
    ON_TRIP = "on_trip"          # assigned to a trip
    MAINTENANCE = "maintenance"  # out of service


class TripStatus(str, Enum):
    """Module 3: the life of one ambulance trip."""
    REQUESTED = "requested"      # someone needs an ambulance, none sent yet
    ASSIGNED = "assigned"        # an ambulance is on its way / carrying the patient
    COMPLETED = "completed"      # patient delivered, ambulance free again
    CANCELLED = "cancelled"


# ---------- Module 4: Pharmacy (lists of allowed values) ----------

class DosageForm(str, Enum):
    """The physical form a medicine comes in."""
    TABLET = "tablet"
    CAPSULE = "capsule"
    SYRUP = "syrup"
    INJECTION = "injection"
    OINTMENT = "ointment"
    DROPS = "drops"
    INHALER = "inhaler"


class DrugSchedule(str, Enum):
    """
    Indian Drugs & Cosmetics Rules, 1945. Decides who may buy a medicine:
      OTC  over the counter: anyone, no prescription (e.g. Paracetamol)
      H    prescription needed (most antibiotics)
      H1   prescription needed AND the pharmacy keeps a register (e.g. some antibiotics, anti-TB)
      X    prescription needed, kept in duplicate, strict storage (e.g. strong sedatives)
    """
    OTC = "OTC"
    H = "H"
    H1 = "H1"
    X = "X"


class StorageType(str, Enum):
    ROOM = "room"                       # normal shelf, below 25-30 °C
    COLD_CHAIN = "cold_chain_2_8C"      # fridge, 2-8 °C (insulin, many vaccines)


class PurchaseOrderStatus(str, Enum):
    DRAFT = "draft"          # being written, not sent to the supplier yet
    ORDERED = "ordered"      # sent to the supplier
    RECEIVED = "received"    # the goods arrived and became batches


class MovementType(str, Enum):
    """Why stock changed. Every change is written to stock_movements."""
    IN = "in"                # new stock received
    OUT = "out"              # dispensed to a patient
    ADJUST = "adjust"        # stock count correction (damaged, miscounted...)
    EXPIRED = "expired"      # removed because it expired
    RETURNED = "returned"    # patient or ward returned it


# ---------- Departments ----------

class DepartmentCreate(BaseModel):
    """What the client sends to create a department."""
    code: str = Field(..., min_length=1, max_length=5, examples=["GEN"],
                      description="Short prefix used on tokens, e.g. GEN-007")
    name: str = Field(..., examples=["General Medicine"])
    doctors: int = Field(1, ge=1, description="Doctors (rooms) working in parallel = c")
    avg_consult_minutes: float = Field(10, gt=0, description="Average consultation time = 1/mu")
    expected_patients_per_hour: float = Field(6, ge=0, description="Expected arrival rate = lambda")


class Department(DepartmentCreate):
    """A department as stored by the server (adds an id)."""
    # from_attributes: can be built from a database row (DepartmentRow in db_models.py)
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---------- Tokens (patients in the queue) ----------

class TokenCreate(BaseModel):
    patient_name: str = Field(..., min_length=1, examples=["Asha Patel"])
    department_id: int


class Token(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # can be built from a TokenRow

    id: int
    number: str            # human-friendly, e.g. "GEN-007"
    patient_name: str
    department_id: int
    status: TokenStatus
    room: int | None = None          # which doctor's room, once called
    created_at: datetime
    called_at: datetime | None = None
    finished_at: datetime | None = None
    scheduled_at: datetime | None = None   # the appointment's slot time (queue order), if booked
    priority: int = 0                      # higher = sooner among the same slot time


class TokenView(Token):
    """A token plus live info for the patient: position and estimated wait."""
    people_ahead: int | None = None
    estimated_wait_minutes: float | None = None


# ---------- Queue statistics ----------

class QueueStats(BaseModel):
    department: Department
    waiting: int
    in_consultation: int
    done_today: int
    now_serving: list[str]               # token numbers currently with doctors
    wait_for_new_patient_minutes: float  # estimate if someone joins right now
    observed_arrivals_last_hour: int
    # M/M/c model output (see queueing.py)
    model: dict


class HospitalSummary(BaseModel):
    """
    The small, privacy-safe status report a hospital can share with a future
    city-wide service. No patient names, just numbers.
    """
    hospital_id: str
    hospital_name: str
    generated_at: datetime
    departments: list[dict]
    # Counts from the extra modules, e.g. {"free_beds": 12}. Never names.
    facilities: dict = Field(default_factory=dict)
