"""Header logo.

An uploaded logo must fit the space the old eyebrow + name occupied. If it
could set its own size, one oversized upload would push the search and
fullscreen buttons off the header.
"""
import re


def _header(html: str) -> str:
    """Just the rendered <header>. The class name also appears in the
    stylesheet and in a JS template string, so a whole-page search would
    match those and prove nothing about what actually rendered."""
    start = html.index('<header class="topbar">')
    return html[start:html.index("</header>", start)]


def test_header_shows_the_name_when_no_logo_is_set(client):
    import database as db
    db.set_setting("logo_text", "Studio X")
    header = _header(client.get("/").data.decode("utf-8"))
    assert "Studio X" in header
    assert "<img" not in header


def test_header_shows_the_logo_when_one_is_set(client):
    import database as db
    db.set_setting("logo_image", "mark.png")
    header = _header(client.get("/").data.decode("utf-8"))
    assert 'class="topbar-logo-img"' in header
    assert "/static/media/mark.png" in header


def test_logo_height_is_capped(client):
    """The cap is what stops an upload from resizing the header."""
    css = client.get("/").data.decode("utf-8")
    rule = re.search(r"\.topbar-logo-img\s*\{([^}]*)\}", css)
    assert rule, "no .topbar-logo-img rule"
    body = rule.group(1)
    assert "height: var(--logo-height)" in body
    assert "max-width: var(--logo-max-w)" in body
    assert "object-fit: contain" in body, "without contain, a logo would stretch"

    height = re.search(r"--logo-height:\s*(\d+)px", css)
    assert height, "--logo-height token missing"
    assert int(height.group(1)) <= 44, "logo taller than the header allows"


def test_made_by_eyebrow_is_gone(client):
    assert b"made by" not in client.get("/").data
