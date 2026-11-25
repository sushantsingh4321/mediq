"""
Pharmacy step 4: the pages are served and wired up.
(What they do in the browser is JavaScript; LEARN.md says how to try them.)
Run from the mediq/ folder with:   pytest
"""

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

PAGES = {
    "/pharmacy.html": "pharmacy-catalogue.js",
    "/pharmacy-dispense.html": "pharmacy-dispense.js",
    "/pharmacy-stock.html": "pharmacy-stock.js",
    "/pharmacy-alerts.html": "pharmacy-alerts.js",
    "/pharmacy-suppliers.html": "pharmacy-suppliers.js",
}


def test_every_pharmacy_page_is_served_with_its_scripts():
    for page, script in PAGES.items():
        html = client.get(page)
        assert html.status_code == 200, page
        # core.js in <head> (theme before the page is drawn), then the shared pharmacy helpers
        assert '<script src="core.js"></script>' in html.text, page
        assert html.text.index('src="pharmacy.js"') < html.text.index(f'src="{script}"'), page
        assert 'id="app-bar"' in html.text and 'src="shell.js"' in html.text, page   # menu = the sidebar
        assert 'id="ph-nav"' not in html.text, page                                 # no second menu
        assert client.get(f"/{script}").status_code == 200, script


def test_shared_helpers_and_menu_links():
    shared = client.get("/pharmacy.js").text
    for helper in ["medicinePicker", "schedulePill", "expiryPill", "window.PH"]:
        assert helper in shared
    assert 'pharmacist: "/pharmacy-dispense.html"' in client.get("/core.js").text   # where pharmacists land
    assert 'href="/pharmacy.html"' in client.get("/site.js").text                    # menu: no longer "Soon"


def test_doctor_screen_has_the_add_prescription_form():
    page = client.get("/index.html").text
    assert 'id="rx-form"' in page and "data-action" in page
    assert page.index('src="pharmacy.js"') < page.index('src="app.js"')
    assert "/pharmacy/prescriptions" in client.get("/app.js").text


def test_the_bill_prints_on_its_own():
    css = client.get("/style.css").text
    assert "@media print" in css and "#bill-area" in css
    assert "[hidden] { display: none !important; }" in css
