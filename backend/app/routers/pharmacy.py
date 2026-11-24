"""
Module 4: Pharmacy. The URLs; the rules themselves are in services/pharmacy.py.

Who may do what (admins may always do everything):
    anyone       search the catalogue (name, strength, price, in stock or not)
    doctor       write prescriptions; read prescriptions, batches and alerts
    pharmacist   everything else: catalogue, suppliers, stock, dispensing, orders

URLs (all start with /api/pharmacy):
  Catalogue
    GET    /medicines?q=dolo&category=analgesic    search brand OR generic name
    GET    /medicines/{id}                         one medicine with its batches
    POST   /medicines                              add          PUT /medicines/{id}  change
    DELETE /medicines/{id}                         hide (is_active = false; history is kept)
    GET    /categories                             category names, for dropdowns
  Suppliers
    GET /suppliers   POST /suppliers   PUT /suppliers/{id}   DELETE /suppliers/{id}
  Stock
    POST /stock/receive                 a delivery arrives: new batch
    POST /stock/adjust                  correct a count (+/-), with a reason
    POST /stock/write-off-expired       take every expired batch off the shelf
    GET  /stock/movements               the stock diary
    GET  /stock/report                  per medicine: units, value, nearest expiry
  Prescriptions and dispensing
    POST /prescriptions                 doctor writes one
    GET  /prescriptions?open_only=true  list (with what is still to hand out)
    GET  /prescriptions/{id}
    POST /dispense                      hand out + make the bill (FEFO, Schedule H check, GST)
    GET  /dispensations                 recent bills      GET /dispensations/{id}  one bill (to print)
  Purchase orders
    POST /purchase-orders               draft     GET /purchase-orders   GET /purchase-orders/{id}
    POST /purchase-orders/{id}/order    draft -> ordered
    POST /purchase-orders/{id}/receive  ordered -> received (creates the batches)
    DELETE /purchase-orders/{id}        only drafts
  Alerts
    GET /alerts                         low stock, expiring in 30/60/90 days, expired

A broken rule (PharmacyError) becomes a 400 response with a message saying
what to fix; main.py sets that up.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..db_models import (DispensationRow, MedicineBatchRow, MedicineRow, PrescriptionItemRow,
                         PrescriptionRow, PurchaseOrderItemRow, PurchaseOrderRow, Role, StockMovementRow,
                         SupplierRow, TokenRow, User)
from ..deps import doctor_only, pharmacist_only, pharmacy_readers
from ..models import DosageForm, DrugSchedule, MovementType, PurchaseOrderStatus, StorageType
from ..services import pharmacy as ph
from ..services.pharmacy import PharmacyError

router = APIRouter(prefix="/api/pharmacy", tags=["pharmacy"])

# Money is a Decimal inside Python (exact), but goes out as a JSON number (12.35)
# so the browser can do maths with it.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]
GST_SLABS = {Decimal(x) for x in ("0", "5", "12", "18", "28")}


def get_or_404(db: Session, row_class, row_id: int, what: str):
    row = db.get(row_class, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{what} #{row_id} not found")
    return row


# =====================================================================
# Medicines
# =====================================================================

class MedicineIn(BaseModel):
    """What you send to add or change a medicine."""
    brand_name: str = Field(..., min_length=1, max_length=100, examples=["Dolo 650"])
    generic_name: str = Field(..., min_length=1, max_length=200, examples=["Paracetamol"])
    strength: str = Field(..., min_length=1, max_length=50, examples=["650 mg"])
    dosage_form: DosageForm
    category: str = Field(..., min_length=1, max_length=50, examples=["analgesic"])
    schedule: DrugSchedule = DrugSchedule.OTC
    manufacturer: str = Field(..., min_length=1, max_length=100, examples=["Micro Labs"])
    hsn_code: str = Field("3004", pattern=r"^\d{4,8}$")           # 3004 = packaged medicines
    gst_percent: Decimal = Decimal("12")
    pack_size: int = Field(10, ge=1, le=10000)
    unit: str = Field("tablet", min_length=1, max_length=20)
    storage: StorageType = StorageType.ROOM
    prescription_required: bool = False
    reorder_level: int = Field(50, ge=0)
    is_active: bool = True

    @field_validator("brand_name", "generic_name", "strength", "category", "manufacturer", "unit")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("category", "unit")
    @classmethod
    def lower(cls, v: str) -> str:
        return v.lower()

    @field_validator("gst_percent")
    @classmethod
    def gst_slab(cls, v: Decimal) -> Decimal:
        if v not in GST_SLABS:
            raise ValueError("GST must be one of the slabs: 0, 5, 12, 18 or 28")
        return v

    @model_validator(mode="after")
    def schedule_needs_prescription(self):
        # Schedule H/H1/X always need a prescription, whatever the checkbox says
        if self.schedule != DrugSchedule.OTC:
            self.prescription_required = True
        return self


class MedicineOut(MedicineIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    display_name: str                       # "Dolo 650", or "Crocin Advance 500 mg"
    gst_percent: Money
    stock: int = 0                          # units we can hand out (in date)
    low_stock: bool = False
    mrp: Money | None = None                # of the batch that would go out next (FEFO)
    selling_price: Money | None = None


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    medicine_id: int
    supplier_id: int | None
    supplier_name: str | None = None
    batch_no: str
    mfg_date: date
    expiry_date: date
    quantity: int
    purchase_price: Money
    mrp: Money
    selling_price: Money
    received_at: datetime
    rack_location: str | None
    expired: bool = False
    days_to_expiry: int = 0


class MedicineDetail(MedicineOut):
    batches: list[BatchOut]


def batch_out(b: MedicineBatchRow, today: date) -> BatchOut:
    out = BatchOut.model_validate(b)
    out.supplier_name = b.supplier.name if b.supplier else None
    out.expired = ph.is_expired(b, today)
    out.days_to_expiry = (b.expiry_date - today).days
    return out


def medicine_out(db: Session, m: MedicineRow, today: date) -> MedicineOut:
    """The medicine plus live numbers: in-date stock and the price of the next batch out (FEFO)."""
    usable = ph.usable_batches(db, m.id, today)
    stock = sum(b.quantity for b in usable)
    return MedicineOut.model_validate(m).model_copy(update={
        "stock": stock,
        "low_stock": m.is_active and stock <= m.reorder_level,
        "mrp": usable[0].mrp if usable else None,
        "selling_price": usable[0].selling_price if usable else None,
    })


@router.get("/medicines", response_model=list[MedicineOut])
def search_medicines(q: str = "", category: str | None = None, include_inactive: bool = False,
                     in_stock_only: bool = False, limit: int = Query(100, ge=1, le=500),
                     db: Session = Depends(get_db)):
    """
    Search by brand OR generic name: "dolo" finds Dolo 650, "paracetamol" finds
    every paracetamol brand. Open to everyone (no purchase prices here).
    """
    query = select(MedicineRow)
    words = q.strip()
    if words:
        like = f"%{words}%"
        query = query.where(or_(MedicineRow.brand_name.ilike(like), MedicineRow.generic_name.ilike(like)))
    if category:
        query = query.where(MedicineRow.category == category.lower())
    if not include_inactive:
        query = query.where(MedicineRow.is_active)
    today = ph.today_local()
    meds = [medicine_out(db, m, today) for m in
            db.scalars(query.order_by(MedicineRow.brand_name, MedicineRow.strength).limit(limit))]
    return [m for m in meds if m.stock > 0] if in_stock_only else meds


@router.get("/categories", response_model=list[str])
def categories(db: Session = Depends(get_db)):
    return db.scalars(select(MedicineRow.category).distinct().order_by(MedicineRow.category)).all()


@router.get("/medicines/{medicine_id}", response_model=MedicineDetail, dependencies=[Depends(pharmacy_readers)])
def medicine_detail(medicine_id: int, db: Session = Depends(get_db)):
    """One medicine with ALL its batches (incl. purchase prices), soonest expiry first."""
    m = get_or_404(db, MedicineRow, medicine_id, "Medicine")
    today = ph.today_local()
    return MedicineDetail(**medicine_out(db, m, today).model_dump(),
                          batches=[batch_out(b, today) for b in m.batches])


def save_or_400(db: Session, message: str):
    """Commit; if the database refuses (e.g. a duplicate), say so in plain words."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail=message) from None


@router.post("/medicines", response_model=MedicineOut, status_code=201, dependencies=[Depends(pharmacist_only)])
def add_medicine(data: MedicineIn, db: Session = Depends(get_db)):
    m = MedicineRow(**data.model_dump())
    db.add(m)
    save_or_400(db, f"{data.brand_name} {data.strength} {data.dosage_form.value} is already in the catalogue.")
    return medicine_out(db, m, ph.today_local())


@router.put("/medicines/{medicine_id}", response_model=MedicineOut, dependencies=[Depends(pharmacist_only)])
def update_medicine(medicine_id: int, data: MedicineIn, db: Session = Depends(get_db)):
    m = get_or_404(db, MedicineRow, medicine_id, "Medicine")
    for field, value in data.model_dump().items():
        setattr(m, field, value)
    save_or_400(db, f"Another medicine is already called {data.brand_name} {data.strength} "
                    f"{data.dosage_form.value}.")
    return medicine_out(db, m, ph.today_local())


@router.delete("/medicines/{medicine_id}", status_code=204, dependencies=[Depends(pharmacist_only)])
def deactivate_medicine(medicine_id: int, db: Session = Depends(get_db)):
    """
    "Delete" only hides it: old prescriptions and bills still point to it, and
    the law expects those records to be kept. PUT with is_active=true brings it back.
    """
    get_or_404(db, MedicineRow, medicine_id, "Medicine").is_active = False
    db.commit()


# =====================================================================
# Suppliers
# =====================================================================

class SupplierIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["Apollo Distributors"])
    # GSTIN: 2-digit state code + PAN (5 letters, 4 digits, 1 letter) + entity + "Z" + check character
    gstin: str | None = Field(None, pattern=r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$",
                              examples=["27ABCDE1234F1Z5"])
    drug_license_no: str | None = Field(None, max_length=50, examples=["MH-PUN-123456"])
    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=300)

    @field_validator("gstin", mode="before")
    @classmethod
    def tidy_gstin(cls, v):
        return (v.strip().upper() or None) if isinstance(v, str) else v

    @field_validator("drug_license_no", "phone", "email", "address", mode="before")
    @classmethod
    def blank_is_none(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v


class SupplierOut(SupplierIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    gstin: str | None = None


@router.get("/suppliers", response_model=list[SupplierOut], dependencies=[Depends(pharmacist_only)])
def list_suppliers(db: Session = Depends(get_db)):
    return db.scalars(select(SupplierRow).order_by(SupplierRow.name)).all()


@router.post("/suppliers", response_model=SupplierOut, status_code=201, dependencies=[Depends(pharmacist_only)])
def add_supplier(data: SupplierIn, db: Session = Depends(get_db)):
    s = SupplierRow(**data.model_dump())
    db.add(s)
    save_or_400(db, f"A supplier called {data.name} already exists.")
    return s


@router.put("/suppliers/{supplier_id}", response_model=SupplierOut, dependencies=[Depends(pharmacist_only)])
def update_supplier(supplier_id: int, data: SupplierIn, db: Session = Depends(get_db)):
    s = get_or_404(db, SupplierRow, supplier_id, "Supplier")
    for field, value in data.model_dump().items():
        setattr(s, field, value)
    save_or_400(db, f"A supplier called {data.name} already exists.")
    return s


@router.delete("/suppliers/{supplier_id}", status_code=204, dependencies=[Depends(pharmacist_only)])
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)):
    s = get_or_404(db, SupplierRow, supplier_id, "Supplier")
    used = (db.scalar(select(func.count()).where(MedicineBatchRow.supplier_id == s.id))
            or db.scalar(select(func.count()).where(PurchaseOrderRow.supplier_id == s.id)))
    if used:
        raise HTTPException(status_code=400, detail=f"{s.name} has batches or purchase orders, so it is kept "
                                                    "for the records. You can still edit it.")
    db.delete(s)
    db.commit()


# =====================================================================
# Stock
# =====================================================================

class ReceiveIn(BaseModel):
    medicine_id: int
    supplier_id: int | None = None
    batch_no: str = Field(..., min_length=1, max_length=30, examples=["DL24117"])
    mfg_date: date
    expiry_date: date
    quantity: int = Field(..., ge=1, examples=[500])
    purchase_price: Decimal = Field(..., gt=0, examples=["1.20"])   # per unit
    mrp: Decimal = Field(..., gt=0, examples=["2.20"])               # per unit
    selling_price: Decimal = Field(..., gt=0, examples=["1.90"])     # per unit, before GST
    rack_location: str | None = Field(None, max_length=20, examples=["A3-2"])


@router.post("/stock/receive", response_model=BatchOut, status_code=201)
def receive(data: ReceiveIn, user: User = Depends(pharmacist_only), db: Session = Depends(get_db)):
    if data.supplier_id is not None:
        get_or_404(db, SupplierRow, data.supplier_id, "Supplier")
    batch = ph.receive_stock(db, user_id=user.id, **data.model_dump())
    return batch_out(batch, ph.today_local())


class AdjustIn(BaseModel):
    batch_id: int
    change: int = Field(..., examples=[-2])                  # + adds, - removes
    reason: str = Field(..., min_length=1, max_length=200, examples=["strip damaged"])
    type: MovementType = MovementType.ADJUST                # or "returned"


@router.post("/stock/adjust", response_model=BatchOut)
def adjust(data: AdjustIn, user: User = Depends(pharmacist_only), db: Session = Depends(get_db)):
    batch = ph.adjust_stock(db, user_id=user.id, batch_id=data.batch_id, change=data.change,
                            reason=data.reason, kind=data.type)
    return batch_out(batch, ph.today_local())


@router.post("/stock/write-off-expired", response_model=list[BatchOut])
def write_off(user: User = Depends(pharmacist_only), db: Session = Depends(get_db)):
    """Every expired batch goes to 0, with an "expired" line in the diary. Returns what was removed."""
    today = ph.today_local()
    # Read the quantities BEFORE they become 0, so the answer shows what was thrown away
    before = [(b, b.quantity) for b in ph.expired_batches(db, today)]
    ph.write_off_expired(db, user_id=user.id, on=today)
    return [batch_out(b, today).model_copy(update={"quantity": qty}) for b, qty in before]


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    medicine_id: int
    medicine_name: str = ""
    batch_id: int | None
    batch_no: str | None = None
    type: MovementType
    quantity: int
    reason: str
    user_id: int | None
    user_name: str | None = None
    created_at: datetime


@router.get("/stock/movements", response_model=list[MovementOut], dependencies=[Depends(pharmacist_only)])
def movements(medicine_id: int | None = None, batch_id: int | None = None,
              type: MovementType | None = None, limit: int = Query(100, ge=1, le=1000),
              db: Session = Depends(get_db)):
    query = (select(StockMovementRow, MedicineRow, MedicineBatchRow.batch_no, User.full_name)
             .join(MedicineRow, MedicineRow.id == StockMovementRow.medicine_id)
             .outerjoin(MedicineBatchRow, MedicineBatchRow.id == StockMovementRow.batch_id)
             .outerjoin(User, User.id == StockMovementRow.user_id))
    if medicine_id:
        query = query.where(StockMovementRow.medicine_id == medicine_id)
    if batch_id:
        query = query.where(StockMovementRow.batch_id == batch_id)
    if type:
        query = query.where(StockMovementRow.type == type)
    rows = db.execute(query.order_by(StockMovementRow.id.desc()).limit(limit))
    return [MovementOut.model_validate(mv).model_copy(update={
                "medicine_name": m.display_name, "batch_no": batch_no, "user_name": who})
            for mv, m, batch_no, who in rows]


class StockReportRow(BaseModel):
    medicine_id: int
    display_name: str
    brand_name: str
    generic_name: str
    strength: str
    category: str
    schedule: DrugSchedule
    in_date_units: int            # can be handed out
    expired_units: int            # still on the shelf, can't be used
    reorder_level: int
    low_stock: bool
    nearest_expiry: date | None   # of the in-date stock
    value_at_cost: Money          # in-date units × purchase price
    value_at_selling: Money       # in-date units × selling price (before GST)


class StockReport(BaseModel):
    generated_at: datetime
    medicines: int
    low_stock_count: int
    total_value_at_cost: Money
    total_value_at_selling: Money
    expired_value_at_cost: Money  # money lost to expiry, if not written off yet
    rows: list[StockReportRow]


@router.get("/stock/report", response_model=StockReport, dependencies=[Depends(pharmacist_only)])
def stock_report(category: str | None = None, db: Session = Depends(get_db)):
    today = ph.today_local()
    query = select(MedicineRow).where(MedicineRow.is_active)
    if category:
        query = query.where(MedicineRow.category == category.lower())
    rows, expired_cost = [], Decimal("0")
    for m in db.scalars(query.order_by(MedicineRow.brand_name)):
        good = [b for b in m.batches if b.quantity > 0 and not ph.is_expired(b, today)]
        bad = [b for b in m.batches if b.quantity > 0 and ph.is_expired(b, today)]
        units = sum(b.quantity for b in good)
        expired_cost += sum((b.quantity * b.purchase_price for b in bad), Decimal("0"))
        rows.append(StockReportRow(
            medicine_id=m.id, display_name=m.display_name, brand_name=m.brand_name, generic_name=m.generic_name, strength=m.strength,
            category=m.category, schedule=m.schedule, in_date_units=units,
            expired_units=sum(b.quantity for b in bad), reorder_level=m.reorder_level,
            low_stock=units <= m.reorder_level,
            nearest_expiry=min((b.expiry_date for b in good), default=None),
            value_at_cost=ph.rupees(sum((b.quantity * b.purchase_price for b in good), Decimal("0"))),
            value_at_selling=ph.rupees(sum((b.quantity * b.selling_price for b in good), Decimal("0")))))
    return StockReport(
        generated_at=ph.now_local(), medicines=len(rows), low_stock_count=sum(r.low_stock for r in rows),
        total_value_at_cost=sum((r.value_at_cost for r in rows), Decimal("0")),
        total_value_at_selling=sum((r.value_at_selling for r in rows), Decimal("0")),
        expired_value_at_cost=ph.rupees(expired_cost), rows=rows)


# =====================================================================
# Prescriptions
# =====================================================================

class PrescriptionItemIn(BaseModel):
    medicine_id: int
    dose: str = Field(..., min_length=1, max_length=20, examples=["1-0-1"])   # morning-afternoon-night
    frequency: str = Field("", max_length=50, examples=["twice a day"])
    duration_days: int = Field(..., ge=1, le=365, examples=[5])
    quantity: int = Field(..., ge=1, examples=[10])                          # total units
    instructions: str = Field("", max_length=200, examples=["after food"])


class PrescriptionIn(BaseModel):
    patient_name: str = Field(..., min_length=1, max_length=100, examples=["Asha Patel"])
    patient_id: int | None = None       # if the patient has a mediQ account
    token_id: int | None = None         # the OPD token of this visit, if any
    notes: str = Field("", max_length=500)
    items: list[PrescriptionItemIn] = Field(..., min_length=1)


class PrescriptionItemOut(PrescriptionItemIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    medicine_name: str = ""             # "Amoxil 500 mg capsule"
    schedule: DrugSchedule | None = None
    dispensed: int = 0             # units already handed out
    remaining: int = 0


class PrescriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    patient_name: str
    patient_id: int | None
    doctor_id: int
    doctor_name: str = ""
    token_id: int | None
    token_number: str | None = None
    created_at: datetime
    notes: str
    status: str = "open"           # open | partly_dispensed | dispensed
    items: list[PrescriptionItemOut]


def prescription_out(db: Session, rx: PrescriptionRow) -> PrescriptionOut:
    done = ph.already_dispensed(db, rx.id)
    items = []
    for item in rx.items:
        # If the same medicine is on the prescription twice, hand-outs fill the first line first
        given = min(done.get(item.medicine_id, 0), item.quantity)
        done[item.medicine_id] = done.get(item.medicine_id, 0) - given
        m = item.medicine
        items.append(PrescriptionItemOut.model_validate(item).model_copy(update={
            "medicine_name": f"{m.display_name} {m.dosage_form.value}", "schedule": m.schedule,
            "dispensed": given, "remaining": item.quantity - given}))
    given_total = sum(i.dispensed for i in items)
    status = ("dispensed" if all(i.remaining == 0 for i in items)
              else "partly_dispensed" if given_total else "open")
    token = db.get(TokenRow, rx.token_id) if rx.token_id else None
    return PrescriptionOut(id=rx.id, patient_name=rx.patient_name, patient_id=rx.patient_id,
                           doctor_id=rx.doctor_id, doctor_name=rx.doctor.full_name, token_id=rx.token_id,
                           token_number=token.number if token else None, created_at=rx.created_at,
                           notes=rx.notes, status=status, items=items)


@router.post("/prescriptions", response_model=PrescriptionOut, status_code=201)
def write_prescription(data: PrescriptionIn, user: User = Depends(doctor_only), db: Session = Depends(get_db)):
    """A doctor writes a prescription. It is signed with THEIR account (doctor_id = who is logged in)."""
    if data.patient_id is not None:
        patient = get_or_404(db, User, data.patient_id, "Patient")
        if patient.role != Role.PATIENT:
            raise HTTPException(status_code=400, detail=f"Account #{patient.id} is not a patient account.")
    if data.token_id is not None:
        get_or_404(db, TokenRow, data.token_id, "Token")
    rx = PrescriptionRow(patient_name=data.patient_name.strip(), patient_id=data.patient_id,
                         doctor_id=user.id, token_id=data.token_id, notes=data.notes.strip(),
                         created_at=ph.now_local())
    for item in data.items:
        m = db.get(MedicineRow, item.medicine_id)
        if m is None or not m.is_active:
            raise HTTPException(status_code=400, detail=f"Medicine #{item.medicine_id} isn't in the catalogue. "
                                                        "Search for it again and pick it from the list.")
        rx.items.append(PrescriptionItemRow(**item.model_dump()))
    db.add(rx)
    db.commit()
    return prescription_out(db, rx)


@router.get("/prescriptions", response_model=list[PrescriptionOut], dependencies=[Depends(pharmacy_readers)])
def list_prescriptions(open_only: bool = False, q: str = "", limit: int = Query(50, ge=1, le=500),
                       db: Session = Depends(get_db)):
    """Newest first. open_only=true hides prescriptions that were fully handed out."""
    query = select(PrescriptionRow)
    if q.strip():
        query = query.where(PrescriptionRow.patient_name.ilike(f"%{q.strip()}%"))
    # Read a few extra when filtering, so "open only" still fills the page
    rows = db.scalars(query.order_by(PrescriptionRow.id.desc()).limit(limit * 4 if open_only else limit))
    out = [prescription_out(db, rx) for rx in rows]
    if open_only:
        out = [p for p in out if p.status != "dispensed"]
    return out[:limit]


@router.get("/prescriptions/{prescription_id}", response_model=PrescriptionOut,
            dependencies=[Depends(pharmacy_readers)])
def get_prescription(prescription_id: int, db: Session = Depends(get_db)):
    return prescription_out(db, get_or_404(db, PrescriptionRow, prescription_id, "Prescription"))


# =====================================================================
# Dispensing and bills
# =====================================================================

class DispenseItemIn(BaseModel):
    medicine_id: int
    quantity: int = Field(..., ge=1)


class DispenseIn(BaseModel):
    """
    With a prescription and no items: hand out everything still owed on it.
    Without a prescription: an over-the-counter sale (OTC medicines only).
    """
    prescription_id: int | None = None
    items: list[DispenseItemIn] | None = None

    @model_validator(mode="after")
    def something_to_do(self):
        if self.prescription_id is None and not self.items:
            raise ValueError("Choose a prescription, or add at least one medicine.")
        return self


class BillLineOut(BaseModel):
    medicine_id: int
    medicine_name: str
    hsn_code: str
    batch_id: int
    batch_no: str
    expiry_date: date
    quantity: int
    price: Money          # per unit, before GST
    mrp: Money            # per unit
    gst_percent: Money
    amount: Money         # price × quantity
    gst: Money
    total: Money


class BillOut(BaseModel):
    id: int
    bill_number: str       # "PH-000042"
    prescription_id: int | None
    patient_name: str | None
    doctor_name: str | None
    dispensed_by: str
    dispensed_at: datetime
    lines: list[BillLineOut]
    subtotal: Money
    gst_amount: Money
    total: Money


def bill_out(db: Session, d: DispensationRow) -> BillOut:
    lines = []
    for item in d.items:
        b, m = item.batch, item.batch.medicine
        amount = ph.rupees(item.price * item.quantity)
        gst = ph.rupees(amount * item.gst_percent / 100)
        lines.append(BillLineOut(medicine_id=m.id, medicine_name=f"{m.display_name} {m.dosage_form.value}",
                                 hsn_code=m.hsn_code, batch_id=b.id, batch_no=b.batch_no,
                                 expiry_date=b.expiry_date, quantity=item.quantity, price=item.price, mrp=b.mrp,
                                 gst_percent=item.gst_percent, amount=amount, gst=gst, total=amount + gst))
    rx = db.get(PrescriptionRow, d.prescription_id) if d.prescription_id else None
    return BillOut(id=d.id, bill_number=f"PH-{d.id:06d}", prescription_id=d.prescription_id,
                   patient_name=rx.patient_name if rx else None, doctor_name=rx.doctor.full_name if rx else None,
                   dispensed_by=db.get(User, d.dispensed_by).full_name, dispensed_at=d.dispensed_at,
                   lines=lines, subtotal=d.subtotal, gst_amount=d.gst_amount, total=d.total)


@router.post("/dispense", response_model=BillOut, status_code=201)
def dispense(data: DispenseIn, user: User = Depends(pharmacist_only), db: Session = Depends(get_db)):
    """Hand out medicines: FEFO batches, no expired stock, Schedule H/H1/X need the prescription, GST bill."""
    items = [(i.medicine_id, i.quantity) for i in data.items] if data.items else None
    bill = ph.dispense(db, user_id=user.id, items=items, prescription_id=data.prescription_id)
    return bill_out(db, bill)


@router.get("/dispensations", response_model=list[BillOut], dependencies=[Depends(pharmacist_only)])
def recent_bills(prescription_id: int | None = None, limit: int = Query(20, ge=1, le=200),
                 db: Session = Depends(get_db)):
    query = select(DispensationRow)
    if prescription_id:
        query = query.where(DispensationRow.prescription_id == prescription_id)
    return [bill_out(db, d) for d in db.scalars(query.order_by(DispensationRow.id.desc()).limit(limit))]


@router.get("/dispensations/{dispensation_id}", response_model=BillOut, dependencies=[Depends(pharmacist_only)])
def get_bill(dispensation_id: int, db: Session = Depends(get_db)):
    return bill_out(db, get_or_404(db, DispensationRow, dispensation_id, "Bill"))


# =====================================================================
# Purchase orders
# =====================================================================

class POItemIn(BaseModel):
    medicine_id: int
    quantity: int = Field(..., ge=1)                    # units
    unit_price: Decimal | None = Field(None, gt=0)      # expected, per unit


class POIn(BaseModel):
    supplier_id: int
    notes: str = Field("", max_length=300)
    items: list[POItemIn] = Field(..., min_length=1)


class POItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    medicine_id: int
    medicine_name: str = ""
    quantity: int
    unit_price: Money | None


class POOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_id: int
    supplier_name: str = ""
    status: PurchaseOrderStatus
    notes: str
    created_at: datetime
    ordered_at: datetime | None
    received_at: datetime | None
    items: list[POItemOut]
    estimated_total: Money | None = None


def po_out(po: PurchaseOrderRow) -> POOut:
    items = [POItemOut.model_validate(i).model_copy(update={
        "medicine_name": i.medicine.display_name}) for i in po.items]
    priced = [i for i in po.items if i.unit_price is not None]
    total = ph.rupees(sum((i.unit_price * i.quantity for i in priced), Decimal("0"))) if priced else None
    return POOut.model_validate(po).model_copy(update={
        "supplier_name": po.supplier.name, "items": items, "estimated_total": total})


def po_or_404(db: Session, po_id: int) -> PurchaseOrderRow:
    return get_or_404(db, PurchaseOrderRow, po_id, "Purchase order")


@router.post("/purchase-orders", response_model=POOut, status_code=201)
def create_po(data: POIn, user: User = Depends(pharmacist_only), db: Session = Depends(get_db)):
    get_or_404(db, SupplierRow, data.supplier_id, "Supplier")
    po = PurchaseOrderRow(supplier_id=data.supplier_id, status=PurchaseOrderStatus.DRAFT, notes=data.notes.strip(),
                          created_by=user.id, created_at=ph.now_local())
    for item in data.items:
        m = db.get(MedicineRow, item.medicine_id)
        if m is None or not m.is_active:
            raise HTTPException(status_code=400, detail=f"Medicine #{item.medicine_id} isn't in the catalogue.")
        po.items.append(PurchaseOrderItemRow(**item.model_dump()))
    db.add(po)
    db.commit()
    return po_out(po)


@router.get("/purchase-orders", response_model=list[POOut], dependencies=[Depends(pharmacist_only)])
def list_pos(status: PurchaseOrderStatus | None = None, db: Session = Depends(get_db)):
    query = select(PurchaseOrderRow)
    if status:
        query = query.where(PurchaseOrderRow.status == status)
    return [po_out(po) for po in db.scalars(query.order_by(PurchaseOrderRow.id.desc()))]


@router.get("/purchase-orders/{po_id}", response_model=POOut, dependencies=[Depends(pharmacist_only)])
def get_po(po_id: int, db: Session = Depends(get_db)):
    return po_out(po_or_404(db, po_id))


@router.post("/purchase-orders/{po_id}/order", response_model=POOut, dependencies=[Depends(pharmacist_only)])
def mark_ordered(po_id: int, db: Session = Depends(get_db)):
    po = po_or_404(db, po_id)
    if po.status != PurchaseOrderStatus.DRAFT:
        raise HTTPException(status_code=400, detail=f"Order #{po.id} is already {po.status.value}.")
    po.status, po.ordered_at = PurchaseOrderStatus.ORDERED, ph.now_local()
    db.commit()
    return po_out(po)


class POReceiveLine(BaseModel):
    """What arrived for ONE order line. quantity defaults to what was ordered."""
    item_id: int
    batch_no: str = Field(..., min_length=1, max_length=30)
    mfg_date: date
    expiry_date: date
    quantity: int | None = Field(None, ge=1)
    purchase_price: Decimal | None = Field(None, gt=0)   # defaults to the order's unit price
    mrp: Decimal = Field(..., gt=0)
    selling_price: Decimal = Field(..., gt=0)
    rack_location: str | None = Field(None, max_length=20)


class POReceiveIn(BaseModel):
    lines: list[POReceiveLine] = Field(..., min_length=1)


@router.post("/purchase-orders/{po_id}/receive", response_model=POOut)
def receive_po(po_id: int, data: POReceiveIn, user: User = Depends(pharmacist_only),
               db: Session = Depends(get_db)):
    """The delivery arrived: every line becomes a batch. All lines are saved together or none."""
    po = po_or_404(db, po_id)
    if po.status != PurchaseOrderStatus.ORDERED:
        raise HTTPException(status_code=400, detail=f"Order #{po.id} is {po.status.value}; only an ordered "
                                                    "purchase order can be received.")
    items = {i.id: i for i in po.items}
    if {line.item_id for line in data.lines} != set(items):
        raise HTTPException(status_code=400, detail="Give batch details for every line of the order, once each.")
    if len(data.lines) != len(items):
        raise HTTPException(status_code=400, detail="Each order line can only be received once.")
    try:
        for line in data.lines:
            item = items[line.item_id]
            price = line.purchase_price or item.unit_price
            if price is None:
                raise PharmacyError(f"Enter the purchase price for {item.medicine.brand_name}.")
            ph.receive_stock(db, user_id=user.id, medicine_id=item.medicine_id, supplier_id=po.supplier_id,
                             batch_no=line.batch_no, mfg_date=line.mfg_date, expiry_date=line.expiry_date,
                             quantity=line.quantity or item.quantity, purchase_price=price, mrp=line.mrp,
                             selling_price=line.selling_price, rack_location=line.rack_location, commit=False)
        po.status, po.received_at = PurchaseOrderStatus.RECEIVED, ph.now_local()
        db.commit()
    except Exception:
        db.rollback()   # one bad line: none of the batches are saved
        raise
    return po_out(po)


@router.delete("/purchase-orders/{po_id}", status_code=204, dependencies=[Depends(pharmacist_only)])
def delete_draft(po_id: int, db: Session = Depends(get_db)):
    po = po_or_404(db, po_id)
    if po.status != PurchaseOrderStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Only draft orders can be deleted; this one was already sent.")
    db.delete(po)
    db.commit()


# =====================================================================
# Alerts
# =====================================================================

class LowStockAlert(BaseModel):
    medicine_id: int
    medicine_name: str
    stock: int
    reorder_level: int


class ExpiryAlert(BaseModel):
    batch_id: int
    medicine_id: int
    medicine_name: str
    batch_no: str
    expiry_date: date
    days_left: int        # negative = expired that many days ago
    window: int | None    # 30, 60 or 90: the first window it falls in (None if already expired)
    quantity: int
    value_at_cost: Money
    rack_location: str | None


class AlertsOut(BaseModel):
    low_stock: list[LowStockAlert]
    expiring: list[ExpiryAlert]    # within 90 days, soonest first; filter by `window`
    expired: list[ExpiryAlert]
    counts: dict[str, int]         # {"low_stock", "expiring_30", "expiring_60", "expiring_90", "expired"}


def expiry_alert(b: MedicineBatchRow, today: date) -> ExpiryAlert:
    days = (b.expiry_date - today).days
    window = None if days <= 0 else 30 if days <= 30 else 60 if days <= 60 else 90
    return ExpiryAlert(batch_id=b.id, medicine_id=b.medicine_id,
                       medicine_name=b.medicine.display_name, batch_no=b.batch_no,
                       expiry_date=b.expiry_date, days_left=days, window=window, quantity=b.quantity,
                       value_at_cost=ph.rupees(b.quantity * b.purchase_price), rack_location=b.rack_location)


@router.get("/alerts", response_model=AlertsOut, dependencies=[Depends(pharmacy_readers)])
def alerts(db: Session = Depends(get_db)):
    today = ph.today_local()
    low = [LowStockAlert(medicine_id=m.id, medicine_name=m.display_name, stock=stock,
                         reorder_level=m.reorder_level) for m, stock in ph.low_stock(db, today)]
    expiring = [expiry_alert(b, today) for b in ph.expiring_within(db, 90, today)]
    expired = [expiry_alert(b, today) for b in ph.expired_batches(db, today)]
    counts = {"low_stock": len(low), "expired": len(expired)}
    for days in (30, 60, 90):
        counts[f"expiring_{days}"] = sum(a.days_left <= days for a in expiring)   # 60 includes the 30s
    return AlertsOut(low_stock=low, expiring=expiring, expired=expired, counts=counts)
