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
