"""
Database tables, written as Python classes (SQLAlchemy "ORM models").

Don't mix these up with models.py:
    models.py     Pydantic: the SHAPE of JSON going in and out of the API
    db_models.py  SQLAlchemy: the TABLES stored in the database

One class = one table, one attribute = one column. Changing a class here does
NOT change the database by itself: you also make a migration (see LEARN.md).
"""

import enum
import re
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Time,
                        UniqueConstraint, text, true)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .models import (ACTIVE_APPOINTMENT_STATUSES, AmbulanceStatus, AppointmentSource, AppointmentStatus, CallbackStatus, DosageForm, DrugSchedule, MovementType,
                     PurchaseOrderStatus, StorageType, TokenStatus, TripStatus)


class Role(str, enum.Enum):
    """What a user is allowed to do. New sign-ups are always patients.
    (There was a "receptionist" role; it was removed when patients started
    booking for themselves. Migration 0008 turned receptionists into admins.)"""
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"
    PHARMACIST = "pharmacist"     # Module 4: runs the pharmacy counter and the stock


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)          # 1, 2, 3... given by the database
    full_name: Mapped[str] = mapped_column(String(100))
    # unique=True: the DATABASE itself refuses a second account with the same email
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20))      # optional ("| None")
    # Never the real password: a one-way scrambled version (bcrypt, added in step 2)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        # Stored as plain text ("doctor"), and the database refuses any other value.
        Enum(Role, native_enum=False, length=20, create_constraint=True, name="user_role",
             values_callable=lambda roles: [r.value for r in roles]),
        default=Role.PATIENT,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    # Doctors only (ignored for other roles): accept bookings automatically?
    # Off = each booking waits as "requested" until the doctor accepts it.
    # server_default: existing rows get "true" when the column is added.
    auto_accept: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    def __repr__(self) -> str:  # how a User prints while debugging
        return f"<User {self.id} {self.email} ({self.role.value})>"


class RevokedToken(Base):
    """
    Login tokens that were logged out before they expired.

    A JWT is valid until its expiry time on its own; the server can't "take it
    back". So on logout we write down its unique id (jti) here, and every request
    checks this list. Rows can be deleted once the token would have expired anyway.
    """
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class OpdSlot(Base):
    """
    One weekly OPD session of a doctor, e.g.
        Dr. Meera Rao, General Medicine, Room 2, every Monday 09:00-13:00

    weekday: 0 = Monday ... 6 = Sunday (Python's datetime.weekday() numbering).
    Times are hospital local time (HOSPITAL_TIMEZONE). Sessions can't cross
    midnight: a night shift is two sessions (22:00-23:59 and 00:00-06:00).
    """
    __tablename__ = "opd_slots"
    __table_args__ = (
        # The database itself refuses impossible rows.
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_opd_slots_weekday"),
        CheckConstraint("start_time < end_time", name="ck_opd_slots_start_before_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # A FOREIGN KEY: must be the id of a row in users. Delete the user and their
    # sessions go too (CASCADE).
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Departments still live in memory (store.py), so this is a plain number for now.
    department_id: Mapped[int] = mapped_column(index=True)
    weekday: Mapped[int]
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    room: Mapped[int]

    # slot.doctor gives the User object (SQLAlchemy looks it up for us).
    doctor: Mapped[User] = relationship()


# =====================================================================
# Data that used to live in Python memory (lost on every restart).
# The names end in "Row" so they don't clash with the Pydantic models of the
# same idea in models.py (Department, Token...): a Row is what's SAVED, the
# Pydantic model is what the API SENDS.
# =====================================================================

def _enum(enum_cls, name: str) -> Enum:
    """Store an Enum as plain text ("waiting"); the database refuses other values."""
    return Enum(enum_cls, native_enum=False, length=20, create_constraint=True, name=name,
                values_callable=lambda members: [m.value for m in members])


class DepartmentRow(Base):
    """An OPD department (was store.departments)."""
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(5), unique=True)      # GEN, PED...
    name: Mapped[str] = mapped_column(String(100))
    doctors: Mapped[int]                                           # rooms working in parallel (c)
    avg_consult_minutes: Mapped[float]
    expected_patients_per_hour: Mapped[float]


class TokenRow(Base):
    """One patient in the OPD queue (was store.tokens)."""
    __tablename__ = "tokens"
    __table_args__ = (
        # GEN-007 can only exist once per department
        UniqueConstraint("department_id", "seq", name="uq_tokens_department_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    seq: Mapped[int]                                   # 7 in GEN-007
    number: Mapped[str] = mapped_column(String(20))    # "GEN-007"
    patient_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[TokenStatus] = mapped_column(_enum(TokenStatus, "token_status"), index=True)
    room: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    called_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Module 5: a booked token is queued by its appointment's slot time, then priority.
    # Tokens without an appointment use created_at instead (see store.QUEUE_ORDER).
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    priority: Mapped[int] = mapped_column(default=0, server_default="0")


class WardRow(Base):
    """A hospital ward (Module 1, was bed_store.wards)."""
    __tablename__ = "wards"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # ward.beds: its beds in number order. Deleting a ward deletes its beds.
    beds: Mapped[list["BedRow"]] = relationship(order_by="BedRow.number", cascade="all, delete-orphan")


class BedRow(Base):
    """One numbered bed. Free when patient_name is empty."""
    __tablename__ = "beds"
    __table_args__ = (UniqueConstraint("ward_id", "number", name="uq_beds_ward_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ward_id: Mapped[int] = mapped_column(ForeignKey("wards.id", ondelete="CASCADE"), index=True)
    number: Mapped[int]
    patient_name: Mapped[str | None] = mapped_column(String(100))
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime)

    @property
    def occupied(self) -> bool:
        return self.patient_name is not None


class EnquiryRow(Base):
    """A "Quick enquiry" from the home page (was website.enquiries)."""
    __tablename__ = "enquiries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    country_code: Mapped[str] = mapped_column(String(6))
    mobile: Mapped[str] = mapped_column(String(15))
    speciality: Mapped[str] = mapped_column(String(100))
    consent: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime)


class CallbackRow(Base):
    """A "Request Call Back" (was callback.callbacks)."""
    __tablename__ = "callback_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    mobile: Mapped[str] = mapped_column(String(15), index=True)     # +91XXXXXXXXXX
    status: Mapped[CallbackStatus] = mapped_column(_enum(CallbackStatus, "callback_status"))
    note: Mapped[str] = mapped_column(String(300), default="")
    call_sid: Mapped[str | None] = mapped_column(String(64))
    dry_run: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


# =====================================================================
# Module 3: Ambulance
# =====================================================================

class AmbulanceRow(Base):
    """One ambulance, its driver and where it is."""
    __tablename__ = "ambulances"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)        # AMB-01
    vehicle_number: Mapped[str] = mapped_column(String(20))
    driver_name: Mapped[str] = mapped_column(String(100))
    driver_phone: Mapped[str] = mapped_column(String(15))             # +91XXXXXXXXXX
    status: Mapped[AmbulanceStatus] = mapped_column(_enum(AmbulanceStatus, "ambulance_status"), index=True)
    location: Mapped[str] = mapped_column(String(200))               # plain text, e.g. "Hospital bay 2"
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TripRow(Base):
    """One request for an ambulance, from "requested" to "completed"."""
    __tablename__ = "ambulance_trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Empty until an ambulance is assigned
    ambulance_id: Mapped[int | None] = mapped_column(ForeignKey("ambulances.id"), index=True)
    patient_name: Mapped[str] = mapped_column(String(100))
    contact_phone: Mapped[str] = mapped_column(String(15))
    pickup: Mapped[str] = mapped_column(String(200))
    destination: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[TripStatus] = mapped_column(_enum(TripStatus, "trip_status"), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)   # completed or cancelled

    ambulance: Mapped[AmbulanceRow | None] = relationship()


# =====================================================================
# Module 4: Pharmacy
#
# How the tables fit together:
#
#   suppliers ──< medicine_batches >── medicines        a batch = one delivery of one medicine
#                        │                  │
#                        │                  └──< prescription_items >── prescriptions (doctor writes)
#                        │                                                    │
#                        └──< dispensation_items >── dispensations ───────────┘ (pharmacy hands out)
#
#   stock_movements: a diary line for EVERY change to a batch's quantity
#   purchase_orders ──< purchase_order_items: what we asked a supplier for
#
# ("──<" means "one ... has many ...")
#
# Money: Numeric(10, 2) stores exact rupees and paise (12.35), read back as
# Python's Decimal. A float could turn 12.35 into 12.3499999 and bills would be wrong.
# =====================================================================

Money = Numeric(10, 2)


class MedicineRow(Base):
    """One product on the catalogue, e.g. "Dolo 650, Paracetamol 650 mg tablet"."""
    __tablename__ = "medicines"
    __table_args__ = (
        UniqueConstraint("brand_name", "strength", "dosage_form", name="uq_medicines_brand_strength_form"),
        CheckConstraint("gst_percent >= 0 AND gst_percent <= 28", name="ck_medicines_gst"),
        CheckConstraint("pack_size >= 1", name="ck_medicines_pack_size"),
        CheckConstraint("reorder_level >= 0", name="ck_medicines_reorder_level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_name: Mapped[str] = mapped_column(String(100), index=True)       # Dolo 650
    generic_name: Mapped[str] = mapped_column(String(200), index=True)     # Paracetamol (the salt)
    strength: Mapped[str] = mapped_column(String(50))                      # 650 mg, 5 mg/5 ml
    dosage_form: Mapped[DosageForm] = mapped_column(_enum(DosageForm, "dosage_form"))
    category: Mapped[str] = mapped_column(String(50), index=True)          # analgesic, antibiotic...
    schedule: Mapped[DrugSchedule] = mapped_column(_enum(DrugSchedule, "drug_schedule"))
    manufacturer: Mapped[str] = mapped_column(String(100))
    hsn_code: Mapped[str] = mapped_column(String(10))                      # tax code; 3004 = medicines
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))            # usually 5 or 12
    pack_size: Mapped[int]                                                 # 10 tablets in a strip
    unit: Mapped[str] = mapped_column(String(20))                          # tablet, ml, vial...
    storage: Mapped[StorageType] = mapped_column(_enum(StorageType, "storage_type"))
    prescription_required: Mapped[bool] = mapped_column(Boolean)
    reorder_level: Mapped[int]               # warn when stock (in units) falls to this or below
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)   # "deleted" medicines are just hidden

    @property
    def display_name(self) -> str:
        """
        The name people read: "Dolo 650" (the brand already says 650 mg) or
        "Crocin Advance 500 mg". Avoids "Dolo 650 650 mg".
        """
        number = re.match(r"[\d.]+", self.strength)   # "650" from "650 mg"
        if number and re.search(rf"(?<![\d.]){re.escape(number.group())}(?![\d.])", self.brand_name):
            return self.brand_name
        return f"{self.brand_name} {self.strength}"

    # medicine.batches: every delivery of this medicine, soonest expiry first (FEFO order)
    batches: Mapped[list["MedicineBatchRow"]] = relationship(
        back_populates="medicine", order_by="MedicineBatchRow.expiry_date")


class SupplierRow(Base):
    """A wholesaler or distributor we buy from."""
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    gstin: Mapped[str | None] = mapped_column(String(15))            # 15-character GST number
    drug_license_no: Mapped[str | None] = mapped_column(String(50))  # wholesalers must have one
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(300))


class MedicineBatchRow(Base):
    """
    One delivery of one medicine with one batch number and one expiry date.
    quantity is what is LEFT on the shelf, in units (tablets, ml...).
    """
    __tablename__ = "medicine_batches"
    __table_args__ = (
        UniqueConstraint("medicine_id", "batch_no", name="uq_medicine_batches_medicine_batch_no"),
        CheckConstraint("quantity >= 0", name="ck_medicine_batches_quantity"),   # never negative stock
        CheckConstraint("mfg_date < expiry_date", name="ck_medicine_batches_dates"),
        CheckConstraint("selling_price <= mrp", name="ck_medicine_batches_price_le_mrp"),  # by law
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
    batch_no: Mapped[str] = mapped_column(String(30))
    mfg_date: Mapped[date] = mapped_column(Date)
    expiry_date: Mapped[date] = mapped_column(Date, index=True)
    quantity: Mapped[int]
    purchase_price: Mapped[Decimal] = mapped_column(Money)   # what we paid, per unit
    mrp: Mapped[Decimal] = mapped_column(Money)              # maximum retail price, per unit
    selling_price: Mapped[Decimal] = mapped_column(Money)    # what the patient pays, per unit (before GST)
    received_at: Mapped[datetime] = mapped_column(DateTime)
    rack_location: Mapped[str | None] = mapped_column(String(20))   # e.g. "A3-2"

    medicine: Mapped[MedicineRow] = relationship(back_populates="batches")
    supplier: Mapped[SupplierRow | None] = relationship()


class PurchaseOrderRow(Base):
    """An order to a supplier: draft -> ordered -> received."""
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    status: Mapped[PurchaseOrderStatus] = mapped_column(_enum(PurchaseOrderStatus, "po_status"), index=True)
    notes: Mapped[str] = mapped_column(String(300), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)

    supplier: Mapped[SupplierRow] = relationship()
    items: Mapped[list["PurchaseOrderItemRow"]] = relationship(cascade="all, delete-orphan")


class PurchaseOrderItemRow(Base):
    """One line of a purchase order: "Dolo 650 × 500 tablets at ₹1.50"."""
    __tablename__ = "purchase_order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_purchase_order_items_quantity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"))
    quantity: Mapped[int]                                    # units
    unit_price: Mapped[Decimal | None] = mapped_column(Money)   # expected price per unit, if known

    medicine: Mapped[MedicineRow] = relationship()


class PrescriptionRow(Base):
    """
    What a doctor prescribed. Walk-in OPD patients don't have a mediQ account,
    so patient_id is optional and patient_name is always filled in.
    """
    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)  # if they have an account
    patient_name: Mapped[str] = mapped_column(String(100))
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_id: Mapped[int | None] = mapped_column(ForeignKey("tokens.id"), index=True)   # the OPD visit, if any
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    notes: Mapped[str] = mapped_column(String(500), default="")

    doctor: Mapped[User] = relationship(foreign_keys=[doctor_id])
    items: Mapped[list["PrescriptionItemRow"]] = relationship(cascade="all, delete-orphan")


class PrescriptionItemRow(Base):
    """One medicine on a prescription: "Amoxicillin 500, 1-0-1, 5 days, after food"."""
    __tablename__ = "prescription_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_prescription_items_quantity"),
        CheckConstraint("duration_days > 0", name="ck_prescription_items_duration"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescriptions.id", ondelete="CASCADE"), index=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"))
    dose: Mapped[str] = mapped_column(String(20))            # 1-0-1 = morning, (no afternoon), night
    frequency: Mapped[str] = mapped_column(String(50))       # "twice a day"
    duration_days: Mapped[int]
    quantity: Mapped[int]                                    # total units to hand out
    instructions: Mapped[str] = mapped_column(String(200), default="")   # "after food"

    medicine: Mapped[MedicineRow] = relationship()


class DispensationRow(Base):
    """
    One visit to the pharmacy counter = one bill. The totals are SAVED (not
    recalculated later) so an old bill never changes if prices or GST change.
    """
    __tablename__ = "dispensations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Empty for an over-the-counter sale (OTC medicines only)
    prescription_id: Mapped[int | None] = mapped_column(ForeignKey("prescriptions.id"), index=True)
    dispensed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    dispensed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    subtotal: Mapped[Decimal] = mapped_column(Money)        # before GST
    gst_amount: Mapped[Decimal] = mapped_column(Money)
    total: Mapped[Decimal] = mapped_column(Money)           # what the patient pays

    items: Mapped[list["DispensationItemRow"]] = relationship(cascade="all, delete-orphan")


class DispensationItemRow(Base):
    """One bill line: so many units from ONE batch. Two batches of the same medicine = two lines."""
    __tablename__ = "dispensation_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_dispensation_items_quantity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dispensation_id: Mapped[int] = mapped_column(ForeignKey("dispensations.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("medicine_batches.id"), index=True)
    quantity: Mapped[int]
    price: Mapped[Decimal] = mapped_column(Money)                 # per unit, before GST, at the time of sale
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))   # copied at the time of sale

    batch: Mapped[MedicineBatchRow] = relationship()


class StockMovementRow(Base):
    """
    The stock diary. Every time any batch's quantity changes, one line is
    written here, so you can always answer "where did these 20 tablets go?".

    quantity is the CHANGE, with a sign: +100 received, -10 dispensed,
    -5 expired. Adding up a batch's movements gives its current quantity.
    """
    __tablename__ = "stock_movements"
    __table_args__ = (CheckConstraint("quantity != 0", name="ck_stock_movements_nonzero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("medicine_batches.id"), index=True)
    type: Mapped[MovementType] = mapped_column(_enum(MovementType, "movement_type"), index=True)
    quantity: Mapped[int]
    reason: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))   # who did it (empty = the system/seed)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)


# =====================================================================
# Module 5: Patient self-booking (appointments)
# =====================================================================

# SQL for "this booking still holds its slot" (ACTIVE_APPOINTMENT_STATUSES in models.py)
ACTIVE_SQL = "status IN (" + ", ".join(f"'{s.value}'" for s in ACTIVE_APPOINTMENT_STATUSES) + ")"


class AppointmentRow(Base):
    """
    One booked slot with one doctor, e.g. Asha Patel with Dr. Rao,
    Tue 2 Dec, 10:20-10:30, "fever for 3 days".

    Two rules are kept by the DATABASE itself, with "partial unique indexes"
    (unique, but only among rows that match a WHERE):
      - a doctor's slot can be held by only one active booking (no double booking)
      - a patient can hold only one active booking per doctor per day
    Cancelled / rejected / finished bookings don't count, so the slot frees up.
    """
    __tablename__ = "appointments"
    __table_args__ = (
        Index("uq_appointments_doctor_slot", "doctor_id", "date", "slot_start", unique=True,
              sqlite_where=text(ACTIVE_SQL), postgresql_where=text(ACTIVE_SQL)),
        Index("uq_appointments_patient_doctor_day", "patient_id", "doctor_id", "date", unique=True,
              sqlite_where=text(ACTIVE_SQL), postgresql_where=text(ACTIVE_SQL)),
        CheckConstraint("slot_start < slot_end", name="ck_appointments_slot_order"),
        CheckConstraint("status != 'rejected' OR reject_reason IS NOT NULL", name="ck_appointments_reject_reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # The patient's account. Empty for a walk-in without an account (patient_name is always set).
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    patient_name: Mapped[str] = mapped_column(String(100))
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)            # hospital-local date
    slot_start: Mapped[time] = mapped_column(Time)                  # 10:20
    slot_end: Mapped[time] = mapped_column(Time)                    # 10:30
    reason: Mapped[str] = mapped_column(String(500), default="")    # symptoms, in the patient's words
    status: Mapped[AppointmentStatus] = mapped_column(_enum(AppointmentStatus, "appointment_status"), index=True)
    source: Mapped[AppointmentSource] = mapped_column(_enum(AppointmentSource, "appointment_source"),
                                                      default=AppointmentSource.ONLINE)
    priority: Mapped[int] = mapped_column(default=0)    # higher = seen sooner among the same slot time
    # The queue token (GEN-012) made for this booking; empty until accepted
    token_id: Mapped[int | None] = mapped_column(ForeignKey("tokens.id"), unique=True)
    reject_reason: Mapped[str | None] = mapped_column(String(300))
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)

    patient: Mapped[User | None] = relationship(foreign_keys=[patient_id])
    doctor: Mapped[User] = relationship(foreign_keys=[doctor_id])
    department: Mapped[DepartmentRow] = relationship()
    token: Mapped[TokenRow | None] = relationship()


class NotificationRow(Base):
    """
    One message for one user, e.g. "Dr. Rao accepted your booking for Tue 2 Dec,
    10:20. Your token is GEN-012." Shown as a banner until the user dismisses it
    (read_at). The same text goes to the SMS hook (services/sms.py).
    """
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"), index=True)
    event: Mapped[str] = mapped_column(String(30))         # "accepted", "rejected", "called"...
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
