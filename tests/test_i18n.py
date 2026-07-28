import json

import i18n


def test_english_loads():
    strings = i18n.translations("en")
    assert strings["nav.wall"] == "Wall"


def test_unknown_language_falls_back_to_english():
    assert i18n.translations("klingon") == i18n.translations("en")


def test_missing_key_returns_the_key_itself():
    # A missing string must never render as "None" or crash the page — it
    # should show up as a visible key so the gap is obvious.
    assert i18n.lookup("en", "no.such.key") == "no.such.key"


def test_default_language_is_english(temp_db):
    assert i18n.current_language() == "en"


def test_language_setting_is_respected(temp_db):
    import database as db
    db.set_setting("language", "ru")
    assert i18n.current_language() == "ru"


def test_unavailable_language_setting_falls_back(temp_db):
    import database as db
    db.set_setting("language", "klingon")
    assert i18n.current_language() == "en"


def test_index_exposes_translations_to_javascript(client):
    html = client.get("/").data.decode("utf-8")
    assert "window.I18N" in html
    start = html.index("window.I18N = ") + len("window.I18N = ")
    end = html.index(";", start)
    assert json.loads(html[start:end])["nav.wall"] == "Wall"


def test_html_lang_attribute_follows_the_setting(client):
    import database as db
    db.set_setting("language", "ru")
    assert b'<html lang="ru"' in client.get("/").data
