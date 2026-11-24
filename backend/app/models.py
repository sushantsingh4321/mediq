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
    WAITING = "waiting"                  # in the queue
    IN_CONSULTATION = "in_consultation"  # with a doctor now
    DONE = "done"                        # consultation finished


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
