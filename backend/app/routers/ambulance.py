"""
Module 3: Ambulance dispatch.

An ambulance is AVAILABLE, ON_TRIP or in MAINTENANCE. A trip goes:

    requested  --assign-->  assigned  --complete-->  completed
        \\______________________\\--cancel-->  cancelled

URLs:
    GET   /api/ambulances                        staff: the fleet, with each one's current trip
    GET   /api/ambulances/availability           anyone: counts only (no names)
    POST  /api/ambulances                        admin: add an ambulance
    PATCH /api/ambulances/{id}                   staff: new location, or maintenance <-> available
    GET   /api/ambulances/trips                  staff: trips (?status=requested,assigned)
    POST  /api/ambulances/trips                  staff: log a request (e.g. from a phone call)
    POST  /api/ambulances/trips/{id}/assign      staff: send an ambulance (a chosen one, or the first free)
    POST  /api/ambulances/trips/{id}/complete    staff: patient delivered; ambulance free again
    POST  /api/ambulances/trips/{id}/cancel      staff: not needed any more; ambulance free again

Requests are logged by STAFF (usually from a phone call to the ambulance helpline),
not by a public form, so nobody can send ambulances around as a prank.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..db_models import AmbulanceRow, TripRow
from ..deps import admin_only, any_staff
from ..models import AmbulanceStatus, TripStatus
from .callback import normalize_indian_mobile

router = APIRouter(prefix="/api/ambulances", tags=["ambulance"])

DEFAULT_DESTINATION = "mediQ City Hospital, Emergency"
OPEN = (TripStatus.REQUESTED, TripStatus.ASSIGNED)          # trips still in progress


# ---------------------------------------------------------------- models

class AmbulanceCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=10, examples=["AMB-05"])
    vehicle_number: str = Field(..., min_length=1, max_length=20, examples=["MH 12 XX 0005"])
    driver_name: str = Field(..., min_length=1, max_length=100)
    driver_phone: str = Field(..., max_length=20, examples=["98765 43210"])
    location: str = Field("Hospital ambulance bay", max_length=200)


class AmbulanceUpdate(BaseModel):
    """Send only what changes. status may only be "available" or "maintenance"."""
    location: str | None = Field(None, min_length=1, max_length=200)
    status: AmbulanceStatus | None = None


class TripCreate(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=100)
    contact_phone: str = Field(..., max_length=20, examples=["98765 43210"])
    pickup: str = Field(..., min_length=3, max_length=200, examples=["12 MG Road, near City Mall"])
    destination: str = Field(DEFAULT_DESTINATION, max_length=200)
    notes: str = Field("", max_length=300, examples=["Elderly man, chest pain"])


class AssignRequest(BaseModel):
    ambulance_id: int | None = Field(None, description="Leave empty to send the first available ambulance")


class TripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ambulance_id: int | None
    ambulance_code: str | None = None
    patient_name: str
    contact_phone: str
    pickup: str
    destination: str
    notes: str
    status: TripStatus
    requested_at: datetime
    assigned_at: datetime | None
    finished_at: datetime | None


class AmbulanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    vehicle_number: str
    driver_name: str
    driver_phone: str
    status: AmbulanceStatus
    location: str
    updated_at: datetime
    current_trip: TripOut | None = None


class Availability(BaseModel):
    """Counts only: safe for the public website and the city-wide summary."""
    available: int
    on_trip: int
    maintenance: int


# ---------------------------------------------------------------- helpers

def trip_out(trip: TripRow) -> TripOut:
    out = TripOut.model_validate(trip)
    out.ambulance_code = trip.ambulance.code if trip.ambulance else None
    return out


def get_ambulance_or_404(db: Session, ambulance_id: int) -> AmbulanceRow:
    amb = db.get(AmbulanceRow, ambulance_id)
    if amb is None:
        raise HTTPException(status_code=404, detail=f"Ambulance {ambulance_id} not found")
    return amb


def get_trip_or_404(db: Session, trip_id: int) -> TripRow:
    trip = db.get(TripRow, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")
    return trip


def phone_or_400(raw: str) -> str:
    phone = normalize_indian_mobile(raw)
    if phone is None:
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit Indian mobile number")
    return phone


def counts(db: Session) -> Availability:
    per_status = {s: 0 for s in AmbulanceStatus}
    for status, n in db.execute(select(AmbulanceRow.status, func.count()).group_by(AmbulanceRow.status)):
        per_status[status] = n
    return Availability(available=per_status[AmbulanceStatus.AVAILABLE],
                        on_trip=per_status[AmbulanceStatus.ON_TRIP],
                        maintenance=per_status[AmbulanceStatus.MAINTENANCE])


def available_count() -> int:
    """Used by the city-wide summary and the admin console."""
    with SessionLocal() as db:
        return counts(db).available


def free_ambulance(amb: AmbulanceRow, location: str | None = None):
    """The trip is over: the ambulance is ready again (at `location` if given)."""
    amb.status = AmbulanceStatus.AVAILABLE
    if location:
        amb.location = location
    amb.updated_at = datetime.now()


def seed_demo_ambulances():
    """Four made-up ambulances (fake drivers, numbers and vehicle plates)."""
    with SessionLocal() as db:
        if db.scalar(select(AmbulanceRow).limit(1)) is not None:
            return
        now = datetime.now()
        demo = [
            ("AMB-01", "MH 12 XX 0001", "Ramesh Kale", "+919000040001", "Hospital ambulance bay"),
            ("AMB-02", "MH 12 XX 0002", "Sunil Pawar", "+919000040002", "Hospital ambulance bay"),
            ("AMB-03", "MH 12 XX 0003", "Imran Shaikh", "+919000040003", "Sector 12 standby point"),
            ("AMB-04", "MH 12 XX 0004", "Joseph D'Souza", "+919000040004", "Ring Road standby point"),
        ]
        for code, plate, driver, phone, where in demo:
            db.add(AmbulanceRow(code=code, vehicle_number=plate, driver_name=driver, driver_phone=phone,
                                status=AmbulanceStatus.AVAILABLE, location=where, updated_at=now))
        db.commit()


# ---------------------------------------------------------------- endpoints: fleet

@router.get("", response_model=list[AmbulanceOut], dependencies=[Depends(any_staff)])
def fleet(db: Session = Depends(get_db)):
    """Every ambulance, with the trip it's on (if any)."""
    current = {t.ambulance_id: t for t in db.scalars(
        select(TripRow).where(TripRow.status == TripStatus.ASSIGNED))}
    result = []
    for amb in db.scalars(select(AmbulanceRow).order_by(AmbulanceRow.code)):
        out = AmbulanceOut.model_validate(amb)
        if amb.id in current:
            out.current_trip = trip_out(current[amb.id])
        result.append(out)
    return result


@router.get("/availability", response_model=Availability)
def availability(db: Session = Depends(get_db)):
    return counts(db)


@router.post("", response_model=AmbulanceOut, status_code=201, dependencies=[Depends(admin_only)])
def add_ambulance(data: AmbulanceCreate, db: Session = Depends(get_db)):
    code = data.code.strip().upper()
    if db.scalar(select(AmbulanceRow).where(AmbulanceRow.code == code)) is not None:
        raise HTTPException(status_code=409, detail=f"Ambulance {code} already exists")
    amb = AmbulanceRow(code=code, vehicle_number=data.vehicle_number.strip(), driver_name=data.driver_name.strip(),
                       driver_phone=phone_or_400(data.driver_phone), status=AmbulanceStatus.AVAILABLE,
                       location=data.location.strip(), updated_at=datetime.now())
    db.add(amb)
    db.commit()
    return amb


@router.patch("/{ambulance_id}", response_model=AmbulanceOut, dependencies=[Depends(any_staff)])
def update_ambulance(ambulance_id: int, data: AmbulanceUpdate, db: Session = Depends(get_db)):
    """Update the location, or take an ambulance out of / back into service."""
    amb = get_ambulance_or_404(db, ambulance_id)
    if data.status is not None:
        if data.status == AmbulanceStatus.ON_TRIP:
            raise HTTPException(status_code=400, detail="Use 'assign' on a trip to send an ambulance out.")
        if amb.status == AmbulanceStatus.ON_TRIP:
            raise HTTPException(status_code=409, detail=f"{amb.code} is on a trip. Complete or cancel it first.")
        amb.status = data.status
    if data.location is not None:
        amb.location = data.location.strip()
    amb.updated_at = datetime.now()
    db.commit()
    return amb


# ---------------------------------------------------------------- endpoints: trips

@router.get("/trips", response_model=list[TripOut], dependencies=[Depends(any_staff)])
def list_trips(status: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    """Newest first. ?status=requested,assigned shows only open trips."""
    query = select(TripRow)
    if status:
        try:
            wanted = [TripStatus(s.strip()) for s in status.split(",")]
        except ValueError:
            raise HTTPException(status_code=422, detail="status must be requested, assigned, completed or cancelled")
        query = query.where(TripRow.status.in_(wanted))
    query = query.order_by(TripRow.id.desc()).limit(min(max(limit, 1), 200))
    return [trip_out(t) for t in db.scalars(query)]


@router.post("/trips", response_model=TripOut, status_code=201, dependencies=[Depends(any_staff)])
def request_trip(data: TripCreate, db: Session = Depends(get_db)):
    """Log a request for an ambulance. It waits as "requested" until one is assigned."""
    trip = TripRow(patient_name=data.patient_name.strip(), contact_phone=phone_or_400(data.contact_phone),
                   pickup=data.pickup.strip(), destination=data.destination.strip() or DEFAULT_DESTINATION,
                   notes=data.notes.strip(), status=TripStatus.REQUESTED, requested_at=datetime.now())
    db.add(trip)
    db.commit()
    return trip_out(trip)


@router.post("/trips/{trip_id}/assign", response_model=TripOut, dependencies=[Depends(any_staff)])
def assign(trip_id: int, data: AssignRequest, db: Session = Depends(get_db)):
    """Send an ambulance. Both the trip and the ambulance change in ONE save."""
    trip = get_trip_or_404(db, trip_id)
    if trip.status != TripStatus.REQUESTED:
        raise HTTPException(status_code=409, detail=f"Trip {trip.id} is already {trip.status.value}.")

    if data.ambulance_id is not None:
        amb = get_ambulance_or_404(db, data.ambulance_id)
        if amb.status != AmbulanceStatus.AVAILABLE:
            raise HTTPException(status_code=409,
                                detail=f"{amb.code} is not available ({amb.status.value.replace('_', ' ')}).")
    else:
        amb = db.scalars(select(AmbulanceRow).where(AmbulanceRow.status == AmbulanceStatus.AVAILABLE)
                         .order_by(AmbulanceRow.code).limit(1)).first()
        if amb is None:
            raise HTTPException(status_code=409, detail="No ambulance is available right now.")

    now = datetime.now()
    trip.ambulance_id, trip.status, trip.assigned_at = amb.id, TripStatus.ASSIGNED, now
    amb.status, amb.updated_at = AmbulanceStatus.ON_TRIP, now
    db.commit()
    db.refresh(trip)
    return trip_out(trip)


@router.post("/trips/{trip_id}/complete", response_model=TripOut, dependencies=[Depends(any_staff)])
def complete(trip_id: int, db: Session = Depends(get_db)):
    """Patient delivered. The ambulance is free again, now at the destination."""
    trip = get_trip_or_404(db, trip_id)
    if trip.status != TripStatus.ASSIGNED:
        raise HTTPException(status_code=409, detail=f"Only an assigned trip can be completed (this one is {trip.status.value}).")
    trip.status, trip.finished_at = TripStatus.COMPLETED, datetime.now()
    free_ambulance(trip.ambulance, location=trip.destination)
    db.commit()
    return trip_out(trip)


@router.post("/trips/{trip_id}/cancel", response_model=TripOut, dependencies=[Depends(any_staff)])
def cancel(trip_id: int, db: Session = Depends(get_db)):
    """Not needed any more. If an ambulance was on its way, it becomes available again."""
    trip = get_trip_or_404(db, trip_id)
    if trip.status not in OPEN:
        raise HTTPException(status_code=409, detail=f"Trip {trip.id} is already {trip.status.value}.")
    if trip.ambulance is not None:
        free_ambulance(trip.ambulance)
    trip.status, trip.finished_at = TripStatus.CANCELLED, datetime.now()
    db.commit()
    return trip_out(trip)
