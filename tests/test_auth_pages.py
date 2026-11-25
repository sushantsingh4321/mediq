"""
Tests for step 5: the login/signup pages are served and wired up.
(The browser behaviour itself is JavaScript; see LEARN.md for how to try it.)
Run from the mediq/ folder with:   pytest
"""

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_login_and_signup_pages_are_served():
    login = client.get("/login.html")
    assert login.status_code == 200
    assert 'id="login-form"' in login.text and 'type="password"' in login.text
    assert "auth.js" in login.text and "site.js" in login.text

    signup = client.get("/signup.html")
    assert signup.status_code == 200
    for field in ['name="full_name"', 'name="email"', 'name="phone"', 'name="password"', 'name="confirm"']:
        assert field in signup.text


def test_scripts_send_the_login_token():
    core = client.get("/core.js").text          # the shared helpers (design system step 1)
    assert "Authorization" in core and "goToLogin" in core
    assert "data-logout" in client.get("/site.js").text      # the website's Log out link
    # Every page loads core.js in <head>, so the helpers and the theme are ready early
    for page in ["/login.html", "/index.html", "/admin.html", "/design.html"]:
        assert '<script src="core.js"></script>' in client.get(page).text, page
    app_js = client.get("/app.js").text
    assert "authHeader()" in app_js and "SCREEN_ROLES" in app_js


def test_staff_page_declares_the_role_it_needs():
    assert 'data-require-roles="admin"' in client.get("/staff-callbacks.html").text


def test_a_server_hiccup_never_logs_people_out():
    """Only a real 401 forgets the login. Slow or failed checks are retried, and if the server
    still can't be reached the login is KEPT and a "Can't reach" banner is shown instead."""
    core = client.get("/core.js").text
    assert ".catch(() => { clearToken(); return null; })" not in core     # the old bug
    assert "async function whoAmI()" in core
    assert "res.status === 401) { clearToken(); return null; }" in core   # the one case that logs out
    assert "attempt <= 3" in core                                        # retries
    assert "Can't reach the hospital system right now." in core and '"offline"' in core
    # Every page that checks access stops quietly when offline instead of treating it as logged out
    for script in ["patient.js", "doctor-appointments.js", "pharmacy.js", "site.js", "dashboard.js"]:
        assert 'access === "offline"' in client.get(f"/{script}").text, script
