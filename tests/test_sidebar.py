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
    # Main view: key numbers, one trend, one comparison. Details sit in tabs.
    for part in ['id="kpis"', 'id="chart-arrivals"', 'id="chart-waits"', 'role="tablist"', 'role="tabpanel"',
                 'id="queues-table"', 'id="chart-beds"', 'id="chart-bookings"', 'id="pharmacy-table"',
                 'src="shell.js"', 'id="app-bar"', 'class="g12"']:
        assert part in html, part
    assert html.count('role="tab"') == 5 and html.count("hidden>") >= 4      # one tab open at a time
    js = client.get("/dashboard.js").text
    assert "/admin/activity" in js and "/admin/overview" in js   # real numbers only
    assert 'checkAccess(u, ["admin"])' in js                     # admins only (the API checks too)
    assert "lineChart" in js and "sortedBars" in js              # a line for the trend, sorted bars to compare
    assert "ArrowRight" in js                                     # tabs work with the keyboard
    assert "<script" not in js and "chart.js" not in js.lower()  # plain SVG, no chart library
    assert '/dashboard.html' in client.get("/shell.js").text     # in the sidebar
    assert 'admin: "/dashboard.html"' in client.get("/core.js").text   # admins land here after login
    css = client.get("/style.css").text
    assert ".g12" in css and "repeat(12, minmax(0, 1fr))" in css         # the 12-column grid
    assert ':root[data-theme="dark"] {\n  --c-neutral' in css             # its own dark colours
    assert ".dash-tbl .num { text-align: right" in css                     # numbers right-aligned


def test_staff_pages_have_no_website_footer():
    # Staff tools end with their content; the public website keeps its footer
    for name in ["admin", "ambulance", "index", "staff-callbacks"]:
        assert 'id="site-footer"' not in client.get(f"/{name}.html").text, name
    for name in WEBSITE_PAGES:
        assert 'id="site-footer"' in client.get(f"/{name}.html" if name != "home" else "/").text, name


def test_the_website_header_always_fits():
    """'Book an appointment' went off the page: a signed-in name made the header too wide."""
    site = client.get("/site.js").text
    assert 'class="avatar"' in site and "initials(" in site        # signed in: a small round button...
    assert 'class="panel-btn" data-logout' in site                   # ...whose menu has Log out
    css = client.get("/style.css").text
    assert "@media (max-width: 1280px)" in css                       # the menu button takes over earlier
    assert "header.site-header .header-actions { flex-shrink: 0; }" in css
    assert "header.site-header .logo small { display: none; }" in css


def test_tables_and_forms_fit_on_phones():
    """Wide tables ran off phone screens; now each row becomes a labelled card under 640px."""
    core = client.get("/core.js").text
    assert "function labelTables" in core and "data-label" in core and "stack-on-phone" in core
    assert "requestAnimationFrame(() => { tableTimer" not in core          # paused in background tabs
    css = client.get("/style.css").text
    assert "table.stack-on-phone tr { display: grid;" in css
    assert "content: attr(data-label)" in css
    assert ".enquiry-form > *, .phone-row > * { min-width: 0; }" in css   # forms shrink on 320px phones
    assert ".tabs { flex-wrap: wrap;" in css


def test_weekday_names_only_change_inside_dates():
    core = client.get("/core.js").text
    assert "DAY_IN_DATE" in core and "Sun Pharma" in core                 # a company, not Sunday
