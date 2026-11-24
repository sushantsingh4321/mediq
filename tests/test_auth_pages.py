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
    site = client.get("/site.js").text
    assert "Authorization" in site and "goToLogin" in site and "logout-btn" in site
    app_js = client.get("/app.js").text
    assert "authHeader()" in app_js and "SCREEN_ROLES" in app_js


def test_staff_page_declares_the_role_it_needs():
    assert 'data-require-roles="receptionist"' in client.get("/staff-callbacks.html").text
