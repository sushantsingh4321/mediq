"""
Home page hero: the GradientASCII background (frontend/gradient-ascii.js) and
the live waits. Run from the mediq/ folder with:   pytest
"""

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_hero_has_the_effect_and_the_live_waits():
    page = client.get("/").text
    assert 'id="hero-ascii"' in page and 'aria-hidden="true"' in page      # decoration, hidden from screen readers
    assert page.index('src="gradient-ascii.js"') < page.index('src="home.js"')
    assert 'id="hero-waits"' in page and 'aria-live="polite"' in page      # real numbers, announced when they change
    assert "Book an appointment" in page and 'href="/book.html"' in page
    assert "GEN-012" not in page                                            # no invented "now serving" picture
    assert 'class="eyebrow"' not in page                                    # no label above the headline


def test_effect_script_is_plain_js_with_fallbacks():
    js = client.get("/gradient-ascii.js").text
    assert "window.GradientASCII = { mount }" in js
    assert 'getContext("webgl2"' in js and "return null" in js              # no WebGL 2: CSS background stays
    assert "prefers-reduced-motion" in js                                    # "reduce motion": no animation
    assert "IntersectionObserver" in js                                      # pauses when off screen
    assert "import " not in js and "useEffect" not in js                     # no React left
    home = client.get("/home.js").text
    assert 'shape: "horizon"' in home and "drawHeroWaits" in home


def test_home_sections_follow_the_new_design():
    page = client.get("/").text
    # One idea per screen: how it works, specialities, live band, hospitals, call back
    for part in ['class="steps"', 'id="spec-list"', 'class="live-band"', 'id="hospital-list"', 'id="enquiry-form"']:
        assert part in page, part
    # The old busy parts are gone
    for old in ["ns-strip", "service-card", "spec-grid"]:
        assert old not in page, old
    # Photos are local files with alt text, and their authors are credited
    assert 'src="img/doctors-at-work.jpg" alt="' in page and 'src="img/waiting-room.jpg" alt="' in page
    assert client.get("/img/doctors-at-work.jpg").status_code == 200
    js = client.get("/home.js").text
    assert "sf-credits" in js and "Legend1306" in js and "Harrison Keely" in js
    # Keyboard users can skip the menu
    assert "skip-link" in client.get("/site.js").text and 'id="main"' in page
