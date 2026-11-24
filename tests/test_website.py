"""
Tests for the website: site data, the enquiry form and the pages themselves.
Run from the mediq/ folder with:   pytest
"""

from fastapi.testclient import TestClient

from backend.app.main import app
from helpers import admin_headers

# Logged in as admin: these endpoints need a login since step 4 (accounts)
client = TestClient(app, headers=admin_headers())

GOOD = {"name": "Ravi Kumar", "country_code": "+91", "mobile": "9876543210",
        "speciality": "Cardiology", "consent": True}


def post_enquiry(**changes):
    """Helper: send the GOOD enquiry with some fields changed."""
    return client.post("/api/enquiries", json={**GOOD, **changes})


def test_site_content_comes_from_the_data_file():
    d = client.get("/api/site").json()
    assert d["brand"] == "mediQ Health"
    # India's real public numbers (108 ambulance, 112 all emergencies), never invented phone numbers
    assert {e["number"] for e in d["emergency_numbers"]} == {"108", "112"}
    assert "411000" not in d["head_office"]                  # no postcodes in demo addresses
    assert d["default_country_code"] == "+91"
    assert all(h["state"] for h in d["hospitals"])          # menu groups by state
    assert all(s["conditions"] for s in d["specialities"])  # each speciality has conditions


def test_enquiry_is_saved():
    r = post_enquiry()
    assert r.status_code == 201
    saved = r.json()
    assert saved["name"] == "Ravi Kumar" and saved["id"] >= 1
    assert any(e["id"] == saved["id"] for e in client.get("/api/enquiries").json())


def test_enquiry_validation():
    assert post_enquiry(consent=False).status_code == 400        # must agree to be called
    assert post_enquiry(speciality="Astrology").status_code == 400  # not in the data file
    assert post_enquiry(country_code="+999").status_code == 400
    assert post_enquiry(name="   ").status_code == 400
    assert post_enquiry(mobile="98765 abc").status_code == 422   # digits only
    assert post_enquiry(mobile="123").status_code == 422         # too short


def test_enquiries_never_reach_the_city_summary():
    post_enquiry(name="Private Person", mobile="9000000001")
    body = client.get("/api/hospital/summary").text
    assert "Private Person" not in body and "9000000001" not in body


def test_pages_are_served():
    home = client.get("/")
    assert home.status_code == 200
    assert 'id="site-header"' in home.text and 'id="enquiry-form"' in home.text

    # The OPD system still works at /index.html, now with the shared header
    opd = client.get("/index.html")
    assert 'id="doctor-form"' in opd.text and 'id="site-header"' in opd.text

    for asset in ("/site.js", "/home.js", "/app.js", "/style.css"):
        assert client.get(asset).status_code == 200
