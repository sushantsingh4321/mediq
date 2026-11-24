"""
Redesign step 1: the design system (DESIGN.md) and its bans, checked in the code.
Run from the mediq/ folder with:   pytest
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
CSS = (ROOT / "frontend" / "style.css").read_text()
PAGES = sorted((ROOT / "frontend").glob("*.html"))


def test_the_world_tokens_exist_in_light_and_dark():
    for token in ("--night", "--ink", "--cobalt", "--sky", "--ice", "--tint", "--font-mono"):
        assert f"{token}:" in CSS, token
    dark = CSS[CSS.index(':root[data-theme="dark"] {'):]
    dark = dark[:dark.index("}")]
    for token in ("--page", "--surface", "--text", "--link", "--action"):
        assert f"{token}:" in dark, token


def test_every_page_loads_geist_and_the_hindi_face():
    for page in PAGES:
        html = page.read_text()
        assert "family=Geist:" in html and "Noto+Sans+Devanagari" in html, page.name


def test_no_stripe_down_one_side_of_a_box():
    stripes = re.findall(r"border-left:\s*[2-9]px[^;]*;|border-left-(?:color|width)|inset\s+[2-9]px\s+0\s+0", CSS)
    assert stripes == []


def test_no_label_above_a_heading():
    for page in PAGES:
        assert 'class="eyebrow"' not in page.read_text(), page.name
    assert ".eyebrow" not in CSS


def test_no_violet():
    assert not re.search(r"#(8b5cf6|7c3aed|a78bfa|c4b5fd|6d28d9|9333ea)\b", CSS, re.I)


def test_browser_surfaces_are_themed():
    assert "::selection" in CSS and "accent-color" in CSS and "scrollbar-color" in CSS
    assert "text-underline-offset" in CSS


def test_design_docs_exist():
    assert "## Bans" in (ROOT / "DESIGN.md").read_text()
    assert "Book an appointment" in (ROOT / "PRODUCT.md").read_text()
