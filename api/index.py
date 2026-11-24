"""
Vercel's door into mediQ.

Vercel runs every Python file in the api/ folder as a "serverless function".
This one hands the requests to our FastAPI app; vercel.json sends every
/api/... request here. Locally you don't need this file: uvicorn runs
backend.app.main directly.

(Serverless = no always-on server. Vercel starts the app when a request comes
in and may stop it when it's quiet, so nothing may be kept in memory between
requests: everything lives in the database.)
"""

import sys
from pathlib import Path

# Make "backend" importable: add the project folder (the parent of api/) to Python's search path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.main import app  # noqa: E402  (Vercel looks for a variable called "app")
