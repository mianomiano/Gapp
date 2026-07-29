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


import io


def test_admin_can_save_theme_settings(admin_client):
    resp = admin_client.post("/api/admin/settings", data={
        "accent_color": "#ff0066",
        "cell_radius": "6",
    })
    assert resp.status_code == 200
    import database as db
    settings = db.get_settings()
    assert settings["accent_color"] == "#ff0066"
    assert settings["cell_radius"] == "6"


def test_font_upload_is_stored(admin_client):
    resp = admin_client.post("/api/admin/settings", data={
        "font_display_file": (io.BytesIO(b"fake-font-bytes"), "MyFont.woff2"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 200
    import database as db
    stored = db.get_settings()["font_display"]
    assert stored.endswith(".woff2")
    import theme
    assert theme.FONT_FILE.match(stored), f"stored name is unusable: {stored}"


def test_font_upload_rejects_non_font_files(admin_client):
    resp = admin_client.post("/api/admin/settings", data={
        "font_display_file": (io.BytesIO(b"<script>"), "evil.html"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400
    import database as db
    assert not db.get_settings().get("font_display")


def test_theme_settings_require_admin(client):
    assert client.post("/api/admin/settings",
                       data={"accent_color": "#fff"}).status_code == 401


def test_font_upload_goes_through_the_storage_backend(admin_client, tmp_path):
    """Fonts must outlive a redeploy.

    They used to be written straight into static/fonts, which on a host with
    an ephemeral filesystem meant every deploy silently reverted the app to
    its bundled fonts while the setting still named the uploaded file — a 404
    inside a @font-face, which fails with no error anywhere.
    """
    admin_client.post("/api/admin/settings", data={
        "font_display_file": (io.BytesIO(b"stub"), "Probe.woff2"),
    }, content_type="multipart/form-data")

    import storage
    written = list((tmp_path / "media").glob("Probe_*.woff2"))
    assert written, "upload did not reach the storage backend"
    assert written[0].read_bytes() == b"stub"

    # And the URL in the stylesheet must be the backend's, not a guessed path.
    import database as db
    import theme
    css = theme.css_overrides(db.get_settings(),
                              font_url=storage.backend().url)
    assert f"/static/media/{written[0].name}" in css


def test_uploaded_font_url_comes_from_the_resolver():
    """A copy on R2 serves fonts from the bucket, not from this host."""
    import theme
    css = theme.css_overrides(
        {"font_display": "MyFont.woff2"},
        font_url=lambda name: f"https://cdn.example.com/{name}",
    )
    assert "url('https://cdn.example.com/MyFont.woff2')" in css


def test_accent_choice_repaints_its_whole_family():
    """Regression: --green changed while every border and fill stayed green.

    The dim and translucent variants were fixed values, so a new accent only
    moved the thin highlights — which read as the colour not changing.
    """
    import theme
    css = theme.css_overrides({"accent_color": "#c8ff00"})
    assert "--green: #c8ff00" in css
    assert "--green-dim: #4c6100" in css
    assert "--green-bg: rgba(200, 255, 0, 0.05)" in css
    assert "--green-soft: rgba(200, 255, 0, 0.12)" in css


def test_short_hex_accent_expands_before_deriving():
    import theme
    css = theme.css_overrides({"accent_color": "#f06"})
    assert "--green-bg: rgba(255, 0, 102, 0.05)" in css


def test_no_accent_means_no_derived_variables():
    """The bundled defaults must stay in force when nothing is chosen."""
    import theme
    css = theme.css_overrides({"cell_radius": "4"})
    assert "--green-dim" not in css
    assert "--green-soft" not in css
