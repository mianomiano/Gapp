import json
import re
from pathlib import Path

import i18n

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

# A text node holding two or more Latin letters. Deliberately crude — it only
# has to catch what a human would recognise as a forgotten UI string. The
# punctuation class is wide on purpose: an early version omitted · and —, and
# quietly missed "No files yet · add media in /admin".
HARDCODED = re.compile(r">\s*([A-Za-z][A-Za-z0-9 ,.'!?/·—–…&:;()-]{2,})\s*<")


def _hardcoded_strings(path: Path):
    """UI text still baked into the markup instead of going through t()."""
    html = path.read_text(encoding="utf-8")
    body = html[html.index("<body"):]
    # Strip script, style, and comments: code, CSS, and notes-to-self are
    # not UI copy and must not count as untranslated strings.
    body = re.sub(r"(?s)<script\b.*?</script>", "", body)
    body = re.sub(r"(?s)<style\b.*?</style>", "", body)
    body = re.sub(r"(?s)<!--.*?-->", "", body)

    found = []
    for match in HARDCODED.finditer(body):
        text = match.group(1).strip()
        if "{{" in match.group(0) or "{%" in match.group(0):
            continue
        found.append(text)
    return sorted(set(found))


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


def _injected_dictionary(html: str) -> dict:
    """The window.I18N object. Read to end of line rather than to the first
    ';' — translations contain entities like &lt; whose semicolon would
    truncate the JSON mid-string."""
    start = html.index("window.I18N = ") + len("window.I18N = ")
    line = html[start:html.index("\n", start)].rstrip().rstrip(";")
    return json.loads(line)


def test_index_exposes_translations_to_javascript(client):
    html = client.get("/").data.decode("utf-8")
    assert _injected_dictionary(html)["nav.wall"] == "Wall"


def test_admin_exposes_translations_to_javascript(client):
    html = client.get("/admin").data.decode("utf-8")
    assert _injected_dictionary(html)["admin.save"] == "Save"


def test_gallery_does_not_ship_admin_strings(client):
    """The admin panel's ~110 strings are dead weight on every visitor."""
    keys = _injected_dictionary(client.get("/").data.decode("utf-8"))
    assert not [k for k in keys if k.startswith("admin.")]


def test_html_lang_attribute_follows_the_setting(client):
    import database as db
    db.set_setting("language", "ru")
    assert b'<html lang="ru"' in client.get("/").data


def test_index_has_no_hardcoded_ui_text():
    leftover = _hardcoded_strings(TEMPLATES / "index.html")
    assert leftover == [], f"Not yet translated: {leftover}"


def _js_hardcoded(path: Path):
    """UI text inside <script>: markup built in template literals, plus
    aria-labels. The markup scan cannot see these, and a literal here is
    just as untranslated — this gap hid 'Send Stars' in the post reader."""
    html = path.read_text(encoding="utf-8")
    scripts = re.findall(r"(?s)<script\b[^>]*>(.*?)</script>", html)

    found = []
    for code in scripts:
        # Text nodes inside HTML strings built by JS.
        for text in re.findall(r">\s*([A-Za-z][A-Za-z0-9 ,.'!?/·—–…&:;()-]{2,})\s*<", code):
            found.append(text.strip())
        # Hardcoded aria-labels in the same strings.
        for text in re.findall(r'aria-label="([A-Za-z][^"$]{2,})"', code):
            found.append(text.strip())
    return sorted(set(found))


def test_index_javascript_has_no_hardcoded_ui_text():
    leftover = _js_hardcoded(TEMPLATES / "index.html")
    assert leftover == [], f"Not yet translated (in JS): {leftover}"


def test_admin_has_no_hardcoded_ui_text():
    leftover = _hardcoded_strings(TEMPLATES / "admin.html")
    assert leftover == [], f"Not yet translated: {leftover}"


def test_admin_javascript_has_no_hardcoded_ui_text():
    leftover = _js_hardcoded(TEMPLATES / "admin.html")
    assert leftover == [], f"Not yet translated (in JS): {leftover}"


def _css_hardcoded(path: Path):
    """User-visible text in CSS content:. Neither other scan sees these —
    the markup scan strips <style> and the JS scan only reads <script>."""
    css_blocks = re.findall(
        r"(?s)<style\b[^>]*>(.*?)</style>", path.read_text(encoding="utf-8")
    )
    found = []
    for css in css_blocks:
        for text in re.findall(r"content:\s*'([^']{2,})'", css):
            if re.search(r"[A-Za-z]{2}", text):
                found.append(text)
    return sorted(set(found))


def test_admin_css_has_no_hardcoded_ui_text():
    leftover = _css_hardcoded(TEMPLATES / "admin.html")
    assert leftover == [], f"Not yet translated (in CSS): {leftover}"


def test_index_css_has_no_hardcoded_ui_text():
    leftover = _css_hardcoded(TEMPLATES / "index.html")
    assert leftover == [], f"Not yet translated (in CSS): {leftover}"
