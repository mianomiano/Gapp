# Shared Base: Copyable App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the gallery app copyable — a second person runs the same folder against their own bot, in Russian, with their own colours and fonts, configured entirely from the admin panel.

**Architecture:** All per-copy differences become rows in the existing SQLite `settings` table, read at render time. Translations are two static JSON files; the server picks one and passes it to Jinja (for markup) and to `window.I18N` (for JS strings). Theme values are injected as an inline `<style>` block overriding the `:root` custom properties the templates already use. External CDNs are vendored into `static/`.

**Tech Stack:** Python 3.14, Flask 3, SQLite (stdlib `sqlite3`), Jinja2, vanilla JS. Tests: pytest + Flask test client. Font conversion: `fonttools` + `brotli`.

## Global Constraints

- **Python:** 3.14.6 at `C:\Users\Shadow\AppData\Local\Programs\Python\Python314\python.exe`. Invoke pytest as `python -m pytest`.
- **No network calls at request time.** Every font, icon, and stylesheet must resolve from `static/`. This is the hard requirement that makes the Russian copy work.
- **Migrations follow the existing pattern** (`database.py:117-122`): read `PRAGMA table_info`, then `ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT …`. Never drop or rewrite a table — `gallery.db` holds live content.
- **Tests never touch `gallery.db`.** The `client` fixture repoints `database.DB_PATH` at a temp file.
- **Default language is English.** `language` setting values are exactly `en` and `ru`.
- **Brand name comes from the `logo_text` setting**, never a literal. After Task 10 the string `Geroinzo` must not appear in any file under `templates/`, `app.py`, or `database.py`.
- **Restart to see changes:** `.\restart.ps1` (debug is off, no autoreload).
- **Commit after every task.** The repo is at `C:\GEROINZO\geroinzo-gallery`, branch `main`.

---

## File Structure

**Create:**
- `tests/conftest.py` — pytest fixtures: isolated DB, Flask test client, admin session
- `tests/test_assets.py` — asserts no external hosts in rendered HTML
- `tests/test_i18n.py` — translation loading, completeness, language switching
- `tests/test_theme.py` — settings → CSS variable injection
- `tests/test_stars.py` — stars modes, donation/unlock split
- `tests/test_posts.py` — post media (no cap), aspect ratio fields
- `i18n.py` — loads `lang/*.json`, exposes `translations(lang)` and `t()`
- `theme.py` — builds the `:root` override CSS from settings
- `lang/en.json`, `lang/ru.json` — UI strings
- `tools/vendor_assets.py` — one-off: download icons, download default fonts, convert local `.ttf` → `.woff2`
- `static/vendor/tabler-icons.min.css` + `static/vendor/fonts/` — vendored icon font
- `static/fonts/*.woff2` — vendored default fonts

**Modify:**
- `app.py` — render context (lang, theme), settings whitelist, stars mode, post media cap
- `database.py` — `show_stars` migrations on `posts` and `media`; image dimension columns
- `templates/index.html` — remove CDNs, `t()` calls, theme block, layout fixes
- `templates/admin.html` — remove CDN, `t()` calls, Appearance tab
- `requirements.txt` — add `pytest`; `fonttools`/`brotli` are dev-only (tools script)

---

### Task 1: Test harness

Nothing in this repo is currently tested. Every later task depends on this fixture.

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing
- Produces: pytest fixtures `client` (Flask test client on an isolated DB) and `admin_client` (same, with `session["is_admin"] = True`). Every later test file uses these two names.

- [ ] **Step 1: Add pytest to requirements**

```
flask>=3.0
python-dotenv>=1.0
requests>=2.31
pytest>=8.0
```

- [ ] **Step 2: Install it**

Run: `python -m pip install -r requirements.txt`
Expected: pytest installs without error.

- [ ] **Step 3: Write the fixtures**

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures.

Every test runs against a throwaway SQLite file, never the live gallery.db.
database.DB_PATH is read inside get_conn() at call time, so repointing the
module attribute before init_db() is enough to isolate the whole app.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db  # noqa: E402


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the database module at an empty file and create the schema."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    return path


@pytest.fixture
def app(temp_db, tmp_path, monkeypatch):
    """The Flask app, wired to the temp DB and a temp media directory."""
    import app as app_module

    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(app_module, "MEDIA_DIR", media)
    app_module.app.config.update(TESTING=True, SECRET_KEY="test-key")
    return app_module.app


@pytest.fixture
def client(app):
    """Anonymous visitor."""
    return app.test_client()


@pytest.fixture
def admin_client(app):
    """Logged-in admin — skips the password round trip."""
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["is_admin"] = True
    return c
```

- [ ] **Step 4: Write the failing smoke test**

Create `tests/test_smoke.py`:

```python
def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<!DOCTYPE html>" in resp.data


def test_admin_api_requires_login(client):
    assert client.get("/api/admin/media").status_code == 401


def test_admin_api_allows_logged_in(admin_client):
    assert admin_client.get("/api/admin/media").status_code == 200


def test_tests_do_not_touch_the_real_database(temp_db):
    import database as db
    assert db.DB_PATH == temp_db
    assert "gallery.db" not in str(db.DB_PATH)
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: all 4 PASS. If `test_index_renders` fails on a missing template, check the `sys.path` insert in conftest resolves to the repo root.

- [ ] **Step 6: Commit**

```bash
git add tests/ requirements.txt
git commit -m "test: add pytest harness with isolated database fixtures"
```

---

### Task 2: Vendor the Tabler icon font

Every control in both templates is a Tabler icon loaded from jsDelivr. From Russia that CDN is unreliable, so the recipient's copy would render with no icons at all. The URL is also pinned to `@latest`, which can change under us.

**Files:**
- Create: `tools/vendor_assets.py`
- Create: `static/vendor/tabler-icons.min.css` (generated)
- Create: `static/vendor/fonts/` (generated)
- Create: `tests/test_assets.py`
- Modify: `templates/index.html:1152`, `templates/admin.html:7`

**Interfaces:**
- Consumes: nothing
- Produces: `/static/vendor/tabler-icons.min.css` served by Flask's static route. Task 3 extends the same `tools/vendor_assets.py` script.

- [ ] **Step 1: Write the failing test**

Create `tests/test_assets.py`:

```python
"""The app must load zero external hosts — see Global Constraints."""
import re

import pytest

EXTERNAL = re.compile(
    rb"https?://(?!telegram\.org)[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE
)


def _external_hosts(html: bytes):
    """Every off-site URL in the markup, except the Telegram SDK, which is
    required by Telegram itself and is reachable wherever the app opens."""
    return sorted(set(EXTERNAL.findall(html)))


def test_index_loads_no_external_hosts(client):
    assert _external_hosts(client.get("/").data) == []


def test_admin_loads_no_external_hosts(client):
    assert _external_hosts(client.get("/admin").data) == []


def test_icon_stylesheet_is_served_locally(client):
    assert b"/static/vendor/tabler-icons.min.css" in client.get("/").data
    assert client.get("/static/vendor/tabler-icons.min.css").status_code == 200
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python -m pytest tests/test_assets.py -v`
Expected: FAIL — the reported hosts include `cdn.jsdelivr.net` and `fonts.googleapis.com`.

- [ ] **Step 3: Write the vendoring script**

Create `tools/vendor_assets.py`:

```python
"""One-off: pull external assets into static/ so the app needs no CDN.

Run from the repo root:   python tools/vendor_assets.py
Commit whatever it writes. Re-run only to bump the pinned version.
"""
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "static" / "vendor"
VENDOR_FONTS = VENDOR / "fonts"

# Pinned deliberately. @latest can change the glyph set without warning.
TABLER_VERSION = "3.31.0"
TABLER_BASE = f"https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@{TABLER_VERSION}"


def fetch(url: str) -> bytes:
    print(f"  GET {url}")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def vendor_tabler() -> None:
    VENDOR_FONTS.mkdir(parents=True, exist_ok=True)
    css = fetch(f"{TABLER_BASE}/dist/tabler-icons.min.css").decode("utf-8")

    # The CSS references its font files by relative path; download each one
    # and rewrite the url() to point at our own folder.
    for ref in sorted(set(re.findall(r"url\(['\"]?([^'\")?#]+)", css))):
        name = Path(ref).name
        if not name.endswith((".woff2", ".woff", ".ttf", ".eot")):
            continue
        # woff2 alone covers every browser Telegram runs on.
        if not name.endswith(".woff2"):
            continue
        (VENDOR_FONTS / name).write_bytes(
            fetch(f"{TABLER_BASE}/dist/fonts/{name}")
        )
        css = css.replace(ref, f"fonts/{name}")

    # Drop now-dead references to formats we did not download.
    css = re.sub(r",?\s*url\([^)]*\.(woff|ttf|eot)[^)]*\)\s*format\([^)]*\)", "", css)
    (VENDOR / "tabler-icons.min.css").write_text(css, encoding="utf-8")
    print(f"  wrote {VENDOR / 'tabler-icons.min.css'}")


if __name__ == "__main__":
    print(f"Vendoring Tabler icons {TABLER_VERSION}...")
    try:
        vendor_tabler()
    except requests.RequestException as exc:
        sys.exit(f"Download failed: {exc}")
    print("Done.")
```

- [ ] **Step 4: Run it**

Run: `python tools/vendor_assets.py`
Expected: writes `static/vendor/tabler-icons.min.css` and at least one `.woff2` under `static/vendor/fonts/`. Verify with `dir static\vendor\fonts`.

- [ ] **Step 5: Point both templates at the local copy**

In `templates/index.html:1152` replace the jsDelivr `<link>` with:

```html
  <link rel="stylesheet" href="/static/vendor/tabler-icons.min.css" />
```

In `templates/admin.html:7` replace the jsDelivr `<link>` with the identical line.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_assets.py -v`
Expected: `test_icon_stylesheet_is_served_locally` PASSES. The two `no_external_hosts` tests still FAIL, reporting only `fonts.googleapis.com` / `fonts.gstatic.com` — Task 3 clears those.

- [ ] **Step 7: Commit**

```bash
git add tools/ static/vendor/ templates/ tests/test_assets.py
git commit -m "feat: vendor Tabler icon font, pin version, drop jsDelivr

The CDN is unreliable from Russia and every control in both templates is
an icon, so the Russian copy would render with no icons at all. @latest
was also unpinned and could change the glyph set without warning."
```

---

### Task 3: Self-host the fonts

Removes the last external host and wires up the `@font-face` blocks, which have been commented-out `YOUR_DISPLAY_FONT` placeholders since the project started (`index.html:25-51`).

Space Grotesk and Share Tech Mono are both SIL Open Font License, so bundling them is fine. They stay the defaults; admin-uploaded fonts override them in Task 8.

**Files:**
- Modify: `tools/vendor_assets.py`
- Create: `static/fonts/*.woff2` (generated)
- Modify: `templates/index.html:11-14` (remove Google links), `:25-51` (real `@font-face`)

**Interfaces:**
- Consumes: `fetch()` from Task 2
- Produces: CSS families `AppDisplay` and `AppMono`, referenced by `--font-display` / `--font-mono`. Task 8 overrides the `src` of these same two families.

- [ ] **Step 1: Add font vendoring to the script**

Append to `tools/vendor_assets.py`, above the `__main__` block:

```python
FONTS = ROOT / "static" / "fonts"

# Google's CSS API returns woff2 URLs when asked with a modern UA.
GOOGLE_CSS = (
    "https://fonts.googleapis.com/css2"
    "?family=Space+Grotesk:wght@400;700&family=Share+Tech+Mono&display=swap"
)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"}


def vendor_default_fonts() -> None:
    """Download the two default families as woff2 so no CDN is needed.

    Google serves hash-named files, so each is saved under a deterministic
    name the template can reference directly.
    """
    FONTS.mkdir(parents=True, exist_ok=True)
    resp = requests.get(GOOGLE_CSS, headers=UA, timeout=60)
    resp.raise_for_status()

    # Each @font-face block carries its family and weight above the src url.
    blocks = resp.text.split("@font-face")
    for block in blocks:
        family = re.search(r"font-family:\s*'([^']+)'", block)
        weight = re.search(r"font-weight:\s*(\d+)", block)
        url = re.search(r"url\((https://[^)]+\.woff2)\)", block)
        if not (family and url):
            continue
        slug = family.group(1).replace(" ", "")
        name = f"{slug}-{weight.group(1) if weight else '400'}.woff2"
        (FONTS / name).write_bytes(fetch(url.group(1)))
        print(f"  wrote {FONTS / name}")


def convert_local_ttf(source: Path) -> None:
    """Convert every .ttf in `source` to .woff2 in static/fonts.

    woff2 is 2-3x smaller than ttf, which matters on mobile data. Requires
    `pip install fonttools brotli` — dev-only, not a runtime dependency.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        sys.exit("Install the converter first:  pip install fonttools brotli")

    FONTS.mkdir(parents=True, exist_ok=True)
    for ttf in sorted(source.glob("*.ttf")):
        out = FONTS / (ttf.stem.replace(" ", "") + ".woff2")
        font = TTFont(str(ttf))
        font.flavor = "woff2"
        font.save(str(out))
        print(f"  {ttf.name} -> {out.name}")
```

Then change the `__main__` block to:

```python
if __name__ == "__main__":
    print(f"Vendoring Tabler icons {TABLER_VERSION}...")
    try:
        vendor_tabler()
        print("Vendoring default fonts...")
        vendor_default_fonts()
    except requests.RequestException as exc:
        sys.exit(f"Download failed: {exc}")

    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
        print(f"Converting .ttf files in {src}...")
        convert_local_ttf(src)
    print("Done.")
```

- [ ] **Step 2: Run it**

Run: `python tools/vendor_assets.py`
Expected: several `.woff2` files appear in `static/fonts/`. Verify with `dir static\fonts`.

- [ ] **Step 3: Replace the commented-out placeholders with real font-face blocks**

Step 2 writes deterministic filenames: `SpaceGrotesk-400.woff2`, `SpaceGrotesk-700.woff2`, `ShareTechMono-400.woff2`. Confirm with `dir static\fonts` before pasting.

In `templates/index.html`, replace the whole commented block at lines 25-51 with:

```css
    @font-face {
      font-family: 'AppDisplay';
      src: url('/static/fonts/SpaceGrotesk-400.woff2') format('woff2');
      font-weight: 400;
      font-style: normal;
      font-display: swap;
    }

    @font-face {
      font-family: 'AppDisplay';
      src: url('/static/fonts/SpaceGrotesk-700.woff2') format('woff2');
      font-weight: 700;
      font-style: normal;
      font-display: swap;
    }

    @font-face {
      font-family: 'AppMono';
      src: url('/static/fonts/ShareTechMono-400.woff2') format('woff2');
      font-weight: 400;
      font-style: normal;
      font-display: swap;
    }
```

`font-display: swap` (not `block`): text stays readable while the font loads instead of showing blank.

- [ ] **Step 4: Point the tokens at the local families**

In `templates/index.html`, in the `:root` block, replace the three font variables:

```css
      --font-display:  'AppDisplay', system-ui, 'Segoe UI', Roboto, Arial, sans-serif;
      --font-mono:     'AppMono', ui-monospace, 'Cascadia Mono', Consolas, monospace;
      --font-stamp:    'AppMono', ui-monospace, 'Cascadia Mono', Consolas, monospace;
```

- [ ] **Step 5: Delete the Google Fonts links**

Remove `templates/index.html` lines 11-14 entirely — the comment plus all three `<link>` tags.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_assets.py -v`
Expected: all 3 PASS. If a `no_external_hosts` test still fails, the reported host name tells you exactly which reference was missed.

- [ ] **Step 7: Verify in the browser**

Run: `.\restart.ps1` then open http://localhost:5050
Expected: icons in the bottom nav and header still render; text is not in a serif fallback. Open DevTools → Network, filter "Font": every entry is same-origin.

- [ ] **Step 8: Commit**

```bash
git add tools/ static/fonts/ templates/index.html
git commit -m "feat: self-host fonts, drop Google Fonts

Removes the last external host. Wires up the @font-face blocks that have
been commented-out YOUR_DISPLAY_FONT placeholders since the start, under
neutral family names (AppDisplay/AppMono) ahead of de-branding."
```

---

### Task 4: Translation infrastructure

Server-side translation: Jinja renders markup strings through `t()`, and the same dictionary is injected as `window.I18N` for strings that JavaScript sets at runtime. One source of truth, two consumers.

**Files:**
- Create: `i18n.py`
- Create: `lang/en.json`
- Create: `tests/test_i18n.py`
- Modify: `app.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `i18n.translations(lang: str) -> dict[str, str]` — loads and caches a language file, falling back to `en` for an unknown code
  - `i18n.current_language() -> str` — reads the `language` setting, defaulting to `"en"`
  - Jinja global `t(key: str) -> str` — returns the translation, or the key itself if missing
  - Template context variables `lang` and `i18n_json`

- [ ] **Step 1: Write the failing test**

Create `tests/test_i18n.py`:

```python
import json

import i18n


def test_english_loads():
    strings = i18n.translations("en")
    assert strings["nav.wall"] == "Wall"


def test_unknown_language_falls_back_to_english():
    assert i18n.translations("klingon") == i18n.translations("en")


def test_missing_key_returns_the_key_itself():
    # A missing string must never render as "None" or crash the page.
    assert i18n.lookup("en", "no.such.key") == "no.such.key"


def test_default_language_is_english(temp_db):
    assert i18n.current_language() == "en"


def test_language_setting_is_respected(temp_db):
    import database as db
    db.set_setting("language", "ru")
    assert i18n.current_language() == "ru"


def test_index_exposes_translations_to_javascript(client):
    html = client.get("/").data.decode("utf-8")
    assert "window.I18N" in html
    start = html.index("window.I18N = ") + len("window.I18N = ")
    end = html.index(";\n", start)
    assert json.loads(html[start:end])["nav.wall"] == "Wall"


def test_html_lang_attribute_follows_the_setting(client, temp_db):
    import database as db
    db.set_setting("language", "ru")
    assert b'<html lang="ru"' in client.get("/").data
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python -m pytest tests/test_i18n.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'i18n'`.

- [ ] **Step 3: Write the module**

Create `i18n.py`:

```python
"""UI translations.

One JSON file per language in lang/. The server picks a file based on the
`language` setting and hands it to Jinja (for markup) and to window.I18N
(for strings JavaScript sets at runtime) — one source of truth, two consumers.
"""
import json
from functools import lru_cache
from pathlib import Path

import database as db

LANG_DIR = Path(__file__).resolve().parent / "lang"
DEFAULT = "en"


@lru_cache(maxsize=8)
def translations(lang: str) -> dict:
    """Strings for `lang`, falling back to English for anything unknown."""
    path = LANG_DIR / f"{lang}.json"
    if not path.is_file():
        path = LANG_DIR / f"{DEFAULT}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def lookup(lang: str, key: str) -> str:
    """Translate one key. An unknown key renders as itself, so a missing
    string shows up as a visible key in the UI rather than 'None'."""
    return translations(lang).get(key, key)


def current_language() -> str:
    """The language chosen in the admin panel."""
    value = (db.get_settings().get("language") or "").strip().lower()
    return value if value in available() else DEFAULT


def available() -> list:
    """Language codes that actually have a file on disk."""
    return sorted(p.stem for p in LANG_DIR.glob("*.json"))
```

- [ ] **Step 4: Create the English file**

Create `lang/en.json` with the keys used by the tests. Later tasks grow this file:

```json
{
  "nav.wall": "Wall",
  "nav.posts": "Posts",
  "nav.video": "Video",
  "nav.photo": "Photo",
  "nav.about": "About"
}
```

- [ ] **Step 5: Wire it into Flask**

In `app.py`, add below `import database as db`:

```python
import i18n
```

Add after `db.init_db()`:

```python
@app.context_processor
def inject_i18n():
    """Make t() and the language available to every template."""
    lang = i18n.current_language()
    strings = i18n.translations(lang)
    return {
        "lang": lang,
        "t": lambda key: strings.get(key, key),
        "i18n_json": json.dumps(strings, ensure_ascii=False),
    }
```

- [ ] **Step 6: Expose the strings to JavaScript**

In `templates/index.html`, change line 2 to:

```html
<html lang="{{ lang }}">
```

Then immediately before the main `<script>` block that starts the app (search for `const tg =`), add:

```html
  <script>
    window.I18N = {{ i18n_json | safe }};
    window.T = function (key) { return window.I18N[key] || key; };
  </script>
```

`| safe` is correct here: `i18n_json` is `json.dumps` output of a file we ship, not user input.

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_i18n.py -v`
Expected: all 7 PASS.

- [ ] **Step 8: Commit**

```bash
git add i18n.py lang/ app.py templates/index.html tests/test_i18n.py
git commit -m "feat: add translation infrastructure

Server picks a language file from the `language` setting and passes it to
Jinja via t() and to JavaScript via window.I18N. Missing keys render as
the key itself so gaps are visible rather than crashing."
```

---

### Task 5: Extract the app's strings

Roughly 60 strings across `index.html`: 27 visible text nodes, 19 `aria-label`/`placeholder` attributes, and a handful set from JavaScript.

Rather than listing every string here, the test enforces completeness: it fails while any hardcoded English remains in a text node.

**Files:**
- Modify: `templates/index.html`, `lang/en.json`
- Modify: `tests/test_i18n.py`

**Interfaces:**
- Consumes: `t()` and `window.T()` from Task 4
- Produces: `lang/en.json` populated with every `app.*` and `nav.*` key. Task 7 translates exactly these keys.

- [ ] **Step 1: Write the completeness test**

Append to `tests/test_i18n.py`:

```python
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

# A text node holding two or more Latin letters, that is not already a
# Jinja expression. Deliberately crude — it only has to catch what a human
# would recognise as a forgotten UI string.
HARDCODED = re.compile(r">\s*([A-Za-z][A-Za-z ,.'!?/-]{2,})\s*<")

ALLOWED = {
    # Brand-neutral technical tokens and single symbols that are not UI copy.
    "DOCTYPE", "html", "head", "body", "script", "style",
}


def _hardcoded_strings(path: Path):
    html = path.read_text(encoding="utf-8")
    body = html[html.index("<body"):]
    found = []
    for match in HARDCODED.finditer(body):
        text = match.group(1).strip()
        if text in ALLOWED or "{{" in match.group(0):
            continue
        found.append(text)
    return sorted(set(found))


def test_index_has_no_hardcoded_ui_text():
    leftover = _hardcoded_strings(TEMPLATES / "index.html")
    assert leftover == [], f"Not yet translated: {leftover}"
```

- [ ] **Step 2: Run it to see the work list**

Run: `python -m pytest tests/test_i18n.py::test_index_has_no_hardcoded_ui_text -v`
Expected: FAIL, printing every remaining string. That list is the task.

- [ ] **Step 3: Replace markup strings with `t()` calls**

Work through the failure list. For each string, add a key to `lang/en.json` and swap the literal for a `t()` call. Use `area.thing` naming. Examples covering each shape you will hit:

```html
<!-- plain text node -->
<button class="bnav-item" data-view="wall">Wall</button>
<button class="bnav-item" data-view="wall">{{ t('nav.wall') }}</button>

<!-- attribute -->
<button aria-label="Search">
<button aria-label="{{ t('app.search') }}">

<!-- placeholder -->
<input placeholder="Search works…">
<input placeholder="{{ t('app.search_placeholder') }}">
```

Corresponding `lang/en.json` additions:

```json
{
  "app.search": "Search",
  "app.search_placeholder": "Search works…",
  "app.share": "Share",
  "app.forward": "Forward",
  "app.copy_link": "Copy link",
  "app.full_screen": "Full screen",
  "app.send_stars": "Send Stars",
  "app.unlock": "Unlock",
  "app.skip": "Skip",
  "app.back_to_posts": "Back to posts",
  "app.no_files": "No files yet · add media in /admin",
  "app.no_posts": "No posts yet · add them in /admin",
  "app.contact_cta": "Job / Advertising — get in touch",
  "app.send_message": "Send message",
  "app.message_placeholder": "Your message — a job, an ad, a question…",
  "app.message_sent": "Sent — thank you! The owner will get back to you.",
  "app.message_failed": "Could not send. Please try again.",
  "app.links": "Links",
  "app.made_by": "made by"
}
```

- [ ] **Step 4: Replace JavaScript strings with `T()`**

Search `templates/index.html` for `textContent =` and string literals inside `innerHTML`. Replace each:

```javascript
// index.html:1594 — was: starLabel.textContent = locked ? `Unlock · ${m.minStars}★` : 'Send Stars';
starLabel.textContent = locked
  ? `${T('app.unlock')} · ${m.minStars}★`
  : T('app.send_stars');

// the post reader's back button — was: '<i class="ti ti-arrow-left"></i> Back to posts'
back.innerHTML = '<i class="ti ti-arrow-left"></i> ' + T('app.back_to_posts');

// contact form result messages
statusEl.textContent = T('app.message_sent');
statusEl.textContent = T('app.message_failed');
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_i18n.py -v`
Expected: all PASS, including `test_index_has_no_hardcoded_ui_text`.

- [ ] **Step 6: Check it in the browser**

Run: `.\restart.ps1` then open http://localhost:5050
Expected: identical to before. Any key you mistyped shows as the raw key (e.g. `app.send_stars`) — that is the design, and makes mistakes obvious.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html lang/en.json tests/test_i18n.py
git commit -m "refactor: extract gallery UI strings to lang/en.json"
```

---

### Task 6: Extract the admin panel's strings

Same method, ~140 strings in `templates/admin.html`. The recipient administers their own copy, so the admin panel must translate too.

**Files:**
- Modify: `templates/admin.html`, `lang/en.json`, `app.py`
- Modify: `tests/test_i18n.py`

**Interfaces:**
- Consumes: `t()` / `window.T()` from Task 4
- Produces: `admin.*` keys in `lang/en.json`

- [ ] **Step 1: Extend the completeness test**

Append to `tests/test_i18n.py`:

```python
def test_admin_has_no_hardcoded_ui_text():
    leftover = _hardcoded_strings(TEMPLATES / "admin.html")
    assert leftover == [], f"Not yet translated: {leftover}"
```

- [ ] **Step 2: Run it to see the work list**

Run: `python -m pytest tests/test_i18n.py::test_admin_has_no_hardcoded_ui_text -v`
Expected: FAIL, listing ~140 strings.

- [ ] **Step 3: Expose the strings to the admin template**

The context processor from Task 4 already applies to every template. Add the same two lines near the top of `templates/admin.html`'s first `<script>` block:

```html
  <script>
    window.I18N = {{ i18n_json | safe }};
    window.T = function (key) { return window.I18N[key] || key; };
  </script>
```

And change `templates/admin.html` line 2 to `<html lang="{{ lang }}">`.

- [ ] **Step 4: Work through the list**

Same three shapes as Task 5. Tab labels (`admin.html:197-201`) are the natural starting point:

```html
<button class="tab-btn active" data-tab="media">{{ t('admin.tab_media') }}</button>
<button class="tab-btn" data-tab="posts">{{ t('admin.tab_posts') }}</button>
<button class="tab-btn" data-tab="stats">{{ t('admin.tab_stats') }} <span class="stat-badge" id="statsTabBadge" hidden></span></button>
<button class="tab-btn" data-tab="messages">{{ t('admin.tab_messages') }} <span class="tab-count" id="msgTabBadge" hidden></span></button>
<button class="tab-btn" data-tab="settings">{{ t('admin.tab_settings') }}</button>
```

```json
{
  "admin.tab_media": "Media",
  "admin.tab_posts": "Posts",
  "admin.tab_stats": "Stats",
  "admin.tab_messages": "Messages",
  "admin.tab_settings": "Settings"
}
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 6: Check the panel in the browser**

Run: `.\restart.ps1`, open http://localhost:5050/admin, log in, click through all five tabs.
Expected: every label reads normally, no raw keys visible.

- [ ] **Step 7: Commit**

```bash
git add templates/admin.html lang/en.json tests/test_i18n.py
git commit -m "refactor: extract admin panel strings to lang/en.json"
```

---

### Task 7: Russian translation and the language switch

**Files:**
- Create: `lang/ru.json`
- Modify: `templates/admin.html` (language dropdown), `app.py` (accept the setting)
- Modify: `tests/test_i18n.py`

**Interfaces:**
- Consumes: every key in `lang/en.json` from Tasks 5-6
- Produces: `language` setting accepted by `POST /api/admin/settings`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_i18n.py`:

```python
def test_russian_covers_every_english_key():
    en, ru = i18n.translations("en"), i18n.translations("ru")
    missing = sorted(set(en) - set(ru))
    assert missing == [], f"Untranslated keys: {missing}"


def test_russian_has_no_extra_keys():
    en, ru = i18n.translations("en"), i18n.translations("ru")
    extra = sorted(set(ru) - set(en))
    assert extra == [], f"Keys not in en.json: {extra}"


def test_russian_is_actually_russian():
    ru = i18n.translations("ru")
    cyrillic = [v for v in ru.values() if any("\u0400" <= c <= "\u04ff" for c in v)]
    assert len(cyrillic) > len(ru) * 0.8


def test_admin_can_set_the_language(admin_client):
    resp = admin_client.post("/api/admin/settings", data={"language": "ru"})
    assert resp.status_code == 200
    import database as db
    assert db.get_settings()["language"] == "ru"


def test_switching_language_changes_the_page(client, admin_client):
    import database as db
    before = client.get("/").data
    db.set_setting("language", "ru")
    i18n.translations.cache_clear()
    assert client.get("/").data != before
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_i18n.py -v`
Expected: FAIL — `lang/ru.json` does not exist.

- [ ] **Step 3: Write the Russian file**

Create `lang/ru.json` with every key from `en.json`. Starting set:

```json
{
  "nav.wall": "Стена",
  "nav.posts": "Посты",
  "nav.video": "Видео",
  "nav.photo": "Фото",
  "nav.about": "О себе",
  "app.search": "Поиск",
  "app.search_placeholder": "Поиск работ…",
  "app.share": "Поделиться",
  "app.forward": "Переслать",
  "app.copy_link": "Скопировать ссылку",
  "app.full_screen": "Полный экран",
  "app.send_stars": "Отправить звёзды",
  "app.unlock": "Открыть",
  "app.skip": "Пропустить",
  "app.back_to_posts": "Назад к постам",
  "app.no_files": "Пока нет файлов · добавьте в /admin",
  "app.no_posts": "Пока нет постов · добавьте их в /admin",
  "app.contact_cta": "Работа / Реклама — связаться",
  "app.send_message": "Отправить сообщение",
  "app.message_placeholder": "Ваше сообщение — работа, реклама, вопрос…",
  "app.message_sent": "Отправлено — спасибо! Владелец свяжется с вами.",
  "app.message_failed": "Не удалось отправить. Попробуйте ещё раз.",
  "app.links": "Ссылки",
  "app.made_by": "сделал",
  "admin.tab_media": "Медиа",
  "admin.tab_posts": "Посты",
  "admin.tab_stats": "Статистика",
  "admin.tab_messages": "Сообщения",
  "admin.tab_settings": "Настройки"
}
```

Fill in the rest by running the coverage test — it names every missing key.

- [ ] **Step 4: Allow the setting through the API**

In `app.py`, in `admin_set_settings`, add `"language"` to the plain-text field tuple:

```python
    for key in ("logo_text", "about_text", "bot_username", "miniapp_name",
                "contact_chat_id", "language"):
```

Because `i18n.translations` is `lru_cache`d, clear it whenever settings change. Add at the end of `admin_set_settings`, before the return:

```python
    i18n.translations.cache_clear()
```

- [ ] **Step 5: Add the dropdown to the admin Settings tab**

Inside the `settings` tab panel in `templates/admin.html`:

```html
  <label>{{ t('admin.language') }}
    <select name="language" id="languageSelect">
      <option value="en">English</option>
      <option value="ru">Русский</option>
    </select>
  </label>
```

Add `"admin.language": "Language"` to `en.json` and `"admin.language": "Язык"` to `ru.json`. Make sure the existing settings-save JavaScript includes this field, and that loading the settings preselects the current value.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 7: Check both languages in the browser**

Run: `.\restart.ps1`, open `/admin`, set Language to Русский, save, then reload the gallery.
Expected: nav, buttons, and admin tabs are in Russian. Switch back to English and confirm it returns.

- [ ] **Step 8: Commit**

```bash
git add lang/ru.json templates/admin.html app.py tests/test_i18n.py
git commit -m "feat: add Russian translation and admin language switch"
```

---

### Task 8: Theme settings

Colours, fonts, and corner radius stored as settings and injected as a `:root` override. The templates already use these custom properties everywhere, so overriding them restyles the whole app with no other change.

**Files:**
- Create: `theme.py`
- Create: `tests/test_theme.py`
- Modify: `app.py`, `templates/index.html`

**Interfaces:**
- Consumes: `db.get_settings()`
- Produces:
  - `theme.THEME_KEYS: tuple[str, ...]` — the settable keys, used by the admin whitelist in Task 9
  - `theme.css_overrides(settings: dict) -> str` — a `:root { … }` block, empty string when nothing is set
  - Template context variable `theme_css`

- [ ] **Step 1: Write the failing test**

Create `tests/test_theme.py`:

```python
import theme


def test_no_settings_produces_no_css():
    assert theme.css_overrides({}) == ""


def test_accent_colour_becomes_a_variable():
    css = theme.css_overrides({"accent_color": "#ff0066"})
    assert "--green: #ff0066" in css
    assert css.startswith(":root")


def test_radius_is_emitted_with_units():
    assert "--cell-radius: 6px" in theme.css_overrides({"cell_radius": "6"})


def test_invalid_colour_is_ignored():
    # Anything not a plain hex colour must not reach the stylesheet.
    css = theme.css_overrides({"accent_color": "red; } body { display:none"})
    assert "display:none" not in css
    assert css == ""


def test_radius_is_clamped_to_the_slider_range():
    assert "--cell-radius: 12px" in theme.css_overrides({"cell_radius": "999"})
    assert "--cell-radius: 0px" in theme.css_overrides({"cell_radius": "-5"})


def test_non_numeric_radius_is_ignored():
    assert theme.css_overrides({"cell_radius": "abc"}) == ""


def test_uploaded_font_overrides_the_family(temp_db):
    css = theme.css_overrides({"font_display": "MyFont.woff2"})
    assert "@font-face" in css
    assert "/static/fonts/MyFont.woff2" in css


def test_theme_reaches_the_page(client):
    import database as db
    db.set_setting("accent_color", "#ff0066")
    assert b"--green: #ff0066" in client.get("/").data
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_theme.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'theme'`.

- [ ] **Step 3: Write the module**

Create `theme.py`:

```python
"""Per-copy appearance, stored in settings and injected as a :root override.

The templates already reference every one of these as a CSS custom property,
so overriding them restyles the entire app without touching a stylesheet.

Everything here is written into a <style> tag, so each value is validated
rather than trusted — a setting containing "} body { display:none" would
otherwise rewrite the page.
"""
import re

HEX = re.compile(r"^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$")
FONT_FILE = re.compile(r"^[A-Za-z0-9_.-]+\.(?:woff2|woff|otf|ttf)$")

# setting key -> CSS custom property
COLOR_KEYS = {
    "accent_color": "--green",
    "bg_page": "--bg-page",
    "bg_base": "--bg-base",
    "bg_raised": "--bg-raised",
}

RADIUS_MIN, RADIUS_MAX = 0, 12

THEME_KEYS = tuple(COLOR_KEYS) + ("cell_radius", "font_display", "font_mono")


def _colors(settings: dict) -> list:
    out = []
    for key, prop in COLOR_KEYS.items():
        value = (settings.get(key) or "").strip()
        if value and HEX.match(value):
            out.append(f"  {prop}: {value};")
    return out


def _radius(settings: dict) -> list:
    raw = (settings.get("cell_radius") or "").strip()
    if not raw:
        return []
    try:
        value = int(float(raw))
    except ValueError:
        return []
    value = max(RADIUS_MIN, min(RADIUS_MAX, value))
    return [f"  --cell-radius: {value}px;"]


def _fonts(settings: dict) -> tuple:
    """Uploaded fonts re-declare the same families the templates already use,
    so nothing else needs to change. Later @font-face wins."""
    faces, variables = [], []
    for key, family, var in (
        ("font_display", "AppDisplay", "--font-display"),
        ("font_mono", "AppMono", "--font-mono"),
    ):
        filename = (settings.get(key) or "").strip()
        if not filename or not FONT_FILE.match(filename):
            continue
        faces.append(
            "@font-face {\n"
            f"  font-family: '{family}';\n"
            f"  src: url('/static/fonts/{filename}');\n"
            "  font-weight: 400 700;\n"
            "  font-display: swap;\n"
            "}"
        )
        variables.append(f"  {var}: '{family}', system-ui, sans-serif;")
    return faces, variables


def css_overrides(settings: dict) -> str:
    """A stylesheet fragment for the current settings, or '' if none apply."""
    faces, font_vars = _fonts(settings)
    declarations = _colors(settings) + _radius(settings) + font_vars
    if not declarations and not faces:
        return ""
    blocks = list(faces)
    if declarations:
        blocks.append(":root {\n" + "\n".join(declarations) + "\n}")
    return "\n".join(blocks)
```

- [ ] **Step 4: Inject it**

In `app.py`, add `import theme` beside the other imports, and extend the context processor from Task 4:

```python
@app.context_processor
def inject_i18n():
    """Make t(), the language, and the theme available to every template."""
    lang = i18n.current_language()
    strings = i18n.translations(lang)
    return {
        "lang": lang,
        "t": lambda key: strings.get(key, key),
        "i18n_json": json.dumps(strings, ensure_ascii=False),
        "theme_css": theme.css_overrides(db.get_settings()),
    }
```

- [ ] **Step 5: Render it last**

In `templates/index.html`, immediately before `</head>`, after the main `<style>` block so it wins:

```html
  <style id="themeOverrides">{{ theme_css | safe }}</style>
```

`| safe` is sound only because `theme.py` validates every value against a strict pattern — see the tests in Step 1.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_theme.py -v`
Expected: all 8 PASS.

- [ ] **Step 7: Commit**

```bash
git add theme.py app.py templates/index.html tests/test_theme.py
git commit -m "feat: add theme overrides driven by settings

Colours, corner radius, and uploaded fonts render as a :root override.
Every value is validated against a strict pattern before it reaches the
style tag, since these are injected as raw CSS."
```

---

### Task 9: Appearance tab in the admin panel

**Files:**
- Modify: `templates/admin.html`, `app.py`, `lang/en.json`, `lang/ru.json`
- Modify: `tests/test_theme.py`

**Interfaces:**
- Consumes: `theme.THEME_KEYS` from Task 8
- Produces: `POST /api/admin/settings` accepts every theme key plus `font_display_file` / `font_mono_file` uploads

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_theme.py`:

```python
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
    assert db.get_settings()["font_display"].endswith(".woff2")


def test_font_upload_rejects_non_font_files(admin_client):
    resp = admin_client.post("/api/admin/settings", data={
        "font_display_file": (io.BytesIO(b"<script>"), "evil.html"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_theme_settings_require_admin(client):
    assert client.post("/api/admin/settings", data={"accent_color": "#fff"}).status_code == 401
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_theme.py -v`
Expected: the four new tests FAIL.

- [ ] **Step 3: Accept the settings server-side**

In `app.py`, add the font extension whitelist near the other constants:

```python
FONT_EXT = {"woff2", "woff", "otf", "ttf"}
FONTS_DIR = BASE_DIR / "static" / "fonts"
```

In `admin_set_settings`, extend the plain-text loop and add font handling before the return:

```python
    for key in ("logo_text", "about_text", "bot_username", "miniapp_name",
                "contact_chat_id", "language") + theme.THEME_KEYS:
        if key in request.form:
            db.set_setting(key, request.form.get(key, "").strip())

    # Font uploads — separate field names so the stored value stays a filename.
    for field, setting in (("font_display_file", "font_display"),
                           ("font_mono_file", "font_mono")):
        upload = request.files.get(field)
        if not upload or not upload.filename:
            continue
        extension = ext_of(upload.filename)
        if extension not in FONT_EXT:
            return jsonify({"error": f"Unsupported font type: .{extension}"}), 400
        FONTS_DIR.mkdir(parents=True, exist_ok=True)
        stem = secure_filename(upload.filename.rsplit(".", 1)[0]) or "font"
        stored = f"{stem[:40]}_{secrets.token_hex(4)}.{extension}"
        upload.save(FONTS_DIR / stored)
        db.set_setting(setting, stored)
```

Note `theme.THEME_KEYS` includes `font_display`/`font_mono`, so a form field of that exact name could set the filename directly — harmless, since `theme.py` validates the pattern before use.

- [ ] **Step 4: Build the tab**

Add a button to the tab nav in `templates/admin.html`, after Settings:

```html
    <button class="tab-btn" data-tab="appearance">{{ t('admin.tab_appearance') }}</button>
```

And a panel alongside the others:

```html
  <section class="tab-panel" data-tab="appearance">
    <h2>{{ t('admin.appearance_heading') }}</h2>
    <form id="appearanceForm" enctype="multipart/form-data">
      <label>{{ t('admin.accent_color') }}
        <input type="color" name="accent_color" id="accentColor" />
      </label>
      <label>{{ t('admin.bg_page') }}
        <input type="color" name="bg_page" id="bgPage" />
      </label>
      <label>{{ t('admin.bg_base') }}
        <input type="color" name="bg_base" id="bgBase" />
      </label>
      <label>{{ t('admin.bg_raised') }}
        <input type="color" name="bg_raised" id="bgRaised" />
      </label>
      <label>{{ t('admin.cell_radius') }}
        <input type="range" name="cell_radius" id="cellRadius" min="0" max="12" step="1" />
        <output id="cellRadiusOut"></output>
      </label>
      <label>{{ t('admin.font_display') }}
        <input type="file" name="font_display_file" accept=".woff2,.woff,.otf,.ttf" />
      </label>
      <label>{{ t('admin.font_mono') }}
        <input type="file" name="font_mono_file" accept=".woff2,.woff,.otf,.ttf" />
      </label>
      <button type="submit">{{ t('admin.save') }}</button>
    </form>
  </section>
```

Wire it up in the admin JavaScript, following the pattern the Settings form already uses:

```javascript
  document.getElementById('appearanceForm').addEventListener('submit', async e => {
    e.preventDefault();
    const res = await fetch('/api/admin/settings', {
      method: 'POST',
      body: new FormData(e.target),
    });
    const data = await res.json();
    alert(res.ok ? T('admin.saved') : (data.error || T('admin.save_failed')));
  });

  document.getElementById('cellRadius').addEventListener('input', e => {
    document.getElementById('cellRadiusOut').textContent = e.target.value + 'px';
  });
```

When the Appearance tab is opened, load current values from `GET /api/admin/settings` and populate each input — mirror how the Settings tab does it.

- [ ] **Step 5: Add the strings**

To `lang/en.json`:

```json
{
  "admin.tab_appearance": "Appearance",
  "admin.appearance_heading": "Appearance",
  "admin.accent_color": "Accent colour",
  "admin.bg_page": "Page background",
  "admin.bg_base": "Base background",
  "admin.bg_raised": "Raised background",
  "admin.cell_radius": "Corner radius",
  "admin.font_display": "Display font",
  "admin.font_mono": "Interface font",
  "admin.save": "Save",
  "admin.saved": "Saved.",
  "admin.save_failed": "Could not save."
}
```

To `lang/ru.json`:

```json
{
  "admin.tab_appearance": "Оформление",
  "admin.appearance_heading": "Оформление",
  "admin.accent_color": "Акцентный цвет",
  "admin.bg_page": "Фон страницы",
  "admin.bg_base": "Основной фон",
  "admin.bg_raised": "Фон блоков",
  "admin.cell_radius": "Скругление углов",
  "admin.font_display": "Заголовочный шрифт",
  "admin.font_mono": "Шрифт интерфейса",
  "admin.save": "Сохранить",
  "admin.saved": "Сохранено.",
  "admin.save_failed": "Не удалось сохранить."
}
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS, including the Russian coverage test from Task 7.

- [ ] **Step 7: Try it end to end**

Run: `.\restart.ps1`, open `/admin` → Appearance, set the accent to `#ff0066` and radius to `6`, save, reload the gallery.
Expected: nav and buttons pick up the new accent; cells have rounded corners. Upload one of the `.woff2` files from `static/fonts/` as the display font and confirm the headings change.

- [ ] **Step 8: Commit**

```bash
git add templates/admin.html app.py lang/ tests/test_theme.py
git commit -m "feat: add Appearance tab for colours, radius, and font uploads"
```

---

### Task 10: De-brand

"Geroinzo" appears 35 times across 8 files in three distinct roles, each needing different treatment.

**Files:**
- Modify: `app.py`, `database.py`, `templates/index.html`, `templates/admin.html`, `README.md`, `seed_demo.py`, `share.bat`, `restart.ps1`
- Create: `tests/test_branding.py`

**Interfaces:**
- Consumes: the existing `logo_text` setting
- Produces: nothing new — removes literals

- [ ] **Step 1: Write the failing test**

Create `tests/test_branding.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = ["app.py", "database.py", "templates/index.html", "templates/admin.html"]


def test_no_brand_name_in_code():
    offenders = {}
    for name in CODE:
        text = (ROOT / name).read_text(encoding="utf-8")
        count = text.lower().count("geroinzo")
        if count:
            offenders[name] = count
    assert offenders == {}, f"Hardcoded brand name remains: {offenders}"


def test_invoice_title_uses_the_logo_setting(temp_db):
    import database as db
    db.set_setting("logo_text", "Studio X")
    assert db.get_settings()["logo_text"] == "Studio X"


def test_page_title_follows_the_logo_setting(client):
    import database as db
    db.set_setting("logo_text", "Studio X")
    assert b"Studio X" in client.get("/").data
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_branding.py -v`
Expected: FAIL, listing the per-file counts.

- [ ] **Step 3: Replace the visible brand name**

In `app.py`, both invoice builders fall back to the literal. Replace in `api_invoice`:

```python
    brand = db.get_settings().get("logo_text") or "Gallery"
    title = ("Unlock: " if purpose == "unlock" else "Support: ") + (
        item["title"] or brand
    )
```

And in `api_post_invoice`:

```python
    brand = db.get_settings().get("logo_text") or "Gallery"
    title = ("Support: " + (post["title"] or brand))[:32]
```

In `app.py`'s `api_settings`, change the default:

```python
        "logoText": settings.get("logo_text", ""),
```

- [ ] **Step 4: Make the page title dynamic**

In `templates/index.html` line 6:

```html
  <title>{{ brand }}</title>
```

In `templates/admin.html` line 6:

```html
  <title>{{ brand }} — {{ t('admin.title') }}</title>
```

Add `brand` to the context processor in `app.py`:

```python
        "brand": db.get_settings().get("logo_text") or "Gallery",
```

Add `"admin.title": "Admin"` to `en.json` and `"admin.title": "Админка"` to `ru.json`.

- [ ] **Step 5: Rename the font families**

Any remaining `GeroinzoDisplay` / `GeroinzoMono` / `GeroinzoStamp` comments in `templates/index.html` become `AppDisplay` / `AppMono` / `AppStamp`. The `@font-face` blocks were already renamed in Task 3; this catches the trailing comments on the `--font-*` lines.

- [ ] **Step 6: Update the docs and scripts**

Replace brand references in `README.md`, `seed_demo.py`, `share.bat`, and `restart.ps1` with generic wording ("the gallery", "the app"). Leave the directory name `geroinzo-gallery` alone — renaming it breaks the paths hardcoded in `restart.ps1` and `share.bat` and gains nothing, since the recipient only sees what renders in the app.

Also update `database.py`'s module docstring (line 2) and `app.py`'s (line 2).

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: remove hardcoded brand name

Visible name now reads the logo_text setting; CSS families renamed to
AppDisplay/AppMono/AppStamp; docs and scripts made generic. Directory
name kept — restart.ps1 and share.bat hardcode the path."
```

---

### Task 11: Layout fixes

**Files:**
- Modify: `app.py:302`, `database.py`, `templates/index.html`
- Create: `tests/test_posts.py`

**Interfaces:**
- Consumes: nothing
- Produces: `media.width` / `media.height` columns; `/api/posts/<id>` returns a single `media` list

- [ ] **Step 1: Write the failing tests**

Create `tests/test_posts.py`:

```python
import io


def _make_post_with_media(admin_client, count):
    admin_client.post("/api/admin/posts", data={"title": "P", "body": "b"})
    post_id = 1
    for i in range(count):
        admin_client.post(f"/api/admin/posts/{post_id}", data={
            "media": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 64), f"img{i}.png"),
        }, content_type="multipart/form-data")
    return post_id


def test_post_returns_more_than_fifteen_images(admin_client, client):
    post_id = _make_post_with_media(admin_client, 20)
    data = client.get(f"/api/posts/{post_id}").get_json()
    assert len(data["media"]) == 20, "images past 15 were silently dropped"


def test_post_media_is_one_list(admin_client, client):
    post_id = _make_post_with_media(admin_client, 3)
    data = client.get(f"/api/posts/{post_id}").get_json()
    assert "media" in data
    assert "images" not in data and "videos" not in data


def test_media_rows_carry_dimensions(temp_db):
    import database as db
    media_id = db.add_media(filename="x.png", m_type="photo", title="", description="",
                            date_label="", year="", size="medium", is_locked=False,
                            min_stars=1, width=800, height=600)
    row = db.get_media(media_id)
    assert row["width"] == 800 and row["height"] == 600
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_posts.py -v`
Expected: all three FAIL.

- [ ] **Step 3: Add the dimension columns**

In `database.py`, alongside the existing media migrations (near line 103):

```python
    if "width" not in cols:
        cur.execute("ALTER TABLE media ADD COLUMN width INTEGER NOT NULL DEFAULT 0")
    if "height" not in cols:
        cur.execute("ALTER TABLE media ADD COLUMN height INTEGER NOT NULL DEFAULT 0")
```

Add `width=0, height=0` parameters to `add_media()` and include them in its INSERT.

- [ ] **Step 4: Remove the cap and the pointless split**

In `app.py`, replace the body of `api_post_one`'s media handling:

```python
    media = db.list_post_media(post_id)
    return jsonify({
        "id": post["id"],
        "title": post["title"],
        "body": post["body"],
        "categories": _post_categories(post),
        "hashtags": _post_hashtags(post),
        "media": [media_public(m, uid) for m in media],
        "likes": db.post_like_total(post_id),
        "liked": db.user_liked_post(post_id, uid),
        "minStars": post["min_stars"],
    })
```

The `[:15]` cap silently discarded images past the fifteenth, and the client re-merged the two lists anyway (`index.html:2057`).

Add the dimensions to `media_public`:

```python
        "width": item["width"],
        "height": item["height"],
```

- [ ] **Step 5: Update the client**

In `templates/index.html`, in `openPost`, replace the merge with the single list:

```javascript
    const postMedia = post.media || [];
```

- [ ] **Step 6: Size cells before the image loads**

In `buildCell`, set an aspect ratio when dimensions are known, so cells never start at the provisional 160px and snap:

```javascript
    if (m.width && m.height) {
      cell.style.aspectRatio = m.width + ' / ' + m.height;
    }
```

And give placeholders a fixed span in `relayoutCell`, replacing the self-referential branch:

```javascript
    } else {
      h = 140;   // placeholders have no intrinsic size; do not measure the cell,
                 // whose height the grid itself is setting
    }
```

- [ ] **Step 7: Remove the dead CSS**

Delete from `templates/index.html`: `.post-reader-gallery` and `.post-reader-gallery .cell` (~line 1100), `.morph-gallery`, `.morph-item`, `.morph-item img/video`, `.morph-item.active` and its media query (~lines 1126-1137), and `.cell-ghost` (~line 389). Also remove the `#expGhost` "WHO NEEDS" markup and the `.expanded-card.as-modal.has-media #expGhost` rule.

Confirm nothing references them:

```bash
git grep -n "morph-\|post-reader-gallery\|cell-ghost\|expGhost" templates/
```

Expected: no output.

- [ ] **Step 8: Run the tests**

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 9: Check in the browser**

Run: `.\restart.ps1`, open the gallery, hard-reload (Ctrl+Shift+R).
Expected: the wall no longer jumps as images load. Open a post and confirm its gallery still lays out correctly.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "fix: remove post image cap, size cells before load, drop dead CSS

/api/posts/<id> truncated images to 15 with no warning and split them
from videos, which the client immediately re-merged. Media rows now carry
width/height so cells get an aspect-ratio up front instead of starting at
a provisional 160px span and snapping once the image arrives."
```

---

### Task 12: Stars modes and the donation/unlock split

**Files:**
- Modify: `database.py`, `app.py`, `templates/index.html`, `templates/admin.html`, `lang/*.json`
- Create: `tests/test_stars.py`

**Interfaces:**
- Consumes: `theme.THEME_KEYS` pattern for the settings whitelist
- Produces: `stars_mode` setting (`off` / `all` / `checked`); `posts.show_stars` and `media.show_stars` columns; `showStars` boolean on the media and post APIs

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stars.py`:

```python
import pytest


@pytest.fixture
def locked_item(temp_db):
    import database as db
    return db.add_media(filename="x.png", m_type="photo", title="Locked",
                        description="", date_label="", year="", size="medium",
                        is_locked=True, min_stars=10)


def test_default_mode_is_all(temp_db):
    import database as db
    assert db.get_settings().get("stars_mode", "all") == "all"


def test_mode_off_hides_the_donation_button(client, temp_db):
    import database as db
    media_id = db.add_media(filename="x.png", m_type="photo", title="", description="",
                            date_label="", year="", size="medium", is_locked=False,
                            min_stars=1)
    db.set_setting("stars_mode", "off")
    item = client.get(f"/api/media/{media_id}").get_json()
    assert item["showStars"] is False


def test_mode_off_still_allows_unlocking_locked_content(client, temp_db, locked_item):
    """Donation and Unlock are the same button in the UI. If `off` hid it for
    locked items too, that content would become permanently unviewable."""
    import database as db
    db.set_setting("stars_mode", "off")
    item = client.get(f"/api/media/{locked_item}").get_json()
    assert item["isLocked"] is True
    assert item["canUnlock"] is True


def test_mode_checked_respects_the_per_item_flag(client, temp_db):
    import database as db
    on = db.add_media(filename="a.png", m_type="photo", title="", description="",
                      date_label="", year="", size="medium", is_locked=False, min_stars=1)
    off = db.add_media(filename="b.png", m_type="photo", title="", description="",
                       date_label="", year="", size="medium", is_locked=False, min_stars=1)
    db.update_media(on, {"show_stars": "1"})
    db.set_setting("stars_mode", "checked")
    assert client.get(f"/api/media/{on}").get_json()["showStars"] is True
    assert client.get(f"/api/media/{off}").get_json()["showStars"] is False


def test_admin_can_set_the_mode(admin_client):
    resp = admin_client.post("/api/admin/settings", data={"stars_mode": "checked"})
    assert resp.status_code == 200
    import database as db
    assert db.get_settings()["stars_mode"] == "checked"


def test_invalid_mode_is_rejected(admin_client):
    admin_client.post("/api/admin/settings", data={"stars_mode": "banana"})
    import database as db
    assert db.get_settings().get("stars_mode") in (None, "", "all")
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_stars.py -v`
Expected: all FAIL.

- [ ] **Step 3: Migrate both tables**

In `database.py`, with the existing media migrations:

```python
    if "show_stars" not in cols:
        cur.execute("ALTER TABLE media ADD COLUMN show_stars INTEGER NOT NULL DEFAULT 0")
```

And with the posts migrations (the `pcols` list near line 119), add:

```python
        ("show_stars", "ALTER TABLE posts ADD COLUMN show_stars INTEGER NOT NULL DEFAULT 0"),
```

- [ ] **Step 4: Compute visibility server-side**

In `app.py`, above `media_public`:

```python
STARS_MODES = ("off", "all", "checked")


def stars_visible(item) -> bool:
    """Whether the voluntary donation button shows for this item.

    Deliberately does NOT govern unlocking. The two share one button in the
    UI, so gating unlocks on this setting would make locked content
    permanently unviewable once the owner turned donations off.
    """
    mode = db.get_settings().get("stars_mode", "all")
    if mode == "off":
        return False
    if mode == "checked":
        return bool(item["show_stars"])
    return True
```

Add both flags to `media_public`'s returned dict:

```python
        "showStars": stars_visible(item),
        "canUnlock": bool(item["is_locked"]),
```

Do the same in `api_post_one`, using the post row.

- [ ] **Step 5: Validate the setting**

In `app.py`'s `admin_set_settings`, before the plain-text loop:

```python
    if "stars_mode" in request.form:
        mode = request.form.get("stars_mode", "").strip()
        if mode in STARS_MODES:
            db.set_setting("stars_mode", mode)
```

Do **not** add `stars_mode` to the plain-text key tuple — it must go through this check.

- [ ] **Step 6: Honour the flags in the UI**

In `templates/index.html`, in the function that opens an item (search for `starLabel.textContent`), show the button when either the donation is allowed or the item is locked:

```javascript
    const showButton = m.showStars || (m.canUnlock && !m.unlocked);
    starBtn.style.display = showButton ? '' : 'none';
    starLabel.textContent = (m.canUnlock && !m.unlocked)
      ? `${T('app.unlock')} · ${m.minStars}★`
      : T('app.send_stars');
```

In `openPost`, only append the Stars button when `post.showStars` is true.

- [ ] **Step 7: Add the admin controls**

In the Appearance tab from Task 9:

```html
      <label>{{ t('admin.stars_mode') }}
        <select name="stars_mode" id="starsMode">
          <option value="all">{{ t('admin.stars_all') }}</option>
          <option value="checked">{{ t('admin.stars_checked') }}</option>
          <option value="off">{{ t('admin.stars_off') }}</option>
        </select>
      </label>
```

Add a checkbox to both the media editor and the post editor:

```html
      <label><input type="checkbox" name="show_stars" value="1" /> {{ t('admin.show_stars_item') }}</label>
```

Strings for `en.json`:

```json
{
  "admin.stars_mode": "Send Stars button",
  "admin.stars_all": "Show everywhere",
  "admin.stars_checked": "Only where ticked",
  "admin.stars_off": "Hide (unlocking still works)",
  "admin.show_stars_item": "Show Send Stars on this item"
}
```

And `ru.json`:

```json
{
  "admin.stars_mode": "Кнопка «Звёзды»",
  "admin.stars_all": "Показывать везде",
  "admin.stars_checked": "Только где отмечено",
  "admin.stars_off": "Скрыть (открытие платного работает)",
  "admin.show_stars_item": "Показывать «Звёзды» на этом элементе"
}
```

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: everything PASSES.

- [ ] **Step 9: Verify the dangerous case by hand**

Run: `.\restart.ps1`. In admin, lock a wall image with a Stars price, then set the Stars button to "Hide". Open that image in the gallery.
Expected: the **Unlock** button is still there. This is the whole point of the split — confirm it directly rather than trusting the test.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: add Stars button modes with donation/unlock split

Three modes (off/all/checked) plus a per-item flag on media and posts.
Donation visibility obeys the setting; unlocking never does, because both
share one button and hiding it for locked items would make that content
permanently unviewable."
```

---

## Done criteria

- `python -m pytest tests/ -v` passes.
- `git grep -in geroinzo -- app.py database.py templates/` returns nothing.
- The rendered page loads no external host except `telegram.org`.
- Setting `language: ru` renders app and admin in Russian.
- Setting an accent colour and radius in admin visibly changes the gallery.
- A locked item still shows Unlock with `stars_mode: off`.

At that point the shared base is done and the folder can be copied. Step 6 of the spec — downloads and snippets — is owner-only and gets its own plan.
