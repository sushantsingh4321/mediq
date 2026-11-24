"""
Pharmacy rules (Module 4). Plain functions: the API (step 3) calls these.

The rules, in plain words:

  1. FEFO, "First Expiry, First Out": when handing out a medicine, take it
     from the batch that expires SOONEST. Older stock leaves the shelf before
     it can go off.
  2. Never hand out an expired batch. A batch counts as expired ON its expiry
     date (to be safe, it must expire AFTER today to be used).
  3. Schedule H, H1 and X medicines (and anything marked
     prescription_required) need a doctor's prescription. Only OTC medicines
     can be sold without one.
  4. Every change to stock writes one line in stock_movements (the diary).
  5. The bill adds GST per line: amount = price × quantity, GST = amount × GST%.

Every function that changes stock does ALL its checks first and only then
changes anything, so a failed request never leaves half a bill behind.

Errors are PharmacyError with a message saying what went wrong and how to fix
it. The API turns them into a 400 response with that message.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db_models import (DispensationItemRow, DispensationRow, MedicineBatchRow, MedicineRow,
                         PrescriptionRow, StockMovementRow)
from ..models import DrugSchedule, MovementType

PAISA = Decimal("0.01")


class PharmacyError(Exception):
    """A rule was broken. str(error) is a message a person can act on."""


# ---------------------------------------------------------------- time and money

def now_local() -> datetime:
    """Hospital time, without the timezone attached (that's how the tables store it)."""
    return datetime.now(ZoneInfo(get_settings().hospital_timezone)).replace(tzinfo=None)


def today_local() -> date:
    return now_local().date()


def percent(value: Decimal) -> str:
    """Decimal("12.00") -> "12", Decimal("2.50") -> "2.5" (for messages)."""
    return f"{Decimal(value).normalize():f}"


def rupees(amount: Decimal) -> Decimal:
    """Round to whole paise the way a bill does: 2.345 -> 2.35 (half goes UP)."""
    return Decimal(amount).quantize(PAISA, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- rule 2: expiry

def is_expired(batch: MedicineBatchRow, on: date) -> bool:
    """Expired on or before `on`. A batch expiring today is NOT handed out today."""
    return batch.expiry_date <= on


def usable_batches(db: Session, medicine_id: int, on: date) -> list[MedicineBatchRow]:
    """Batches we may hand out: some left, not expired, in FEFO order (soonest expiry first)."""
    return list(db.scalars(
        select(MedicineBatchRow)
        .where(MedicineBatchRow.medicine_id == medicine_id,
               MedicineBatchRow.quantity > 0,
               MedicineBatchRow.expiry_date > on)
        .order_by(MedicineBatchRow.expiry_date, MedicineBatchRow.id)   # id: tie-break, oldest delivery first
    ))


def stock_on_hand(db: Session, medicine_id: int, on: date) -> int:
    """Units we can actually hand out (expired stock doesn't count)."""
    return sum(b.quantity for b in usable_batches(db, medicine_id, on))


# ---------------------------------------------------------------- rule 1: FEFO

def pick_batches_fefo(db: Session, medicine: MedicineRow, quantity: int, on: date
                      ) -> list[tuple[MedicineBatchRow, int]]:
    """
    Decide which batches to take `quantity` units from, soonest expiry first.
    Returns [(batch, units_to_take), ...]. Changes nothing.

    Example: need 15, batches A (expires March, 10 left) and B (June, 50 left)
             -> [(A, 10), (B, 5)]
    """
    picks, still_needed = [], quantity
    for batch in usable_batches(db, medicine.id, on):
        take = min(batch.quantity, still_needed)
        picks.append((batch, take))
        still_needed -= take
        if still_needed == 0:
            return picks

    have = quantity - still_needed
    message = (f"Not enough {medicine.display_name}: {quantity} {medicine.unit}(s) "
               f"needed, {have} in date.")
    expired_left = db.scalar(select(func.coalesce(func.sum(MedicineBatchRow.quantity), 0)).where(
        MedicineBatchRow.medicine_id == medicine.id, MedicineBatchRow.quantity > 0,
        MedicineBatchRow.expiry_date <= on))
    if expired_left:
        message += f" {expired_left} more are expired and can't be used."
    raise PharmacyError(message + " Receive new stock, or dispense fewer.")


# ---------------------------------------------------------------- rule 3: prescriptions

def needs_prescription(medicine: MedicineRow) -> bool:
    return medicine.prescription_required or medicine.schedule != DrugSchedule.OTC


def already_dispensed(db: Session, prescription_id: int) -> dict[int, int]:
    """{medicine_id: units already handed out} for one prescription (it may be filled in parts)."""
    rows = db.execute(
        select(MedicineBatchRow.medicine_id, func.sum(DispensationItemRow.quantity))
        .join(DispensationItemRow.batch)
        .join(DispensationRow, DispensationRow.id == DispensationItemRow.dispensation_id)
        .where(DispensationRow.prescription_id == prescription_id)
        .group_by(MedicineBatchRow.medicine_id))
    return {medicine_id: int(total) for medicine_id, total in rows}


def remaining_on_prescription(db: Session, prescription: PrescriptionRow) -> dict[int, int]:
    """{medicine_id: units still to hand out} = prescribed - already dispensed."""
    prescribed: dict[int, int] = defaultdict(int)
    for item in prescription.items:
        prescribed[item.medicine_id] += item.quantity
    done = already_dispensed(db, prescription.id)
    return {mid: qty - done.get(mid, 0) for mid, qty in prescribed.items()}


# ---------------------------------------------------------------- rule 4: the stock diary

def log_movement(db: Session, batch: MedicineBatchRow, change: int, kind: MovementType,
                 reason: str, user_id: int | None, when: datetime) -> None:
    """Write one diary line. `change` has a sign: +100 in, -10 out."""
    db.add(StockMovementRow(medicine_id=batch.medicine_id, batch_id=batch.id, type=kind,
                            quantity=change, reason=reason, user_id=user_id, created_at=when))


# ---------------------------------------------------------------- receiving stock

def receive_stock(db: Session, *, user_id: int | None, medicine_id: int, batch_no: str,
                  mfg_date: date, expiry_date: date, quantity: int, purchase_price: Decimal,
                  mrp: Decimal, selling_price: Decimal, supplier_id: int | None = None,
                  rack_location: str | None = None, on: date | None = None,
                  commit: bool = True) -> MedicineBatchRow:
    """
    A delivery arrives: create the batch and write an "in" line in the diary.
    commit=False lets a purchase order receive several batches and save them
    together (all or nothing).
    """
    on = on or today_local()
    medicine = db.get(MedicineRow, medicine_id)
    if medicine is None or not medicine.is_active:
        raise PharmacyError("That medicine isn't in the catalogue. Add it first, then receive stock.")
    batch_no = batch_no.strip().upper()
    if quantity <= 0:
        raise PharmacyError("Quantity must be at least 1 unit.")
    if expiry_date <= on:
        raise PharmacyError(f"Batch {batch_no} expires on {expiry_date:%d %b %Y}, which isn't after today. "
                            "Don't accept expired stock: return it to the supplier.")
    if mfg_date >= expiry_date:
        raise PharmacyError("The manufacturing date must be before the expiry date. Check the strip.")
    if mfg_date > on:
        raise PharmacyError("The manufacturing date is in the future. Check the date on the strip.")
    mrp, selling_price, purchase_price = rupees(mrp), rupees(selling_price), rupees(purchase_price)
    if min(mrp, selling_price, purchase_price) <= 0:
        raise PharmacyError("Prices must be more than ₹0.")
    # In India MRP includes all taxes, so the price WITH GST may not go above it.
    with_gst = rupees(selling_price * (1 + medicine.gst_percent / 100))
    if with_gst > mrp:
        raise PharmacyError(f"Selling price ₹{selling_price} + {percent(medicine.gst_percent)}% GST = ₹{with_gst}, "
                            f"which is above the MRP of ₹{mrp}. Lower the selling price.")
    duplicate = db.scalar(select(MedicineBatchRow).where(
        MedicineBatchRow.medicine_id == medicine_id, MedicineBatchRow.batch_no == batch_no))
    if duplicate is not None:
        raise PharmacyError(f"Batch {batch_no} of {medicine.display_name} was already received. "
                            "To change its count, use a stock adjustment.")

    when = now_local()
    batch = MedicineBatchRow(medicine_id=medicine_id, supplier_id=supplier_id, batch_no=batch_no,
                             mfg_date=mfg_date, expiry_date=expiry_date, quantity=quantity,
                             purchase_price=purchase_price, mrp=mrp, selling_price=selling_price,
                             received_at=when, rack_location=rack_location)
    db.add(batch)
    db.flush()   # ask the database for batch.id now, so the diary line can point to it
    log_movement(db, batch, +quantity, MovementType.IN, f"Received batch {batch_no}", user_id, when)
    if commit:
        db.commit()
    return batch


# ---------------------------------------------------------------- dispensing (rules 1-5 together)

@dataclass
class BillLine:
    medicine: MedicineRow
    batch: MedicineBatchRow
    quantity: int
    price: Decimal          # per unit, before GST
    gst_percent: Decimal

    @property
    def amount(self) -> Decimal:
        return rupees(self.price * self.quantity)

    @property
    def gst(self) -> Decimal:
        return rupees(self.amount * self.gst_percent / 100)


def dispense(db: Session, *, user_id: int, items: list[tuple[int, int]] | None = None,
             prescription_id: int | None = None, on: date | None = None) -> DispensationRow:
    """
    Hand out medicines and make the bill.

      items            [(medicine_id, quantity), ...]. With a prescription you may
                       leave it out: everything still owed on the prescription is used.
      prescription_id  needed if ANY item is Schedule H/H1/X or prescription_required.

    Returns the saved DispensationRow (with .items, .subtotal, .gst_amount, .total).
    """
    on = on or today_local()

    # --- which prescription, and what it still allows ---
    prescription, remaining = None, {}
    if prescription_id is not None:
        prescription = db.get(PrescriptionRow, prescription_id)
        if prescription is None:
            raise PharmacyError(f"Prescription #{prescription_id} doesn't exist. Check the number.")
        remaining = remaining_on_prescription(db, prescription)
        if items is None:
            items = [(mid, qty) for mid, qty in remaining.items() if qty > 0]
            if not items:
                raise PharmacyError(f"Everything on prescription #{prescription_id} was already dispensed.")
    if not items:
        raise PharmacyError("Add at least one medicine to dispense.")

    # Same medicine listed twice? Add the quantities together first.
    wanted: dict[int, int] = defaultdict(int)
    for medicine_id, quantity in items:
        if quantity <= 0:
            raise PharmacyError("Each quantity must be at least 1.")
        wanted[medicine_id] += quantity

    # --- 1. check everything (nothing is changed yet) ---
    lines: list[BillLine] = []
    for medicine_id, quantity in wanted.items():
        medicine = db.get(MedicineRow, medicine_id)
        if medicine is None or not medicine.is_active:
            raise PharmacyError(f"Medicine #{medicine_id} isn't in the catalogue.")
        name = medicine.display_name
        if prescription is None and needs_prescription(medicine):
            raise PharmacyError(f"{name} is a Schedule {medicine.schedule.value} medicine and needs a "
                                "doctor's prescription. Choose the patient's prescription, or remove it.")
        if prescription is not None:
            if medicine_id not in remaining:
                raise PharmacyError(f"{name} isn't on prescription #{prescription.id}. "
                                    "Ask the doctor to add it, or remove it from this bill.")
            if quantity > remaining[medicine_id]:
                raise PharmacyError(f"Prescription #{prescription.id} allows {remaining[medicine_id]} more "
                                    f"{medicine.unit}(s) of {name}, not {quantity}.")
        for batch, take in pick_batches_fefo(db, medicine, quantity, on):
            lines.append(BillLine(medicine, batch, take, batch.selling_price, medicine.gst_percent))

    # --- 2. all checks passed: change the stock, write the diary and the bill ---
    when = now_local()
    subtotal = sum((line.amount for line in lines), Decimal("0"))
    gst_amount = sum((line.gst for line in lines), Decimal("0"))
    bill = DispensationRow(prescription_id=prescription_id, dispensed_by=user_id, dispensed_at=when,
                           subtotal=subtotal, gst_amount=gst_amount, total=subtotal + gst_amount)
    for line in lines:
        line.batch.quantity -= line.quantity
        bill.items.append(DispensationItemRow(batch_id=line.batch.id, quantity=line.quantity,
                                              price=line.price, gst_percent=line.gst_percent))
    db.add(bill)
    db.flush()   # gives bill.id for the diary reason
    for line in lines:
        log_movement(db, line.batch, -line.quantity, MovementType.OUT, f"Dispensed, bill #{bill.id}",
                     user_id, when)
    db.commit()
    return bill


# ---------------------------------------------------------------- other stock changes

def adjust_stock(db: Session, *, user_id: int | None, batch_id: int, change: int, reason: str,
                 kind: MovementType = MovementType.ADJUST) -> MedicineBatchRow:
    """
    Correct a batch's count (+ or -), e.g. "-2, strip damaged" or "+5, returned by ward".
    kind is ADJUST or RETURNED. A reason is required: the diary must explain every change.
    """
    if kind not in (MovementType.ADJUST, MovementType.RETURNED):
        raise PharmacyError("Use receive stock for new deliveries and dispense for patients.")
    batch = db.get(MedicineBatchRow, batch_id)
    if batch is None:
        raise PharmacyError(f"Batch #{batch_id} doesn't exist.")
    if change == 0:
        raise PharmacyError("The change can't be 0.")
    if not reason.strip():
        raise PharmacyError("Write a reason, for example \"strip damaged\".")
    if batch.quantity + change < 0:
        raise PharmacyError(f"Batch {batch.batch_no} has only {batch.quantity} left, so you can't remove "
                            f"{-change}.")
    batch.quantity += change
    log_movement(db, batch, change, kind, reason.strip(), user_id, now_local())
    db.commit()
    return batch


def write_off_expired(db: Session, *, user_id: int | None, on: date | None = None) -> list[MedicineBatchRow]:
    """Take every expired batch off the shelf (quantity -> 0) and write "expired" diary lines."""
    on = on or today_local()
    batches = list(db.scalars(select(MedicineBatchRow).where(
        MedicineBatchRow.quantity > 0, MedicineBatchRow.expiry_date <= on)))
    when = now_local()
    for batch in batches:
        log_movement(db, batch, -batch.quantity, MovementType.EXPIRED,
                     f"Expired on {batch.expiry_date:%d %b %Y}", user_id, when)
        batch.quantity = 0
    db.commit()
    return batches


# ---------------------------------------------------------------- alerts

def low_stock(db: Session, on: date | None = None) -> list[tuple[MedicineRow, int]]:
    """Active medicines whose in-date stock is at or below their reorder level: [(medicine, stock)]."""
    on = on or today_local()
    in_date = (select(MedicineBatchRow.medicine_id, func.sum(MedicineBatchRow.quantity).label("stock"))
               .where(MedicineBatchRow.expiry_date > on)
               .group_by(MedicineBatchRow.medicine_id).subquery())
    stock = func.coalesce(in_date.c.stock, 0)
    rows = db.execute(select(MedicineRow, stock)
                      .outerjoin(in_date, in_date.c.medicine_id == MedicineRow.id)
                      .where(MedicineRow.is_active, stock <= MedicineRow.reorder_level)
                      .order_by(stock, MedicineRow.brand_name))
    return [(medicine, int(units)) for medicine, units in rows]


def expiring_within(db: Session, days: int, on: date | None = None) -> list[MedicineBatchRow]:
    """Batches with stock that expire in the next `days` days (but not yet expired), soonest first."""
    on = on or today_local()
    return list(db.scalars(select(MedicineBatchRow).where(
        MedicineBatchRow.quantity > 0,
        MedicineBatchRow.expiry_date > on,
        MedicineBatchRow.expiry_date <= on + timedelta(days=days),
    ).order_by(MedicineBatchRow.expiry_date)))


def expired_batches(db: Session, on: date | None = None) -> list[MedicineBatchRow]:
    """Batches still holding stock that have expired: they must come off the shelf."""
    on = on or today_local()
    return list(db.scalars(select(MedicineBatchRow).where(
        MedicineBatchRow.quantity > 0, MedicineBatchRow.expiry_date <= on,
    ).order_by(MedicineBatchRow.expiry_date)))
