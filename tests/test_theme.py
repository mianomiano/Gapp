import theme


def test_no_settings_produces_no_css():
    assert theme.css_overrides({}) == ""


def test_accent_colour_becomes_a_variable():
    css = theme.css_overrides({"accent_color": "#ff0066"})
    assert "--green: #ff0066" in css
    assert ":root" in css


def test_shorthand_hex_is_accepted():
    assert "--green: #f06" in theme.css_overrides({"accent_color": "#f06"})


def test_radius_is_emitted_with_units():
    assert "--cell-radius: 6px" in theme.css_overrides({"cell_radius": "6"})


def test_invalid_colour_is_ignored():
    """Values land inside a <style> tag, so anything that is not a plain hex
    colour must never reach it."""
    css = theme.css_overrides({"accent_color": "red; } body { display:none"})
    assert "display:none" not in css
    assert css == ""


def test_style_tag_cannot_be_closed_early():
    css = theme.css_overrides({"accent_color": "#fff</style><script>alert(1)"})
    assert "</style>" not in css
    assert "script" not in css


def test_radius_is_clamped_to_the_slider_range():
    assert "--cell-radius: 12px" in theme.css_overrides({"cell_radius": "999"})
    assert "--cell-radius: 0px" in theme.css_overrides({"cell_radius": "-5"})


def test_non_numeric_radius_is_ignored():
    assert theme.css_overrides({"cell_radius": "abc"}) == ""


def test_uploaded_font_overrides_the_family():
    css = theme.css_overrides({"font_display": "MyFont.woff2"})
    assert "@font-face" in css
    assert "/static/fonts/MyFont.woff2" in css
    assert "AppDisplay" in css


def test_font_filename_with_a_path_is_rejected():
    """A traversal in the stored filename would let the page reference
    anything on disk."""
    assert theme.css_overrides({"font_display": "../../../etc/passwd"}) == ""
    assert theme.css_overrides({"font_display": "a/b.woff2"}) == ""


def test_theme_reaches_the_page(client):
    import database as db
    db.set_setting("accent_color", "#ff0066")
    assert b"--green: #ff0066" in client.get("/").data


def test_theme_block_comes_after_the_main_stylesheet(client):
    """Later wins in CSS — an override placed first would do nothing."""
    import database as db
    db.set_setting("accent_color", "#ff0066")
    html = client.get("/").data.decode("utf-8")
    assert html.index("--green: #ff0066") > html.index("--bg-page")
