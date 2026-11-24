"""
Pharmacy step 1: the database tables (db_models.py, migration 0006).
The API, FEFO and alerts come in later steps; here we only check that the
tables exist and that the DATABASE ITSELF refuses impossible rows.
Run from the mediq/ folder with:   pytest
"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

import backend.app.main  # noqa: F401  (importing the app runs the migrations)
from backend.app.database import SessionLocal, engine
from backend.app.db_models import (MedicineBatchRow, MedicineRow, MovementType, StockMovementRow,
                                   SupplierRow)
from backend.app.models import DosageForm, DrugSchedule, StorageType

PHARMACY_TABLES = {
    "medicines", "suppliers", "medicine_batches", "purchase_orders", "purchase_order_items",
    "prescriptions", "prescription_items", "dispensations", "dispensation_items", "stock_movements",
}


def make_medicine(db, brand="Test Para 500", **extra):
    """Helper: one medicine with sensible defaults."""
    values = dict(brand_name=brand, generic_name="Paracetamol", strength="500 mg",
                  dosage_form=DosageForm.TABLET, category="analgesic", schedule=DrugSchedule.OTC,
                  manufacturer="Test Pharma", hsn_code="3004", gst_percent=Decimal("12"),
                  pack_size=10, unit="tablet", storage=StorageType.ROOM,
                  prescription_required=False, reorder_level=50)
    values.update(extra)
    med = MedicineRow(**values)
    db.add(med)
    db.commit()
    return med


def make_batch(db, medicine, batch_no, **extra):
    values = dict(medicine_id=medicine.id, batch_no=batch_no, mfg_date=date(2026, 1, 1),
                  expiry_date=date(2028, 1, 1), quantity=100, purchase_price=Decimal("1.10"),
                  mrp=Decimal("2.00"), selling_price=Decimal("1.80"), received_at=datetime.now())
    values.update(extra)
    batch = MedicineBatchRow(**values)
    db.add(batch)
    db.commit()
    return batch


def test_all_pharmacy_tables_exist():
    assert PHARMACY_TABLES <= set(inspect(engine).get_table_names())


def test_medicine_with_batch_and_supplier_round_trip():
    with SessionLocal() as db:
        supplier = SupplierRow(name="Test Distributors", gstin="27ABCDE1234F1Z5")
        db.add(supplier)
        db.commit()
        med = make_medicine(db, brand="Round Trip 500")
        make_batch(db, med, "LATE", expiry_date=date(2028, 6, 1), supplier_id=supplier.id)
        make_batch(db, med, "SOON", expiry_date=date(2027, 3, 1), selling_price=Decimal("12.35"),
                   mrp=Decimal("13.00"))
        med_id = med.id

    with SessionLocal() as db:                         # a fresh session: really from the database
        med = db.get(MedicineRow, med_id)
        # medicine.batches comes back soonest-expiry first: the FEFO order
        assert [b.batch_no for b in med.batches] == ["SOON", "LATE"]
        assert med.batches[0].selling_price == Decimal("12.35")     # exact money, not 12.3499...
        assert med.batches[1].supplier.name == "Test Distributors"
        assert med.schedule == DrugSchedule.OTC and med.is_active   # is_active defaults to True


@pytest.mark.parametrize("bad", [
    {"quantity": -1},                                             # negative stock
    {"mfg_date": date(2027, 1, 1), "expiry_date": date(2026, 1, 1)},   # expires before it was made
    {"selling_price": Decimal("2.50"), "mrp": Decimal("2.00")},   # selling above MRP is illegal
])
def test_database_refuses_impossible_batches(bad):
    with SessionLocal() as db:
        med = make_medicine(db, brand=f"Bad Batch {sorted(bad)}")
        with pytest.raises(IntegrityError):
            make_batch(db, med, "B1", **bad)
        db.rollback()


def test_database_refuses_bad_medicines():
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            make_medicine(db, brand="Too Much GST", gst_percent=Decimal("40"))
        db.rollback()
        make_medicine(db, brand="Twin 500")
        with pytest.raises(IntegrityError):              # same brand + strength + form twice
            make_medicine(db, brand="Twin 500")
        db.rollback()


def test_stock_movement_records_a_signed_change():
    with SessionLocal() as db:
        med = make_medicine(db, brand="Diary 500")
        batch = make_batch(db, med, "D1")
        db.add_all([
            StockMovementRow(medicine_id=med.id, batch_id=batch.id, type=MovementType.IN,
                             quantity=100, reason="received", created_at=datetime.now()),
            StockMovementRow(medicine_id=med.id, batch_id=batch.id, type=MovementType.OUT,
                             quantity=-10, reason="dispensed", created_at=datetime.now()),
        ])
        db.commit()
        total = sum(db.scalars(select(StockMovementRow.quantity).where(StockMovementRow.batch_id == batch.id)))
        assert total == 90
