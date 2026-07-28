"""Fill in width/height for media uploaded before the app recorded them.

Rows added before the width/height migration have 0, so the wall cannot
reserve their space up front and still jumps as they load. This reads each
file's header once and stores the size.

Run from the repo root:   python tools/backfill_dimensions.py
Safe to re-run: it only touches rows that are still 0, and never changes a
file on disk. Videos stay 0 — their size needs a real demuxer.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database as db          # noqa: E402
import imagesize               # noqa: E402

MEDIA_DIR = ROOT / "static" / "media"


def main() -> None:
    # Applies the width/height migration if the app has not been restarted
    # since it was added — otherwise the columns do not exist yet.
    db.init_db()

    conn = db.get_conn()
    rows = conn.execute(
        "SELECT id, filename, type FROM media WHERE width = 0 OR height = 0"
    ).fetchall()

    if not rows:
        print("Nothing to backfill — every row already has a size.")
        return

    filled = skipped = missing = 0
    for row in rows:
        path = MEDIA_DIR / row["filename"]
        if not path.is_file():
            print(f"  missing file: {row['filename']}")
            missing += 1
            continue

        with path.open("rb") as handle:
            width, height = imagesize.dimensions(handle.read(64 * 1024))

        if not (width and height):
            skipped += 1          # video, or a format without a parser
            continue

        conn.execute("UPDATE media SET width = ?, height = ? WHERE id = ?",
                     (width, height, row["id"]))
        print(f"  {row['filename']}  ->  {width}x{height}")
        filled += 1

    conn.commit()
    conn.close()
    print(f"\nfilled {filled}, skipped {skipped} (video/unknown), "
          f"missing {missing}, of {len(rows)} row(s)")


if __name__ == "__main__":
    main()
