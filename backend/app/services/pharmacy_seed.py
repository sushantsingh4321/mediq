"""
Demo data for the pharmacy (Module 4): 30 common Indian medicines, 2 suppliers
and sample batches, so the pages aren't empty on first run.

Runs once at start-up (main.py), and only when the medicines table is empty,
so it never touches a pharmacy you have filled in yourself.

The batches are placed RELATIVE TO TODAY, so the alerts always have something
to show, whatever day you run it:
    expiring within 30 days   Mox 500, Cetzine 10
    expiring within 60 days   Shelcal 500
    expiring within 90 days   Montair LC
    already expired           Combiflam (one batch, still on the shelf)
    low on stock              Galvus 50, Huminsulin R, Asthalin
    out of stock              Addwize 10 (Schedule X)

Prices are close to real Indian MRPs (per unit: one tablet, one bottle...) but
are only examples. GST is 5%, the rate for most medicines since September 2025.
Batch numbers, suppliers and GSTINs are made up.
"""

from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..db_models import MedicineBatchRow, MedicineRow, SupplierRow
from ..models import DosageForm, DrugSchedule, MovementType, StorageType
from .pharmacy import log_movement, now_local, today_local

T, C, S, I, O, D, N = (DosageForm.TABLET, DosageForm.CAPSULE, DosageForm.SYRUP, DosageForm.INJECTION,
                       DosageForm.OINTMENT, DosageForm.DROPS, DosageForm.INHALER)
OTC, H, H1, X = DrugSchedule.OTC, DrugSchedule.H, DrugSchedule.H1, DrugSchedule.X

# brand, generic (salt), strength, form, category, schedule, manufacturer, unit, pack size,
# reorder level, MRP per unit (₹), batches: [(days until expiry, quantity), ...]
MEDICINES = [
    ("Dolo 650", "Paracetamol", "650 mg", T, "analgesic", OTC, "Micro Labs", "tablet", 15, 150, "2.04", [(200, 300), (560, 450)]),
    ("Crocin Advance", "Paracetamol", "500 mg", T, "analgesic", OTC, "Haleon", "tablet", 15, 100, "1.60", [(380, 300)]),
    ("Combiflam", "Ibuprofen + Paracetamol", "400 mg + 325 mg", T, "analgesic", OTC, "Sanofi", "tablet", 20, 80, "2.50", [(-10, 30), (420, 200)]),
    ("Mox 500", "Amoxicillin", "500 mg", C, "antibiotic", H, "Sun Pharma", "capsule", 10, 60, "7.20", [(20, 40), (330, 160)]),
    ("Augmentin 625 Duo", "Amoxicillin + Clavulanic acid", "500 mg + 125 mg", T, "antibiotic", H, "GSK", "tablet", 10, 40, "22.30", [(240, 120)]),
    ("Azithral 500", "Azithromycin", "500 mg", T, "antibiotic", H, "Alembic", "tablet", 5, 30, "23.80", [(410, 90)]),
    ("Ciplox 500", "Ciprofloxacin", "500 mg", T, "antibiotic", H, "Cipla", "tablet", 10, 40, "3.90", [(180, 100), (600, 100)]),
    ("Taxim-O 200", "Cefixime", "200 mg", T, "antibiotic", H, "Alkem", "tablet", 10, 40, "11.00", [(350, 120)]),
    ("Glycomet 500", "Metformin", "500 mg", T, "antidiabetic", H, "USV", "tablet", 20, 200, "1.90", [(150, 400), (640, 600)]),
    ("Amaryl 1", "Glimepiride", "1 mg", T, "antidiabetic", H, "Sanofi", "tablet", 30, 60, "12.40", [(390, 150)]),
    ("Galvus 50", "Vildagliptin", "50 mg", T, "antidiabetic", H, "Novartis", "tablet", 28, 56, "26.00", [(260, 20)]),
    ("Huminsulin R", "Human insulin (regular)", "40 IU/ml", I, "antidiabetic", H, "Eli Lilly", "vial", 1, 10, "180.00", [(200, 4)]),
    ("Pan 40", "Pantoprazole", "40 mg", T, "antacid", H, "Alkem", "tablet", 15, 100, "15.50", [(450, 300)]),
    ("Omez 20", "Omeprazole", "20 mg", C, "antacid", H, "Dr. Reddy's", "capsule", 20, 80, "6.20", [(310, 200)]),
    ("Ondem 4", "Ondansetron", "4 mg", T, "antiemetic", H, "Alkem", "tablet", 10, 40, "5.20", [(500, 100)]),
    ("Telma 40", "Telmisartan", "40 mg", T, "antihypertensive", H, "Glenmark", "tablet", 30, 90, "11.80", [(280, 180), (700, 180)]),
    ("Amlong 5", "Amlodipine", "5 mg", T, "antihypertensive", H, "Micro Labs", "tablet", 15, 90, "4.10", [(520, 300)]),
    ("Atorva 10", "Atorvastatin", "10 mg", T, "cardiac", H, "Zydus", "tablet", 15, 90, "9.50", [(330, 225)]),
    ("Ecosprin 75", "Aspirin", "75 mg", T, "cardiac", OTC, "USV", "tablet", 14, 140, "0.52", [(600, 700)]),
    ("Thyronorm 50", "Levothyroxine", "50 mcg", T, "thyroid", H, "Abbott", "tablet", 120, 120, "1.85", [(210, 480)]),
    ("Montair LC", "Montelukast + Levocetirizine", "10 mg + 5 mg", T, "anti-allergic", H, "Cipla", "tablet", 10, 40, "21.00", [(80, 60), (480, 100)]),
    ("Cetzine 10", "Cetirizine", "10 mg", T, "anti-allergic", OTC, "GSK", "tablet", 10, 50, "1.90", [(25, 60), (520, 200)]),
    ("Asthalin", "Salbutamol", "100 mcg/dose", N, "respiratory", H, "Cipla", "inhaler", 1, 10, "160.00", [(400, 3)]),
    ("Ascoril LS", "Ambroxol + Levosalbutamol + Guaifenesin", "100 ml", S, "respiratory", H, "Glenmark", "bottle", 1, 10, "118.00", [(360, 30)]),
    ("Benadryl", "Diphenhydramine", "150 ml", S, "respiratory", OTC, "Kenvue", "bottle", 1, 10, "125.00", [(540, 25)]),
    ("Shelcal 500", "Calcium + Vitamin D3", "500 mg + 250 IU", T, "supplement", OTC, "Torrent", "tablet", 15, 90, "7.40", [(45, 75), (610, 300)]),
    ("Betadine", "Povidone-iodine", "5% w/w, 20 g", O, "antiseptic", OTC, "Win-Medicare", "tube", 1, 10, "118.00", [(700, 40)]),
    ("Ciplox Eye Drops", "Ciprofloxacin", "0.3% w/v, 10 ml", D, "eye care", H, "Cipla", "bottle", 1, 10, "22.00", [(300, 40)]),
    ("Alprax 0.25", "Alprazolam", "0.25 mg", T, "anxiolytic", H1, "Torrent", "tablet", 15, 30, "2.40", [(440, 90)]),
    ("Addwize 10", "Methylphenidate", "10 mg", T, "CNS stimulant", X, "Sun Pharma", "tablet", 10, 20, "5.60", []),
]

SUPPLIERS = [
    dict(name="Sahyadri Pharma Distributors", gstin="27AABCS1234D1Z5", drug_license_no="MH-PZ3-20B-104512",
         phone="+912026110000", email="orders@sahyadri-pharma.example", address="Bhawani Peth, Pune 411042"),
    dict(name="Lakeside Medical Agencies", gstin="27AAFCL5678K1Z2", drug_license_no="MH-NG2-21B-208877",
         phone="+917122550000", email="sales@lakeside-medical.example", address="Itwari, Nagpur 440002"),
]

GST = Decimal("5")
RACKS = "ABCDEF"


def prices(mrp: str) -> tuple[Decimal, Decimal, Decimal]:
    """From the MRP: selling price (before GST, so that price + GST stays under the MRP) and our cost."""
    mrp_d = Decimal(mrp)
    selling = (mrp_d / (1 + GST / 100) * Decimal("0.95")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    cost = (selling * Decimal("0.72")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return mrp_d, selling, cost


def seed_demo_pharmacy() -> int:
    """Add the demo catalogue if there are no medicines yet. Returns how many medicines were added."""
    with SessionLocal() as db:
        if db.scalar(select(MedicineRow.id).limit(1)) is not None:
            return 0
        return add_demo_pharmacy(db, today_local())


def add_demo_pharmacy(db: Session, today: date) -> int:
    suppliers = [SupplierRow(**s) for s in SUPPLIERS]
    db.add_all(suppliers)
    db.flush()
    when = now_local()
    for n, (brand, generic, strength, form, category, schedule, maker, unit, pack, reorder, mrp, batches) in enumerate(MEDICINES):
        med = MedicineRow(brand_name=brand, generic_name=generic, strength=strength, dosage_form=form,
                          category=category, schedule=schedule, manufacturer=maker, hsn_code="3004",
                          gst_percent=GST, pack_size=pack, unit=unit,
                          storage=StorageType.COLD_CHAIN if form == I else StorageType.ROOM,
                          prescription_required=schedule != OTC, reorder_level=reorder)
        db.add(med)
        db.flush()                                   # gives med.id
        mrp_d, selling, cost = prices(mrp)
        for b, (days_left, quantity) in enumerate(batches):
            expiry = today + timedelta(days=days_left)
            # Made ~2 years before expiry, but never in the future
            mfg = min(expiry - timedelta(days=730), today - timedelta(days=15 + 7 * b))
            batch = MedicineBatchRow(
                medicine_id=med.id, supplier_id=suppliers[(n + b) % 2].id,
                batch_no=f"{brand.split()[0][:3].upper()}{expiry:%y%m}{b + 1}",   # e.g. DOL27061
                mfg_date=mfg, expiry_date=expiry, quantity=quantity,
                purchase_price=cost, mrp=mrp_d, selling_price=selling, received_at=when,
                rack_location=f"{RACKS[n % len(RACKS)]}{n // len(RACKS) + 1}-{b + 1}")
            db.add(batch)
            db.flush()
            log_movement(db, batch, +quantity, MovementType.IN, "Opening stock (demo data)", None, when)
    db.commit()
    return len(MEDICINES)
