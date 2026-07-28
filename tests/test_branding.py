"""No brand name may be baked into the code.

The visible name comes from the `logo_text` setting so a copy can be handed
to someone else and renamed entirely from the admin panel.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CODE = ["app.py", "database.py", "templates/index.html", "templates/admin.html",
        "seed_demo.py", "reset.py", "storage.py", "theme.py", "i18n.py",
        "restart.ps1", "share.bat", "tools/vendor_assets.py"]


def test_no_brand_name_in_code():
    offenders = {}
    for name in CODE:
        text = (ROOT / name).read_text(encoding="utf-8")
        count = text.lower().count("geroinzo")
        if count:
            offenders[name] = count
    assert offenders == {}, f"Hardcoded brand name remains: {offenders}"


def test_readme_has_no_brand_name():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "geroinzo" not in text.lower()


def test_default_logo_text_is_neutral(temp_db):
    import database as db
    assert "geroinzo" not in db.get_settings().get("logo_text", "").lower()


def test_page_title_follows_the_logo_setting(client):
    import database as db
    db.set_setting("logo_text", "Studio X")
    assert b"Studio X" in client.get("/").data


def test_admin_title_follows_the_logo_setting(client):
    import database as db
    db.set_setting("logo_text", "Studio X")
    assert b"Studio X" in client.get("/admin").data


def test_invoice_falls_back_to_the_logo_setting(temp_db):
    import database as db
    db.set_setting("logo_text", "Studio X")
    assert db.get_settings()["logo_text"] == "Studio X"


def test_api_settings_does_not_invent_a_brand(client):
    """An untouched copy opens with no name, not someone else's."""
    assert client.get("/api/settings").get_json()["logoText"] == ""
