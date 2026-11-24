"""
pytest runs this file BEFORE any test file, so this happens before the app is imported.

DRY_RUN=true means no test can ever ring a real phone or send a real SMS, even
if your own .env says DRY_RUN=false (variables set here win over .env).

DATABASE_URL points at a brand-new, empty SQLite file in a temporary folder, so
tests never touch your real mediq.db (and every test run starts clean).
"""

import os
import tempfile
from pathlib import Path

os.environ["DRY_RUN"] = "true"

_test_dir = Path(tempfile.mkdtemp(prefix="mediq-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_test_dir / 'test.db'}"

# To run every test against PostgreSQL instead (as on Neon), point
# TEST_DATABASE_URL at an EMPTY PostgreSQL database you don't need:
#   TEST_DATABASE_URL=postgresql://user:pass@localhost/mediq_test pytest
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

# A fixed key just for tests (never use this anywhere real).
os.environ["SECRET_KEY"] = "test-only-secret-key-0123456789-abcdefghijklmnop"

# The first admin, created on start-up from these settings (test-only values).
os.environ["ADMIN_EMAIL"] = "admin@mediq.example"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
