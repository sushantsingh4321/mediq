"""
Pharmacy step 5: the 30 demo medicines (services/pharmacy_seed.py).
The seed is built in a brand-new, empty in-memory database here, so these
tests see exactly what a first start-up would create.
Run from the mediq/ folder with:   pytest
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.database import Base
from backend.app.db_models import MedicineBatchRow, MedicineRow, StockMovementRow, SupplierRow
from backend.app.main import app
from backend.app.models import DrugSchedule
from backend.app.services import pharmacy as ph
from backend.app.services.pharmacy_seed import add_demo_pharmacy

TODAY = date(2027, 6, 1)


@pytest.fixture(scope="module")
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool)   # in memory, gone after the tests
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        assert add_demo_pharmacy(session, TODAY) == 30
        yield session


def names(medicines):
    return {m.brand_name for m in medicines}


def test_thirty_medicines_two_suppliers(db):
    assert db.scalar(select(func.count()).select_from(MedicineRow)) == 30
    assert db.scalar(select(func.count()).select_from(SupplierRow)) == 2
    schedules = set(db.scalars(select(MedicineRow.schedule)))
    assert schedules == {DrugSchedule.OTC, DrugSchedule.H, DrugSchedule.H1, DrugSchedule.X}   # one of each kind
    # Schedule H/H1/X medicines are marked "prescription required"
    assert all(m.prescription_required == (m.schedule != DrugSchedule.OTC) for m in db.scalars(select(MedicineRow)))


def test_every_batch_obeys_the_rules(db):
    for b in db.scalars(select(MedicineBatchRow)):
        gst = b.medicine.gst_percent
        assert ph.rupees(b.selling_price * (1 + gst / 100)) <= b.mrp, b.batch_no     # within MRP incl. GST
        assert b.purchase_price < b.selling_price and b.mfg_date < b.expiry_date
        assert b.mfg_date <= TODAY
        # The diary adds up to the shelf: one "in" line per batch
        diary = db.scalars(select(StockMovementRow.quantity).where(StockMovementRow.batch_id == b.id)).all()
        assert sum(diary) == b.quantity


def test_the_alerts_have_something_to_show(db):
    low = {m.brand_name for m, _ in ph.low_stock(db, TODAY)}
    assert low == {"Galvus 50", "Huminsulin R", "Asthalin", "Addwize 10"}     # Addwize: out of stock
    soon = lambda days: {b.medicine.brand_name for b in ph.expiring_within(db, days, TODAY)}
    assert soon(30) == {"Mox 500", "Cetzine 10"}
    assert soon(60) == soon(30) | {"Shelcal 500"}
    assert soon(90) == soon(60) | {"Montair LC"}
    assert {b.medicine.brand_name for b in ph.expired_batches(db, TODAY)} == {"Combiflam"}


def test_fefo_on_the_demo_data_uses_the_soon_batch_first(db):
    mox = db.scalar(select(MedicineRow).where(MedicineRow.brand_name == "Mox 500"))
    picks = ph.pick_batches_fefo(db, mox, 50, TODAY)
    assert [(b.expiry_date - TODAY).days for b, _ in picks] == [20, 330]
    assert [take for _, take in picks] == [40, 10]


def test_display_names_dont_repeat_the_strength(db):
    by_brand = {m.brand_name: m.display_name for m in db.scalars(select(MedicineRow))}
    assert by_brand["Dolo 650"] == "Dolo 650"                       # not "Dolo 650 650 mg"
    assert by_brand["Alprax 0.25"] == "Alprax 0.25"
    assert by_brand["Crocin Advance"] == "Crocin Advance 500 mg"    # strength not in the brand: added
    assert by_brand["Augmentin 625 Duo"] == "Augmentin 625 Duo 500 mg + 125 mg"


def test_the_running_app_was_seeded_and_is_searchable():
    found = TestClient(app).get("/api/pharmacy/medicines?q=paracetamol").json()
    assert {"Dolo 650", "Crocin Advance", "Combiflam"} <= {m["brand_name"] for m in found}
