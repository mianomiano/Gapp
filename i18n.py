"""UI translations.

One JSON file per language in lang/. The server picks a file based on the
`language` setting and hands it to Jinja (for markup, via t()) and to
window.I18N (for strings JavaScript sets at runtime) — one source of truth,
two consumers.

Adding a language is one new file; nothing here needs changing. Both the file
list and the file contents are cached, so a new or edited language file needs
an app restart to appear — the same restart any template edit already needs.
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
    string shows as a visible key in the UI rather than 'None'."""
    return translations(lang).get(key, key)


@lru_cache(maxsize=1)
def available() -> tuple:
    """Language codes that actually have a file on disk."""
    return tuple(sorted(p.stem for p in LANG_DIR.glob("*.json")))


def current_language() -> str:
    """The language chosen in the admin panel."""
    value = (db.get_settings().get("language") or "").strip().lower()
    return value if value in available() else DEFAULT
