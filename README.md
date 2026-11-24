# mediQ: OPD patient queuing system

A hospital OPD token queue with queuing-theory (M/M/c) wait estimates, built with
Python + FastAPI and a plain HTML/JS frontend. Designed per hospital, with a
`/api/hospital/summary` endpoint a future city-wide service can read.

**New to all of this? Start with [LEARN.md](LEARN.md).**

## Run

Needs Python 3.10 or newer.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then fill in SECRET_KEY and ADMIN_PASSWORD (see the comments inside)
uvicorn backend.app.main:app --reload --reload-dir backend --reload-dir migrations
```

- Website: http://localhost:8000 · Log in: http://localhost:8000/login.html (the admin from `.env`)
- API docs: http://localhost:8000/docs
- Tests: `pytest`

`--reload` restarts the server when you save backend code; `--reload-dir` limits that to
`backend/` and `migrations/`, so editing tests or docs doesn't restart it. Each restart prints
`WARNING: WatchFiles detected changes ... Reloading...`: that is normal, not an error.
Not editing code? Leave out the `--reload...` options.

## Screens

- **Website** (`/`): hospitals, specialities, live "now serving", enquiry form, request a call back.
- **Reception**: register a patient, get a token like `GEN-007` with people ahead and estimated wait.
- **Doctor**: call the next patient into a room (FCFS, only during their OPD session), finish the current one.
- **Waiting room**: "now serving" board per department, refreshes every 5 s.
- **Dashboard**: live counts plus M/M/c model output (utilization, chance of waiting, Lq, Wq); edit doctors, consult time and arrival rate.
- **Beds**: free/occupied beds per ward; admit and discharge.
- **Doctor schedule** (`/schedule.html`): weekly OPD timetable and who is on duty now.
- **Call-backs** (`/staff-callbacks.html`) and **Admin console** (`/admin.html`).

Staff screens need a login with the right role (patient, receptionist, doctor, admin).

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `MEDIQ_HOSPITAL_ID` | `HOSP-001` | Identifies this hospital to a city-wide service |
| `MEDIQ_HOSPITAL_NAME` | `Demo City Hospital` | Shown in the header |
| `MEDIQ_SEED` | `1` | Create 3 demo departments and 3 wards on start |

Accounts, database, Twilio and time-zone settings live in `.env`; `.env.example` explains each one.

## Current limits

FCFS only (no priority queue yet), call recording/transcripts not built yet, ambulance and
inventory modules not built yet. Data is saved in SQLite (`mediq.db`); see LEARN.md Part 10.5
for moving to PostgreSQL.
