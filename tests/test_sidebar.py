# The floating sidebar (frontend/shell.js) and the light/dark switch on every page.
from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

SIGNED_IN_PAGES = ["book", "my-appointments", "doctor-appointments", "pharmacy", "pharmacy-dispense",
                   "pharmacy-stock", "pharmacy-alerts", "pharmacy-suppliers", "index", "ambulance",
                   "admin", "staff-callbacks"]
WEBSITE_PAGES = ["home", "login", "signup", "callback", "schedule"]


def test_signed_in_pages_load_the_sidebar_before_their_own_script():
    for name in SIGNED_IN_PAGES:
        html = client.get(f"/{name}.html").text
        assert '<script src="shell.js"></script>' in html, name
        assert 'id="app-bar"' in html, name                 # the app bar sits beside the sidebar
        assert html.index('src="core.js"') < html.index('src="shell.js"'), name
    assert client.get("/shell.js").status_code == 200


def test_sidebar_folds_remembers_and_opens_as_a_drawer():
    js = client.get("/shell.js").text
    assert "mediq_sidebar" in js and "sb-folded" in js       # fold, remembered in localStorage
    assert "data-sidebar-open" in js and "Escape" in js       # phone drawer, closes with Esc
    assert "canSee" in js                                     # only the pages your role can open
    assert "data-sidebar-open" in client.get("/core.js").text   # the menu button lives in the app bar
    css = client.get("/style.css").text
    assert ".sidebar" in css and "body.sb-folded .sidebar" in css and "body.sb-open .sidebar" in css


def test_every_page_has_a_light_dark_switch():
    assert 'id="ab-theme"' in client.get("/core.js").text     # app pages: in the app bar
    site = client.get("/site.js").text
    assert 'id="sh-theme"' in site and "toggleTheme" in site  # website pages: in the header
    for name in WEBSITE_PAGES:
        html = client.get(f"/{name}.html" if name != "home" else "/").text
        assert 'id="site-header"' in html and 'src="site.js"' in html, name


def test_dashboard_page_has_kpis_charts_and_tables():
    html = client.get("/dashboard.html").text
    for part in ['id="kpis"', 'id="chart-arrivals"', 'id="chart-flow"', 'id="chart-waits"', 'id="chart-beds"',
                 'id="chart-bookings"', 'id="chart-pharmacy"', 'id="chart-calls"', 'src="shell.js"', 'id="app-bar"']:
        assert part in html, part
    assert html.count("Show as a table") >= 3            # every axis chart has a table version
    js = client.get("/dashboard.js").text
    assert "/admin/activity" in js and "/admin/overview" in js   # real numbers only
    assert 'checkAccess(u, ["admin"])' in js                     # admins only (the API checks too)
    assert "<script" not in js and "chart.js" not in js.lower()  # plain SVG, no chart library
    assert '/dashboard.html' in client.get("/shell.js").text     # in the sidebar
    assert 'admin: "/dashboard.html"' in client.get("/core.js").text   # admins land here after login
    css = client.get("/style.css").text
    assert "--c-green" in css and ':root[data-theme="dark"] {\n  --c-green' in css   # its own dark colours
