"""
Website content + the "Quick enquiry" form.

URLs:
    GET  /api/site        hospitals, cities, specialities... (from the data file)
    POST /api/enquiries   save a "please call me back" enquiry
    GET  /api/enquiries   list saved enquiries (for hospital staff)

All the lists live in ONE file: backend/app/data/site_content.json.
Edit that file to add a hospital or a speciality; no Python or HTML changes needed.
We read the file on every request, so a change shows up as soon as you refresh
the browser (no server restart).
"""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..db_models import EnquiryRow
from ..deps import admin_only

router = APIRouter(prefix="/api", tags=["website"])

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "site_content.json"


# ---------------------------------------------------------------- models
# These describe the SHAPE of site_content.json. If you make a typo in the
# file (say "hospitls"), GET /api/site fails with a clear error instead of
# the website silently showing nothing.

class Helpline(BaseModel):
    label: str
    number: str


class EmergencyNumber(BaseModel):
    label: str          # "Ambulance, anywhere in India"
    number: str         # "108": India's real public emergency numbers, not invented ones


class Hospital(BaseModel):
    name: str
    area: str
    city: str
    state: str          # the menu groups hospitals by this


class Speciality(BaseModel):
    name: str
    conditions: list[str]


class CountryCode(BaseModel):
    code: str           # "+91"
    country: str        # "India"


class SiteContent(BaseModel):
    brand: str
    tagline: str
    email: str
    head_office: str
    helplines: list[Helpline]
    emergency_numbers: list[EmergencyNumber]
    hospitals: list[Hospital]
    specialities: list[Speciality]
    country_codes: list[CountryCode]
    default_country_code: str


class EnquiryCreate(BaseModel):
    """What the enquiry form sends."""
    name: str = Field(..., min_length=1, max_length=100, examples=["Asha Patel"])
    country_code: str = Field(..., examples=["+91"])
    mobile: str = Field(..., pattern=r"^[0-9]{6,15}$",
                        description="Digits only, 6 to 15 of them", examples=["9876543210"])
    speciality: str = Field(..., examples=["Cardiology"])
    consent: bool = Field(..., description="Patient agreed to be contacted")


class Enquiry(EnquiryCreate):
    """An enquiry as stored by the server."""
    model_config = ConfigDict(from_attributes=True)   # can be built from an EnquiryRow

    id: int
    created_at: datetime


# ---------------------------------------------------------------- storage
# Saved in the database table "enquiries" (EnquiryRow in db_models.py).

def enquiry_counts() -> tuple[int, int]:
    """(all enquiries, enquiries received today) for the admin console."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(EnquiryRow))
        new_today = db.scalar(select(func.count()).select_from(EnquiryRow).where(EnquiryRow.created_at >= today))
    return total, new_today


def load_site_content() -> SiteContent:
    with open(DATA_FILE, encoding="utf-8") as f:
        return SiteContent.model_validate(json.load(f))


# ---------------------------------------------------------------- endpoints

@router.get("/site", response_model=SiteContent)
def site_content():
    """Everything the shared header, menu, footer and home page need."""
    return load_site_content()


@router.post("/enquiries", response_model=Enquiry, status_code=201)
def create_enquiry(data: EnquiryCreate, db: Session = Depends(get_db)):
    # Pydantic already checked the types and the mobile format (422 if wrong).
    # These are the rules that need the data file or common sense (400 if wrong).
    site = load_site_content()
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Please enter your name")
    if not data.consent:
        raise HTTPException(status_code=400, detail="Please tick the consent box so we may call you")
    if data.country_code not in {c.code for c in site.country_codes}:
        raise HTTPException(status_code=400, detail=f"Unknown country code {data.country_code}")
    if data.speciality not in {s.name for s in site.specialities}:
        raise HTTPException(status_code=400, detail=f"Unknown speciality {data.speciality}")

    row = EnquiryRow(**{**data.model_dump(), "name": name}, created_at=datetime.now())
    db.add(row)
    db.commit()
    return row


@router.get("/enquiries", response_model=list[Enquiry], dependencies=[Depends(admin_only)])
def list_enquiries(db: Session = Depends(get_db)):
    """
    For hospital staff (call-back list), oldest first. Contains names and phone
    numbers, so it must NEVER be added to the city-wide summary.
    """
    return db.scalars(select(EnquiryRow).order_by(EnquiryRow.id)).all()
