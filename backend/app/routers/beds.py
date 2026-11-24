"""
Module 1: Bed availability.

A hospital has WARDS (General, ICU, Emergency...). Each ward has a fixed number
of numbered BEDS. A bed is either free or has one patient in it.

URLs (all start with /api/wards):
    GET  /api/wards                       every ward with its beds (staff screen)
    GET  /api/wards/availability          counts only, no names
    POST /api/wards                       create a ward
    POST /api/wards/{ward_id}/admit       put a patient in a bed
    POST /api/wards/{ward_id}/discharge   free a bed  (?bed=3)

Everything for this module lives in this one file: the data shapes (models)
and the endpoints (router). The data itself is saved in the database tables
`wards` and `beds` (WardRow and BedRow in db_models.py).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..db_models import BedRow, User, WardRow
from ..deps import admin_only, any_staff, get_optional_user, initials, is_staff

# An APIRouter is a "mini app": a group of endpoints that main.py plugs in
# with app.include_router(). prefix= is added in front of every path below,
# tags= groups them under "beds" on the /docs page.
router = APIRouter(prefix="/api/wards", tags=["beds"])


# ---------------------------------------------------------------- models

class WardCreate(BaseModel):
    """What the client sends to create a ward."""
    name: str = Field(..., min_length=1, examples=["ICU"])
    total_beds: int = Field(..., ge=1, le=500, description="How many beds this ward has")


class Bed(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # can be built from a BedRow

    number: int                          # bed 1, bed 2, ... inside its ward
    occupied: bool = False
    patient_name: str | None = None      # only set while occupied
    admitted_at: datetime | None = None


class Ward(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # can be built from a WardRow

    """A ward as the server stores it."""
    id: int
    name: str
    beds: list[Bed]


class WardView(BaseModel):
    """A ward plus ready-made counts, sent to the staff screen."""
    id: int
    name: str
    total: int
    occupied: int
    free: int
    beds: list[Bed]


class WardAvailability(BaseModel):
    """Counts only. Safe to share outside the hospital (no names)."""
    ward: str
    total: int
    occupied: int
    free: int


class AdmitRequest(BaseModel):
    patient_name: str = Field(..., min_length=1, examples=["Asha Patel"])
    # Leave empty to get the first free bed automatically.
    bed_number: int | None = Field(None, ge=1, description="Optional: a specific bed")


class AdmitResult(BaseModel):
    ward_id: int
    ward_name: str
    bed_number: int
    patient_name: str


# ---------------------------------------------------------------- helpers

def get_ward_or_404(db: Session, ward_id: int) -> WardRow:
    ward = db.get(WardRow, ward_id)
    if ward is None:
        raise HTTPException(status_code=404, detail=f"Ward {ward_id} not found")
    return ward


def get_bed_or_404(ward: WardRow, number: int) -> BedRow:
    if not 1 <= number <= len(ward.beds):
        raise HTTPException(status_code=404,
                            detail=f"{ward.name} has beds 1 to {len(ward.beds)}, not {number}")
    return ward.beds[number - 1]   # ward.beds is sorted by number; bed 1 is at position 0


def count(ward: WardRow) -> tuple[int, int, int]:
    """Return (total, occupied, free) for one ward."""
    total = len(ward.beds)
    occupied = sum(1 for b in ward.beds if b.occupied)
    return total, occupied, total - occupied


def all_wards(db: Session) -> list[WardRow]:
    return list(db.scalars(select(WardRow).order_by(WardRow.id)))


def total_free_beds() -> int:
    """Used by the city-wide summary in main.py."""
    with SessionLocal() as db:
        return sum(count(w)[2] for w in all_wards(db))


def bed_totals() -> tuple[int, int, int]:
    """(total, occupied, free) for the whole hospital (admin console)."""
    with SessionLocal() as db:
        totals = [count(w) for w in all_wards(db)]
    total, occupied = sum(t[0] for t in totals), sum(t[1] for t in totals)
    return total, occupied, total - occupied


def add_ward(db: Session, name: str, total_beds: int) -> WardRow:
    ward = WardRow(name=name, beds=[BedRow(number=n) for n in range(1, total_beds + 1)])
    db.add(ward)
    db.commit()
    return ward


def seed_demo_wards():
    """A few wards so the Beds screen isn't empty on first run."""
    with SessionLocal() as db:
        if db.scalar(select(WardRow).limit(1)) is not None:
            return
        add_ward(db, "General", 20)
        add_ward(db, "ICU", 6)
        add_ward(db, "Emergency", 8)


# ---------------------------------------------------------------- endpoints

@router.get("", response_model=list[WardView])   # no login needed
def list_wards(db: Session = Depends(get_db), user: User | None = Depends(get_optional_user)):
    """
    Every ward with every bed. Anyone may look.
    Staff see full patient names; everyone else sees initials ("A. P.").
    """
    staff = is_staff(user)
    views = []
    for ward in all_wards(db):
        total, occupied, free = count(ward)
        beds = [Bed.model_validate(b) for b in ward.beds]
        if not staff:
            for b in beds:
                b.patient_name = initials(b.patient_name)
        views.append(WardView(id=ward.id, name=ward.name, total=total, occupied=occupied, free=free,
                              beds=beds))
    return views


@router.get("/availability", response_model=list[WardAvailability])
def availability(db: Session = Depends(get_db)):
    """Just the numbers per ward. No patient names, so it is safe to share."""
    result = []
    for ward in all_wards(db):
        total, occupied, free = count(ward)
        result.append(WardAvailability(ward=ward.name, total=total, occupied=occupied, free=free))
    return result


@router.post("", response_model=Ward, status_code=201, dependencies=[Depends(admin_only)])
def create_ward(data: WardCreate, db: Session = Depends(get_db)):
    name = data.name.strip()
    if any(w.name.lower() == name.lower() for w in all_wards(db)):
        raise HTTPException(status_code=400, detail="A ward with that name already exists")
    return add_ward(db, name, data.total_beds)


@router.post("/{ward_id}/admit", response_model=AdmitResult, status_code=201, dependencies=[Depends(any_staff)])
def admit(ward_id: int, data: AdmitRequest, db: Session = Depends(get_db)):
    """
    Put a patient in a bed.
      - With bed_number: use that bed (error if someone is already in it).
      - Without: use the lowest-numbered free bed (error if the ward is full).
    """
    ward = get_ward_or_404(db, ward_id)

    if data.bed_number is not None:
        bed = get_bed_or_404(ward, data.bed_number)
        if bed.occupied:
            # 409 Conflict = "your request clashes with the current state"
            raise HTTPException(status_code=409, detail=f"Bed {bed.number} is already occupied")
    else:
        bed = next((b for b in ward.beds if not b.occupied), None)
        if bed is None:
            raise HTTPException(status_code=409, detail=f"No free beds in {ward.name}")

    bed.patient_name = data.patient_name.strip()
    bed.admitted_at = datetime.now()
    db.commit()
    return AdmitResult(ward_id=ward.id, ward_name=ward.name,
                       bed_number=bed.number, patient_name=bed.patient_name)


@router.post("/{ward_id}/discharge", dependencies=[Depends(any_staff)])
def discharge(ward_id: int, bed: int, db: Session = Depends(get_db)):
    """Free a bed. `bed` comes from the query string: .../discharge?bed=3"""
    ward = get_ward_or_404(db, ward_id)
    the_bed = get_bed_or_404(ward, bed)
    if not the_bed.occupied:
        raise HTTPException(status_code=404, detail=f"Bed {bed} in {ward.name} is already free")

    name = the_bed.patient_name
    the_bed.patient_name, the_bed.admitted_at = None, None
    db.commit()
    return {"discharged": name, "ward": ward.name, "bed_number": bed}
