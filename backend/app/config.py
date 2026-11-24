"""
Settings, read from environment variables.

During development you put them in a file called .env in the mediq/ folder
(copy .env.example). Secrets like TWILIO_AUTH_TOKEN live ONLY there, never in
the code, and .env is listed in .gitignore so it is never committed.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[2]   # the mediq/ folder

# Copy the values from mediq/.env into the environment. Variables that are
# ALREADY set win over the file. The tests rely on this: they set DRY_RUN=true
# first, so a .env with DRY_RUN=false can never make a test dial a real phone.
load_dotenv(PROJECT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    dry_run: bool
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from_number: str
    desk_number: str
    public_base_url: str
    database_url: str
    secret_key: str                 # signs login tokens (JWT); empty = not set
    access_token_minutes: int       # how long a login token stays valid
    admin_email: str                # first admin, created on first run if set
    admin_password: str
    admin_name: str
    hospital_timezone: str          # "now" for OPD schedules, e.g. Asia/Kolkata


# Default database: a single file, mediq/mediq.db (SQLite, nothing to install).
# For PostgreSQL later, set e.g. DATABASE_URL=postgresql+psycopg://user:pass@host/mediq
DEFAULT_DATABASE_URL = f"sqlite:///{PROJECT_DIR / 'mediq.db'}"


def get_settings() -> Settings:
    """Read the settings fresh every time (so tests can change them)."""
    return Settings(
        # Safe default: anything except the word "false" means DRY RUN (no real calls).
        dry_run=os.getenv("DRY_RUN", "true").strip().lower() != "false",
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        twilio_from_number=os.getenv("TWILIO_FROM_NUMBER", ""),
        desk_number=os.getenv("DESK_NUMBER", ""),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        # "or": an empty DATABASE_URL= line in .env also means "use the default file"
        database_url=os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL,
        secret_key=os.getenv("SECRET_KEY", ""),
        access_token_minutes=int(os.getenv("ACCESS_TOKEN_MINUTES") or 60),
        admin_email=os.getenv("ADMIN_EMAIL", ""),
        admin_password=os.getenv("ADMIN_PASSWORD", ""),
        admin_name=os.getenv("ADMIN_NAME") or "mediQ Admin",
        hospital_timezone=os.getenv("HOSPITAL_TIMEZONE") or "Asia/Kolkata",
    )
