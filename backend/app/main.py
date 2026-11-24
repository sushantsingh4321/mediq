"""
mediQ backend: the FastAPI application.

Run it (from the mediq/ folder):
    uvicorn backend.app.main:app --reload --reload-dir backend --reload-dir migrations

Then open:
    http://localhost:8000/          -> the web app (frontend)
    http://localhost:8000/docs      -> interactive API docs (try every endpoint!)

Each function below decorated with @app.get / @app.post is an "endpoint":
a URL the frontend (or anyone) can call.
"""

import os
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy.orm import Session

from .models import (
    Department, DepartmentCreate, HospitalSummary, QueueStats,
    Token, TokenCreate, TokenStatus, TokenView,
)
from .database import get_db, run_migrations
from .db_models import Role, User
from .deps import admin_only, any_staff, doctor_only, reception_only
from .queueing import estimate_wait_for_position, mmc_metrics
from .routers import admin, ambulance, auth, beds, callback, schedule, website
from .store import store

# Create or update the database tables before anything uses them.
# Same as running `alembic upgrade head` by hand; safe to run on every start.
run_migrations()
auth.seed_first_admin()   # first admin account from .env (only if none exists yet)

# Which hospital is this? Set these when you deploy one copy per hospital.
HOSPITAL_ID = os.getenv("MEDIQ_HOSPITAL_ID", "HOSP-001")
HOSPITAL_NAME = os.getenv("MEDIQ_HOSPITAL_NAME", "Demo City Hospital")

app = FastAPI(
    title="mediQ",
    description="OPD patient queuing system for one hospital, ready to report to a city-wide service.",
    version="0.1.0",
)

# Plug in the extra modules. Each router file adds its own group of /api URLs.
app.include_router(beds.router)       # Module 1: bed availability   (/api/wards...)
app.include_router(website.router)    # website content + enquiries  (/api/site, /api/enquiries)
app.include_router(callback.router)   # Request Call Back via Twilio (/api/callback...)
app.include_router(auth.router)       # user accounts: signup, login, me, logout (/api/auth...)
app.include_router(schedule.router)   # Module 2: doctor schedule     (/api/schedule...)
app.include_router(admin.router)      # admin console overview        (/api/admin...)
app.include_router(ambulance.router)  # Module 3: ambulance dispatch  (/api/ambulances...)


# ---------------------------------------------------------------- helpers

def get_department_or_404(dept_id: int) -> Department:
    dept = store.departments.get(dept_id)
    if dept is None:
        # HTTPException makes FastAPI reply with that status code + message.
        raise HTTPException(status_code=404, detail=f"Department {dept_id} not found")
    return dept


def build_stats(dept: Department) -> QueueStats:
    waiting = store.tokens_in(dept.id, TokenStatus.WAITING)
    serving = store.tokens_in(dept.id, TokenStatus.IN_CONSULTATION)
    done = store.tokens_in(dept.id, TokenStatus.DONE)

    service_rate = 60 / dept.avg_consult_minutes  # mu, patients per hour per doctor
    model = mmc_metrics(dept.expected_patients_per_hour, service_rate, dept.doctors)

    # A new patient joining now has everyone waiting ahead of them.
    # If every doctor is busy they also wait for one to free up, so we count
    # the people in consultation as "half done" on average.
    busy_rooms = len(serving)
    ahead = len(waiting) + (busy_rooms / 2 if busy_rooms >= dept.doctors else 0)

    return QueueStats(
        department=dept,
        waiting=len(waiting),
        in_consultation=len(serving),
        done_today=len(done),
        now_serving=[t.number for t in serving],
        wait_for_new_patient_minutes=estimate_wait_for_position(
            ahead, dept.doctors, dept.avg_consult_minutes),
        observed_arrivals_last_hour=store.arrivals_since(dept.id, 60),
        model=model,
    )


def to_view(token: Token) -> TokenView:
    view = TokenView(**token.model_dump())
    if token.status == TokenStatus.WAITING:
        dept = store.departments[token.department_id]
        waiting = store.tokens_in(dept.id, TokenStatus.WAITING)
        ahead = [t.id for t in waiting].index(token.id)
        view.people_ahead = ahead
        view.estimated_wait_minutes = estimate_wait_for_position(
            ahead, dept.doctors, dept.avg_consult_minutes)
    return view


# ---------------------------------------------------------------- departments

@app.get("/api/departments", response_model=list[Department], tags=["departments"])
def list_departments():
    return list(store.departments.values())


@app.post("/api/departments", response_model=Department, status_code=201, tags=["departments"],
          dependencies=[Depends(admin_only)])          # login needed: admin
def create_department(data: DepartmentCreate):
    # FastAPI has already checked `data` against DepartmentCreate for us.
    if any(d.code.upper() == data.code.upper() for d in store.departments.values()):
        raise HTTPException(status_code=400, detail="A department with that code already exists")
    data.code = data.code.upper()
    return store.add_department(data)


@app.put("/api/departments/{dept_id}", response_model=Department, tags=["departments"],
         dependencies=[Depends(admin_only)])           # login needed: admin (Dashboard)
def update_department(dept_id: int, data: DepartmentCreate):
    get_department_or_404(dept_id)
    data.code = data.code.upper()
    return store.update_department(dept_id, data)


@app.get("/api/departments/{dept_id}/stats", response_model=QueueStats, tags=["departments"])
def department_stats(dept_id: int):
    return build_stats(get_department_or_404(dept_id))


@app.get("/api/departments/{dept_id}/queue", response_model=list[TokenView], tags=["departments"],
         dependencies=[Depends(any_staff)])            # login needed: staff (has patient names)
def department_queue(dept_id: int):
    """Everyone waiting or being seen in a department, in order."""
    get_department_or_404(dept_id)
    active = [t for t in store.tokens_in(dept_id) if t.status != TokenStatus.DONE]
    return [to_view(t) for t in active]


@app.post("/api/departments/{dept_id}/call-next", response_model=Token, tags=["doctor"])
def call_next(dept_id: int, room: int,
              user: User = Depends(doctor_only),       # login needed: doctor (we also need to know WHICH one)
              db: Session = Depends(get_db)):
    """
    A doctor in `room` presses "Next patient":
      1. their current patient (if any) is marked DONE
      2. the oldest WAITING token moves to IN_CONSULTATION in that room
    This is the FCFS (First-Come-First-Served) queue discipline.

    Doctors can only do this during their own OPD session, in its department
    and room (Module 2, routers/schedule.py). Admins may always do it, e.g. to
    cover an emergency.
    """
    dept = get_department_or_404(dept_id)
    if not 1 <= room <= dept.doctors:
        raise HTTPException(status_code=400, detail=f"Room must be between 1 and {dept.doctors}")
    if user.role == Role.DOCTOR:
        schedule.check_on_duty(db, user, dept_id, room)

    # Both steps are saved together in store.call_next (see store.py)
    nxt = store.call_next(dept_id, room, datetime.now())
    if nxt is None:
        raise HTTPException(status_code=404, detail="No patients waiting")
    return nxt


@app.post("/api/departments/{dept_id}/finish", tags=["doctor"],
          dependencies=[Depends(doctor_only)])         # login needed: doctor
def finish_current(dept_id: int, room: int):
    """Doctor finishes the current patient without calling another (e.g. end of shift)."""
    get_department_or_404(dept_id)
    finished = store.finish_room(dept_id, room, datetime.now())
    if finished is None:
        raise HTTPException(status_code=404, detail="No patient in that room")
    return {"finished": finished.number}


# ---------------------------------------------------------------- tokens

@app.post("/api/tokens", response_model=TokenView, status_code=201, tags=["reception"],
          dependencies=[Depends(reception_only)])      # login needed: receptionist
def register_patient(data: TokenCreate):
    """Reception registers a patient and gets a token number."""
    dept = get_department_or_404(data.department_id)
    token = store.add_token(data.patient_name.strip(), dept)
    return to_view(token)


@app.get("/api/tokens/{token_id}", response_model=TokenView, tags=["reception"])
def get_token(token_id: int):
    token = store.get_token(token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    return to_view(token)


# ---------------------------------------------------------------- city-wide hook

@app.get("/api/hospital/summary", response_model=HospitalSummary, tags=["city-wide"])
def hospital_summary():
    """
    Anonymous numbers only. A future city-wide service can call this on every
    hospital to show "where is the shortest OPD wait right now?".
    """
    depts = []
    for dept in store.departments.values():
        s = build_stats(dept)
        depts.append({
            "code": dept.code,
            "name": dept.name,
            "doctors": dept.doctors,
            "waiting": s.waiting,
            "estimated_wait_minutes": s.wait_for_new_patient_minutes,
            "utilization": s.model["utilization"],
        })
    # Counts from the extra modules. Numbers only, never names.
    facilities = {
        "free_beds": beds.total_free_beds(),
        "available_ambulances": ambulance.available_count(),
    }
    return HospitalSummary(hospital_id=HOSPITAL_ID, hospital_name=HOSPITAL_NAME,
                           generated_at=datetime.now(), departments=depts,
                           facilities=facilities)


@app.get("/api/health", tags=["city-wide"])
def health():
    return {"status": "ok", "hospital_id": HOSPITAL_ID}


# ---------------------------------------------------------------- demo data

def seed_demo_data():
    """Create a few departments so the app is not empty on first run."""
    if store.departments:
        return
    store.add_department(DepartmentCreate(code="GEN", name="General Medicine", doctors=3,
                                          avg_consult_minutes=8, expected_patients_per_hour=18))
    store.add_department(DepartmentCreate(code="PED", name="Paediatrics", doctors=2,
                                          avg_consult_minutes=12, expected_patients_per_hour=8))
    store.add_department(DepartmentCreate(code="ORT", name="Orthopaedics", doctors=1,
                                          avg_consult_minutes=15, expected_patients_per_hour=3))


if os.getenv("MEDIQ_SEED", "1") == "1":
    seed_demo_data()
    beds.seed_demo_wards()
    ambulance.seed_demo_ambulances()


# ---------------------------------------------------------------- frontend
# Serve the plain HTML/JS frontend from the same server. Mounted LAST so the
# /api routes above take priority.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


# The website's home page. Without this route, "/" would show index.html,
# which is now the OPD system (still reachable at /index.html).
@app.get("/", include_in_schema=False)
def home_page():
    return FileResponse(FRONTEND_DIR / "home.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
