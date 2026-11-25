"""
English / हिन्दी: core.js translates the page with the dictionary in lang-hi.js.
Run from the mediq/ folder with:   pytest
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
DICT = (FRONTEND / "lang-hi.js").read_text(encoding="utf-8")


def test_the_engine_is_on_every_page_and_loads_the_dictionary():
    core = client.get("/core.js").text
    assert "mediq_lang" in core and "lang-hi.js" in core and "MutationObserver" in core
    assert "setLang" in core and "getLang" in core
    assert "coming soon" not in core                      # the old placeholder message is gone
    assert client.get("/lang-hi.js").status_code == 200
    for page in FRONTEND.glob("*.html"):
        assert '<script src="core.js"></script>' in page.read_text(encoding="utf-8"), page.name


def test_every_page_has_a_language_switch():
    assert "data-lang=\"hi\"" in client.get("/core.js").text          # app pages: in the app bar
    site = client.get("/site.js").text
    assert "data-switch-lang" in site and "हिन्दी" in site               # website pages: in the header


def test_what_people_type_is_never_translated():
    core = client.get("/core.js").text
    assert "textarea" in core and "notranslate" in core


def test_patient_pages_main_words_have_hindi():
    for english in ["Book an appointment", "My appointments", "Log in", "Create an account", "I've arrived",
                    "It's your turn", "Cancel booking", "Request a call back", "Emergency", "Doctor timetable",
                    "Incorrect email or password.", "Sorry, someone has just booked that slot. Pick another time.",
                    "Cardiology", "General Medicine", "Paediatrics", "Orthopaedics"]:
        line = f'"{english}":'
        assert line in DICT.replace('\\"', '"'), english
    # Every speciality and condition from the site data has a translation (they are searched too)
    import json
    data = json.loads((Path(__file__).resolve().parents[1] / "backend/app/data/site_content.json").read_text())
    for s in data["specialities"]:
        for word in [s["name"], *s["conditions"]]:
            assert f'"{word}":' in DICT, word


def test_dictionary_has_devanagari_and_no_empty_entries():
    assert re.search(r"[ऀ-ॿ]", DICT)
    assert '": ""' not in DICT
