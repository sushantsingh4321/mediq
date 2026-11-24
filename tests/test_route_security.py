"""
Self-booking step 8: "enforce roles on every route", checked for EVERY route.

The test asks the app for all its /api routes and calls each one WITHOUT a
login. Only the routes in PUBLIC (each with its reason) may answer; every
other route must say 401. Routes that need a login must also check the ROLE,
unless they only touch the caller's own data (OWN_DATA).

So when someone adds a route later and forgets the login check, this fails.
Run from the mediq/ folder with:   pytest
"""

import itertools
import re

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.app.main import app
from helpers import admin_headers, login_headers, queue_token

client = TestClient(app)

PUBLIC = {
    # the website and the waiting room
    ("GET", "/api/health"): "is the server up",
    ("GET", "/api/site"): "website content",
    ("GET", "/api/hospital/summary"): "numbers only, for the city-wide view",
    ("GET", "/api/departments"): "department names",
    ("GET", "/api/departments/{dept_id}/stats"): "waiting counts and wait times, no names",
    ("GET", "/api/departments/{dept_id}/queue"): "live queue: visitors see initials only (Part 15)",
    ("GET", "/api/tokens/{token_id}"): "your token's place and wait: visitors see initials only",
    ("GET", "/api/wards"): "beds: visitors see initials only (Part 15)",
    ("GET", "/api/wards/availability"): "bed counts only",
    ("GET", "/api/ambulances/availability"): "ambulance counts only",
    # finding a doctor and a time (booking itself needs a login)
    ("GET", "/api/schedule"): "the weekly OPD timetable",
    ("GET", "/api/schedule/on-duty"): "who is in OPD now",
    ("GET", "/api/schedule/doctors"): "doctor names",
    ("GET", "/api/doctors"): "doctors in a department and their hours",
    ("GET", "/api/doctors/{doctor_id}/slots"): "free / taken times, no patient details",
    ("GET", "/api/pharmacy/medicines"): "medicine search: no cost prices",
    ("GET", "/api/pharmacy/categories"): "medicine categories",
    # forms anyone may send
    ("POST", "/api/auth/signup"): "create a patient account",
    ("POST", "/api/auth/login"): "log in",
    ("POST", "/api/enquiries"): "home page enquiry form",
    ("POST", "/api/callback"): "request a call back",
    # Twilio calls these, so they can't need a login; they check Twilio's signature instead
    # (skipped only in DRY_RUN practice mode, where nothing is really dialled)
    ("POST", "/api/callback/{callback_id}/twiml"): "Twilio webhook",
    ("POST", "/api/callback/{callback_id}/dial-status"): "Twilio webhook",
    ("POST", "/api/callback/{callback_id}/status"): "Twilio webhook",
}

# Need a login, but only ever read or change the caller's OWN data, so any role is fine
OWN_DATA = {
    ("GET", "/api/auth/me"), ("POST", "/api/auth/logout"),
    ("GET", "/api/notifications/me"), ("POST", "/api/notifications/{notification_id}/read"),
    ("POST", "/api/notifications/read-all"),
}


def all_routes(routes=None):
    """Every APIRoute, including those inside included routers (this FastAPI version groups them)."""
    for r in app.routes if routes is None else routes:
        if hasattr(r, "original_router"):
            yield from all_routes(r.original_router.routes)
        elif isinstance(r, APIRoute) and r.path.startswith("/api"):
            yield r


def checks(route) -> set[str]:
    """Names of everything the route runs before it starts (its dependencies)."""
    found, todo = set(), [route.dependant]
    while todo:
        dep = todo.pop()
        found.add(getattr(dep.call, "__qualname__", ""))
        todo.extend(dep.dependencies)
    return found


ROUTES = [(method, r.path, r) for r in all_routes() for method in sorted(r.methods)]


def test_we_found_all_the_routes():
    assert len(ROUTES) > 80                     # sanity: the audit really sees every module


def test_every_route_needs_a_login_unless_it_is_on_the_public_list():
    surprises = []
    for method, path, _ in ROUTES:
        url = re.sub(r"\{[^}]+\}", "999999", path)          # a made-up id: nothing real is touched
        status = client.request(method, url, json={}).status_code
        public = (method, path) in PUBLIC
        if public and status == 401:
            surprises.append(f"{method} {path}: on the public list but asks for a login")
        if not public and status != 401:
            surprises.append(f"{method} {path}: answered {status} without a login")
    assert surprises == []


def test_logged_in_routes_also_check_the_role():
    no_role_check = [f"{m} {p}" for m, p, r in ROUTES
                     if (m, p) not in PUBLIC and (m, p) not in OWN_DATA
                     and not any("require_roles" in c for c in checks(r))]
    assert no_role_check == []


def test_public_and_own_data_lists_have_no_stale_entries():
    existing = {(m, p) for m, p, _ in ROUTES}
    assert set(PUBLIC) - existing == set() and OWN_DATA - existing == set()


# ---------------------------------------------------------------- the fix this audit found

_n = itertools.count(1)


def test_token_lookup_shows_initials_to_strangers():
    dept = client.get("/api/departments").json()[0]
    token = queue_token("Kavya Rao Iyer", dept["id"])
    url = f"/api/tokens/{token['id']}"
    assert client.get(url).json()["patient_name"] == "K. R. I."                   # a visitor
    email = f"stranger{next(_n)}@audit.example"
    client.post("/api/auth/signup", json={"full_name": "Stranger", "email": email, "password": "audit-password-1"})
    stranger = login_headers(email, "audit-password-1")
    assert client.get(url, headers=stranger).json()["patient_name"] == "K. R. I." # another patient
    assert client.get(url, headers=admin_headers()).json()["patient_name"] == "Kavya Rao Iyer"   # staff
