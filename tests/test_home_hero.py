"""
Home page: a bright hospital front page with real photos, the emergency numbers,
the main action first and the live waits. Run from the mediq/ folder with:   pytest
"""
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)
IMG = Path(__file__).resolve().parents[1] / "frontend" / "img"


def test_hero_is_bright_with_a_photo_and_the_live_waits():
    page = client.get("/").text
    assert 'class="hero-photo"' in page and 'src="img/doctor-with-child.jpg"' in page
    assert 'id="hero-waits"' in page and "Book an appointment" in page and 'href="/book.html"' in page
    assert "hero-ascii" not in page and "gradient-ascii.js" not in page       # the dark animation is gone
    assert client.get("/gradient-ascii.js").status_code == 404
    assert "GradientASCII" not in client.get("/home.js").text
    assert 'class="eyebrow"' not in page


def test_emergency_numbers_and_quick_links_are_in_view():
    page = client.get("/").text
    assert 'class="er-strip"' in page and 'href="tel:108"' in page and 'href="tel:112"' in page
    for href in ["/book.html", "/schedule.html", "/pharmacy.html", "/index.html#beds", "/callback.html"]:
        assert f'<a href="{href}">' in page, href


def test_photos_are_local_described_and_credited():
    page = client.get("/").text
    for name in ["doctor-with-child.jpg", "doctor-consulting.jpg", "checkup.jpg"]:
        assert f'src="img/{name}"' in page, name
        assert (IMG / name).exists(), name
    assert page.count(' alt="') >= 3
    assert not (IMG / "doctors-at-work.jpg").exists() and not (IMG / "waiting-room.jpg").exists()   # old photos removed
    js = client.get("/home.js").text
    assert "sf-credits" in js and "Shixart1985 (CC BY 2.0)" in js


def test_hero_facts_are_counted_from_the_data():
    js = client.get("/home.js").text
    assert "d.hospitals.length" in js and "d.specialities.length" in js     # never typed in by hand
    assert "SPEC_ICON" in js                                               # each speciality has an icon


def test_home_sections_follow_the_design():
    page = client.get("/").text
    for part in ['class="steps"', 'id="spec-list"', 'class="live-band"', 'id="hospital-list"', 'id="enquiry-form"']:
        assert part in page, part
    assert "skip-link" in client.get("/site.js").text and 'id="main"' in page
