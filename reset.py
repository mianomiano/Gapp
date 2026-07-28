"""
Wipe the gallery back to empty — clears all media, links, and settings.

Use this to hand the project over as a clean, empty gallery, or to clear demo
content. (A fresh `git clone` is already empty; this is just a convenience.)
Safe to run while the server is up — it clears the data, not the database file.

    python reset.py
"""

from pathlib import Path

import database as db

MEDIA_DIR = Path(__file__).resolve().parent / "static" / "media"

db.init_db()
db.wipe_all()

removed = 0
for f in MEDIA_DIR.glob("*"):
    if f.name == ".gitkeep":
        continue
    try:
        f.unlink()
        removed += 1
    except OSError:
        pass  # in use (e.g. being served) — harmless, retry later

print(f"Cleared all content. Removed {removed} media file(s). Gallery is empty.")
