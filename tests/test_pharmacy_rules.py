"""
Pharmacy step 2: the rules (backend/app/services/pharmacy.py).
FEFO, expired batches, Schedule H, the stock diary, GST bills and alerts.

The tests pass a fixed "today" (TODAY) so they give the same answer on any day.
Run from the mediq/ folder with:   pytest
"""

import itertools
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

import backend.app.main  # noqa: F401  (importing the app runs the migrations)
from backend.app.database import SessionLocal
from backend.app.db_models import (MedicineBatchRow, MedicineRow, PrescriptionItemRow, PrescriptionRow,
                                   Role, StockMovementRow, User)
from backend.app.models import DosageForm, DrugSchedule, MovementType, StorageType
from backend.app.services import pharmacy as ph
from backend.app.services.pharmacy import PharmacyError

TODAY = date(2027, 1, 15)
_names = itertools.count(1)     # every test gets brand-new medicine names: the test database is shared


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def staff_id(db):
    """A doctor (writes prescriptions) who also does the dispensing in these tests."""
    user = User(full_name="Dr Rules", email=f"rules{next(_names)}@example.com",
                hashed_password="x", role=Role.DOCTOR)
    db.add(user)
    db.commit()
    return user.id


def medicine(db, schedule=DrugSchedule.OTC, reorder_level=20, gst="12", **extra):
    med = MedicineRow(brand_name=f"Rule Med {next(_names)}", generic_name="Testamol", strength="500 mg",
                      dosage_form=DosageForm.TABLET, category="analgesic", schedule=schedule,
                      manufacturer="Test Pharma", hsn_code="3004", gst_percent=Decimal(gst), pack_size=10,
                      unit="tablet", storage=StorageType.ROOM,
                      prescription_required=schedule != DrugSchedule.OTC, reorder_level=reorder_level, **extra)
    db.add(med)
    db.commit()
    return med


def batch(db, med, batch_no, expires_in_days, quantity=100, selling_price="1.80"):
    """Put a batch on the shelf directly (receive_stock refuses expired ones, but we need some)."""
    b = MedicineBatchRow(medicine_id=med.id, batch_no=batch_no, mfg_date=TODAY - timedelta(days=400),
                         expiry_date=TODAY + timedelta(days=expires_in_days), quantity=quantity,
                         purchase_price=Decimal("1.00"), mrp=Decimal("2.50"),
                         selling_price=Decimal(selling_price), received_at=ph.now_local())
    db.add(b)
    db.commit()
    return b


def prescription(db, doctor_id, *lines):
    """lines: (medicine, quantity) pairs."""
    rx = PrescriptionRow(patient_name="Asha Patel", doctor_id=doctor_id, created_at=ph.now_local())
    for med, qty in lines:
        rx.items.append(PrescriptionItemRow(medicine_id=med.id, dose="1-0-1", frequency="twice a day",
                                            duration_days=5, quantity=qty, instructions="after food"))
    db.add(rx)
    db.commit()
    return rx


# ---------------------------------------------------------------- 1. FEFO

def test_fefo_takes_the_soonest_expiry_first_and_splits_across_batches(db, staff_id):
    med = medicine(db)
    late = batch(db, med, "LATE", expires_in_days=300, quantity=50)
    soon = batch(db, med, "SOON", expires_in_days=40, quantity=10)
    middle = batch(db, med, "MID", expires_in_days=120, quantity=50)

    bill = ph.dispense(db, user_id=staff_id, items=[(med.id, 15)], on=TODAY)

    taken = {line.batch.batch_no: line.quantity for line in bill.items}
    assert taken == {"SOON": 10, "MID": 5}            # all of SOON, then MID; LATE untouched
    db.refresh(soon), db.refresh(middle), db.refresh(late)
    assert (soon.quantity, middle.quantity, late.quantity) == (0, 45, 50)


# ---------------------------------------------------------------- 2. expired batches

def test_expired_batches_are_never_dispensed(db, staff_id):
    med = medicine(db)
    expired = batch(db, med, "OLD", expires_in_days=-10, quantity=100)
    today = batch(db, med, "TODAY", expires_in_days=0, quantity=100)   # expires today: also blocked
    good = batch(db, med, "GOOD", expires_in_days=200, quantity=5)

    bill = ph.dispense(db, user_id=staff_id, items=[(med.id, 5)], on=TODAY)
    assert [line.batch_id for line in bill.items] == [good.id]

    with pytest.raises(PharmacyError, match="200 more are expired"):
        ph.dispense(db, user_id=staff_id, items=[(med.id, 1)], on=TODAY)
    db.refresh(expired), db.refresh(today)
    assert expired.quantity == today.quantity == 100


def test_receiving_expired_stock_is_refused(db, staff_id):
    med = medicine(db)
    with pytest.raises(PharmacyError, match="return it to the supplier"):
        ph.receive_stock(db, user_id=staff_id, medicine_id=med.id, batch_no="X1",
                         mfg_date=TODAY - timedelta(days=700), expiry_date=TODAY, quantity=10,
                         purchase_price=Decimal("1"), mrp=Decimal("2.50"), selling_price=Decimal("1.80"), on=TODAY)


# ---------------------------------------------------------------- 3. Schedule H / H1 / X

@pytest.mark.parametrize("schedule", [DrugSchedule.H, DrugSchedule.H1, DrugSchedule.X])
def test_scheduled_drugs_need_a_prescription(db, staff_id, schedule):
    med = medicine(db, schedule=schedule)
    batch(db, med, "B1", expires_in_days=200)
    with pytest.raises(PharmacyError, match=f"Schedule {schedule.value} medicine and needs"):
        ph.dispense(db, user_id=staff_id, items=[(med.id, 10)], on=TODAY)

    rx = prescription(db, staff_id, (med, 10))
    bill = ph.dispense(db, user_id=staff_id, prescription_id=rx.id, on=TODAY)   # items from the prescription
    assert bill.prescription_id == rx.id and sum(i.quantity for i in bill.items) == 10


def test_otc_needs_no_prescription(db, staff_id):
    med = medicine(db, schedule=DrugSchedule.OTC)
    batch(db, med, "B1", expires_in_days=200)
    assert ph.dispense(db, user_id=staff_id, items=[(med.id, 4)], on=TODAY).prescription_id is None


def test_cannot_dispense_more_than_prescribed_even_in_parts(db, staff_id):
    antibiotic = medicine(db, schedule=DrugSchedule.H)
    other = medicine(db, schedule=DrugSchedule.H)
    batch(db, antibiotic, "A1", expires_in_days=200)
    batch(db, other, "O1", expires_in_days=200)
    rx = prescription(db, staff_id, (antibiotic, 10))

    ph.dispense(db, user_id=staff_id, prescription_id=rx.id, items=[(antibiotic.id, 6)], on=TODAY)
    with pytest.raises(PharmacyError, match="allows 4 more"):
        ph.dispense(db, user_id=staff_id, prescription_id=rx.id, items=[(antibiotic.id, 5)], on=TODAY)
    with pytest.raises(PharmacyError, match="isn't on prescription"):
        ph.dispense(db, user_id=staff_id, prescription_id=rx.id, items=[(other.id, 1)], on=TODAY)
    ph.dispense(db, user_id=staff_id, prescription_id=rx.id, on=TODAY)            # the remaining 4
    with pytest.raises(PharmacyError, match="already dispensed"):
        ph.dispense(db, user_id=staff_id, prescription_id=rx.id, on=TODAY)


# ---------------------------------------------------------------- 4. the stock diary

def test_every_stock_change_is_in_the_diary(db, staff_id):
    med = medicine(db)
    b = ph.receive_stock(db, user_id=staff_id, medicine_id=med.id, batch_no="d1",
                         mfg_date=TODAY - timedelta(days=30), expiry_date=TODAY + timedelta(days=500),
                         quantity=100, purchase_price=Decimal("1"), mrp=Decimal("2.50"),
                         selling_price=Decimal("1.80"), on=TODAY)
    assert b.batch_no == "D1"                                     # batch numbers saved in capitals
    ph.dispense(db, user_id=staff_id, items=[(med.id, 30)], on=TODAY)
    ph.adjust_stock(db, user_id=staff_id, batch_id=b.id, change=-2, reason="strip damaged")
    ph.adjust_stock(db, user_id=staff_id, batch_id=b.id, change=+1, reason="returned by ward",
                    kind=MovementType.RETURNED)

    lines = db.scalars(select(StockMovementRow).where(StockMovementRow.batch_id == b.id)
                       .order_by(StockMovementRow.id)).all()
    assert [(m.type, m.quantity) for m in lines] == [
        (MovementType.IN, 100), (MovementType.OUT, -30), (MovementType.ADJUST, -2), (MovementType.RETURNED, 1)]
    db.refresh(b)
    assert b.quantity == sum(m.quantity for m in lines) == 69     # the diary adds up to the shelf


def test_adjustments_need_a_reason_and_cannot_go_below_zero(db, staff_id):
    med = medicine(db)
    b = batch(db, med, "B1", expires_in_days=200, quantity=3)
    with pytest.raises(PharmacyError, match="reason"):
        ph.adjust_stock(db, user_id=staff_id, batch_id=b.id, change=-1, reason=" ")
    with pytest.raises(PharmacyError, match="only 3 left"):
        ph.adjust_stock(db, user_id=staff_id, batch_id=b.id, change=-4, reason="lost")


# ---------------------------------------------------------------- 5. the bill

def test_bill_adds_gst_per_line(db, staff_id):
    para = medicine(db, gst="12")
    vit = medicine(db, gst="5")
    batch(db, para, "P1", expires_in_days=200, selling_price="1.80")
    batch(db, vit, "V1", expires_in_days=200, selling_price="2.35")

    bill = ph.dispense(db, user_id=staff_id, items=[(para.id, 10), (vit.id, 3)], on=TODAY)
    # 10 × 1.80 = 18.00, GST 12% = 2.16       3 × 2.35 = 7.05, GST 5% = 0.3525 -> 0.35
    assert bill.subtotal == Decimal("25.05")
    assert bill.gst_amount == Decimal("2.51")
    assert bill.total == Decimal("27.56")


def test_a_failed_bill_changes_nothing(db, staff_id):
    ok = medicine(db)
    short = medicine(db)
    good_batch = batch(db, ok, "OK1", expires_in_days=200, quantity=50)
    batch(db, short, "SH1", expires_in_days=200, quantity=2)
    with pytest.raises(PharmacyError, match="Not enough"):
        ph.dispense(db, user_id=staff_id, items=[(ok.id, 10), (short.id, 5)], on=TODAY)
    db.rollback()
    db.refresh(good_batch)
    assert good_batch.quantity == 50                              # the first line wasn't taken either


def test_selling_price_with_gst_may_not_exceed_mrp(db, staff_id):
    med = medicine(db, gst="12")
    with pytest.raises(PharmacyError, match="above the MRP"):     # 2.40 + 12% = 2.69 > 2.50
        ph.receive_stock(db, user_id=staff_id, medicine_id=med.id, batch_no="M1",
                         mfg_date=TODAY - timedelta(days=30), expiry_date=TODAY + timedelta(days=500),
                         quantity=10, purchase_price=Decimal("1"), mrp=Decimal("2.50"),
                         selling_price=Decimal("2.40"), on=TODAY)


# ---------------------------------------------------------------- alerts

def test_low_stock_counts_only_in_date_stock(db):
    low = medicine(db, reorder_level=50)
    batch(db, low, "L1", expires_in_days=200, quantity=30)
    batch(db, low, "L2", expires_in_days=-1, quantity=500)       # expired: doesn't count
    fine = medicine(db, reorder_level=50)
    batch(db, fine, "F1", expires_in_days=200, quantity=80)
    empty = medicine(db, reorder_level=10)                       # no batches at all

    alerts = {m.id: stock for m, stock in ph.low_stock(db, on=TODAY)}
    assert alerts[low.id] == 30 and alerts[empty.id] == 0
    assert fine.id not in alerts


def test_expiry_alerts_in_30_60_90_days_and_expired(db, staff_id):
    med = medicine(db)
    b20 = batch(db, med, "E20", expires_in_days=20)
    b50 = batch(db, med, "E50", expires_in_days=50)
    b80 = batch(db, med, "E80", expires_in_days=80)
    b200 = batch(db, med, "E200", expires_in_days=200)
    gone = batch(db, med, "GONE", expires_in_days=-5, quantity=7)
    batch(db, med, "EMPTY", expires_in_days=10, quantity=0)       # nothing left: no alert

    def ids(batches):
        return {b.id for b in batches if b.medicine_id == med.id}

    assert ids(ph.expiring_within(db, 30, on=TODAY)) == {b20.id}
    assert ids(ph.expiring_within(db, 60, on=TODAY)) == {b20.id, b50.id}
    assert ids(ph.expiring_within(db, 90, on=TODAY)) == {b20.id, b50.id, b80.id}
    assert b200.id not in ids(ph.expiring_within(db, 90, on=TODAY))
    assert ids(ph.expired_batches(db, on=TODAY)) == {gone.id}

    ph.write_off_expired(db, user_id=staff_id, on=TODAY)
    db.refresh(gone)
    assert gone.quantity == 0
    line = db.scalars(select(StockMovementRow).where(StockMovementRow.batch_id == gone.id)).one()
    assert (line.type, line.quantity) == (MovementType.EXPIRED, -7)


# ---------------------------------------------------------------- edge cases (step 6)

def test_otc_medicine_ticked_prescription_required_is_also_blocked(db, staff_id):
    med = medicine(db, schedule=DrugSchedule.OTC)
    med.prescription_required = True          # e.g. a hospital rule stricter than the law
    db.commit()
    batch(db, med, "B1", expires_in_days=200)
    with pytest.raises(PharmacyError, match="needs a doctor's prescription"):
        ph.dispense(db, user_id=staff_id, items=[(med.id, 1)], on=TODAY)


def test_fefo_tie_on_expiry_takes_the_older_delivery_first(db, staff_id):
    med = medicine(db)
    first = batch(db, med, "FIRST", expires_in_days=100, quantity=5)
    second = batch(db, med, "SECOND", expires_in_days=100, quantity=5)    # same expiry, came later
    bill = ph.dispense(db, user_id=staff_id, items=[(med.id, 7)], on=TODAY)
    assert [(line.batch_id, line.quantity) for line in bill.items] == [(first.id, 5), (second.id, 2)]


def test_expiry_windows_include_their_last_day(db):
    from backend.app.routers.pharmacy import expiry_alert
    med = medicine(db)
    windows = {days: expiry_alert(batch(db, med, f"W{days}", expires_in_days=days), TODAY).window
               for days in (1, 30, 31, 60, 61, 90)}
    assert windows == {1: 30, 30: 30, 31: 60, 60: 60, 61: 90, 90: 90}
    in_30 = {b.batch_no for b in ph.expiring_within(db, 30, on=TODAY) if b.medicine_id == med.id}
    assert in_30 == {"W1", "W30"}


def test_hidden_medicines_dont_raise_low_stock_alerts(db):
    med = medicine(db, reorder_level=100)     # no stock at all: would be "low"
    assert med.id in {m.id for m, _ in ph.low_stock(db, on=TODAY)}
    med.is_active = False
    db.commit()
    assert med.id not in {m.id for m, _ in ph.low_stock(db, on=TODAY)}
