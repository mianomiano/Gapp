"""
Fill the gallery with on-brand DEMO content — for showing how it looks.

This is OPTIONAL and for the giver's preview / public reveal only. A freshly
cloned repo starts EMPTY (the database and uploaded media are gitignored), so
the person you gift it to never sees this unless they run it themselves.

    python seed_demo.py            # add demo content (refuses if items exist)
    python seed_demo.py --reset    # wipe everything first, then add demo content

To go back to empty:  python reset.py
"""

import sys
from pathlib import Path

import database as db

MEDIA_DIR = Path(__file__).resolve().parent / "static" / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# Palette pulled from the gallery's design tokens.
BG = "#111114"
TEXT = "#E8E4DC"
GREEN = "#39E8A0"
RED = "#FF2A2A"

# Each demo item: ghost text, accent, and metadata that shows off a feature.
DEMO = [
    dict(slug="domo23", ghost="DOMO", accent=GREEN, type="video", size="tall",
         title="DOMO23", year="2023", date="18 · 10 · 24",
         desc="TYPOGRAPHY STUDY\nMADE UNDER THE INFLUENCE",
         is_locked=False, min_stars=1),
    dict(slug="golf_wang", ghost="FUCK\nTHAT", accent=None, type="photo", size="short",
         title="GOLF WANG", year="2024", date="02 · 03 · 24",
         desc="POSTMODERN PRINT STUDY", is_locked=False, min_stars=1),
    dict(slug="type01", ghost="GRUNGE", accent=RED, type="photo", size="short",
         title="TYPE 01", year="2024", date="11 · 04 · 24",
         desc="GRUNGE LETTERFORM\nEXPERIMENT IN DISTORTION",
         is_locked=False, min_stars=1),
    dict(slug="made_by", ghost="MADE\nBY", accent=GREEN, type="video", size="medium",
         title="MADE BY", year="2024", date="01 · 11 · 24",
         desc="CRT TELEVISION LOOP", is_locked=False, min_stars=1),
    dict(slug="sober_view", ghost="WHO\nNEEDS", accent=GREEN, type="photo", size="medium",
         title="WHO NEEDS A SOBER VIEW?", year="2024", date="11 · 06 · 26",
         desc="A TRIP BEYOND SIGHT & MIND\nLOCKED — UNLOCK WITH STARS",
         is_locked=True, min_stars=25),
    dict(slug="grain", ghost="GRAIN", accent=None, type="photo", size="tall",
         title="GRAIN STUDY", year="2023", date="29 · 09 · 23",
         desc="ANALOG NOISE\nSCANNED & DESTROYED", is_locked=False, min_stars=1),
]


def make_svg(ghost, accent):
    """A dark, scanlined placeholder with big low-opacity ghost type."""
    lines = ghost.split("\n")
    line_height = 130
    start_y = 300 - (len(lines) - 1) * line_height / 2
    spans = "".join(
        f'<tspan x="300" y="{start_y + i * line_height:.0f}">{ln}</tspan>'
        for i, ln in enumerate(lines)
    )
    accent_mark = (
        f'<rect x="40" y="40" width="60" height="8" fill="{accent}" opacity="0.9"/>'
        if accent else ""
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600">
  <defs>
    <pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">
      <rect width="4" height="3" fill="{BG}"/>
      <rect y="3" width="4" height="1" fill="#000000" opacity="0.18"/>
    </pattern>
  </defs>
  <rect width="600" height="600" fill="{BG}"/>
  <text text-anchor="middle" dominant-baseline="middle"
        font-family="'Space Grotesk', system-ui, sans-serif" font-weight="700"
        font-size="150" letter-spacing="-6" fill="{TEXT}" opacity="0.07">{spans}</text>
  {accent_mark}
  <rect width="600" height="600" fill="url(#scan)"/>
</svg>"""


def seed():
    for item in DEMO:
        filename = f"demo_{item['slug']}.svg"
        (MEDIA_DIR / filename).write_text(make_svg(item["ghost"], item["accent"]),
                                          encoding="utf-8")
        db.add_media(
            filename=filename, m_type=item["type"], title=item["title"],
            description=item["desc"], date_label=item["date"], year=item["year"],
            size=item["size"], is_locked=item["is_locked"], min_stars=item["min_stars"],
        )

    # Fill the About tab so the whole app looks complete in the demo.
    db.set_setting("logo_text", "Demo Studio")
    db.set_setting("about_text",
                   "Visual designer. Type, grunge, motion.\nMade under the influence.")
    if not db.list_social():
        db.add_social("brand-instagram", "https://instagram.com/", "Instagram")
        db.add_social("brand-behance", "https://behance.net/", "Behance")
        db.add_social("mail", "mailto:hello@example.com", "Email")

    print(f"Seeded {len(DEMO)} demo items + About content.")
    print("Preview:  python app.py  ->  http://localhost:5000")
    print("Wipe it:  python reset.py")


def wipe():
    db.wipe_all()
    for f in MEDIA_DIR.glob("*"):
        if f.name != ".gitkeep":
            try:
                f.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    db.init_db()
    if "--reset" in sys.argv:
        wipe()
    elif db.list_media():
        print("Gallery already has media. Use:")
        print("  python seed_demo.py --reset   (replace everything with demo content)")
        print("  python reset.py               (clear to empty)")
        sys.exit(1)
    seed()
