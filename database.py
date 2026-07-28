"""
SQLite storage for the gallery.

Single file, zero install, auto-created on first run. Holds media metadata,
likes, donations, content unlocks, social links, and app settings.

Everything here uses plain sqlite3 from the standard library — nothing to set up.
"""

import sqlite3
import time
from pathlib import Path

# The .db file lives next to this script.
DB_PATH = Path(__file__).resolve().parent / "gallery.db"


def get_conn():
    """Open a connection with row access by column name and FK enforcement."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables on first run and seed default settings. Idempotent."""
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS media (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT NOT NULL,
            type        TEXT NOT NULL DEFAULT 'photo',   -- 'photo' | 'video'
            title       TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            date_label  TEXT NOT NULL DEFAULT '',         -- e.g. '18 · 10 · 24'
            year        TEXT NOT NULL DEFAULT '',
            size        TEXT NOT NULL DEFAULT 'medium',   -- 'tall' | 'medium' | 'short'
            is_locked   INTEGER NOT NULL DEFAULT 0,       -- 0/1 paywalled
            min_stars   INTEGER NOT NULL DEFAULT 1,       -- stars to unlock / suggested donation
            likes       INTEGER NOT NULL DEFAULT 0,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS donations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id     INTEGER,
            tg_user_id   TEXT,
            stars_amount INTEGER NOT NULL DEFAULT 0,
            purpose      TEXT NOT NULL DEFAULT 'donation', -- 'donation' | 'unlock'
            timestamp    INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS unlocks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id   INTEGER NOT NULL,
            tg_user_id TEXT NOT NULL,
            created_at INTEGER NOT NULL DEFAULT 0,
            UNIQUE(media_id, tg_user_id)
        );

        CREATE TABLE IF NOT EXISTS media_likes (
            media_id   INTEGER NOT NULL,
            tg_user_id TEXT NOT NULL,
            PRIMARY KEY (media_id, tg_user_id)
        );

        CREATE TABLE IF NOT EXISTS social_links (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            platform   TEXT NOT NULL DEFAULT '',  -- tabler icon name, e.g. 'brand-instagram'
            url        TEXT NOT NULL DEFAULT '',
            label      TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS categories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL DEFAULT '',
            body        TEXT NOT NULL DEFAULT '',     -- long read text
            media_ids   TEXT NOT NULL DEFAULT '',     -- ordered comma list of media ids
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        """
    )

    # Migration: media gains a category_ids column (comma-separated ids, max 3).
    cols = [r["name"] for r in cur.execute("PRAGMA table_info(media)").fetchall()]
    if "category_ids" not in cols:
        cur.execute("ALTER TABLE media ADD COLUMN category_ids TEXT NOT NULL DEFAULT ''")

    # Migration: social links gain an in_header flag (show as a top-bar icon).
    scols = [r["name"] for r in cur.execute("PRAGMA table_info(social_links)").fetchall()]
    if "in_header" not in scols:
        cur.execute("ALTER TABLE social_links ADD COLUMN in_header INTEGER NOT NULL DEFAULT 0")

    # Migration: media can belong to a post (post_id > 0 = not shown on the wall).
    if "post_id" not in cols:
        cur.execute("ALTER TABLE media ADD COLUMN post_id INTEGER NOT NULL DEFAULT 0")

    # Migration: media stores its pixel size, so the wall can reserve the right
    # space before the file loads instead of guessing and then snapping.
    # 0 means unknown (rows added before this migration) — the client falls
    # back to measuring on load, as it always did.
    for col in ("width", "height"):
        if col not in cols:
            cur.execute(f"ALTER TABLE media ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")

    # Migration: per-item opt-in for the Send Stars button, used when the
    # stars_mode setting is 'checked'.
    if "show_stars" not in cols:
        cur.execute("ALTER TABLE media ADD COLUMN show_stars INTEGER NOT NULL DEFAULT 0")

    # Migration: posts gain categories, hashtags, likes and a stars amount.
    pcols = [r["name"] for r in cur.execute("PRAGMA table_info(posts)").fetchall()]
    for col, ddl in (
        ("category_ids", "ALTER TABLE posts ADD COLUMN category_ids TEXT NOT NULL DEFAULT ''"),
        ("hashtags",     "ALTER TABLE posts ADD COLUMN hashtags TEXT NOT NULL DEFAULT ''"),
        ("likes",        "ALTER TABLE posts ADD COLUMN likes INTEGER NOT NULL DEFAULT 0"),
        ("min_stars",    "ALTER TABLE posts ADD COLUMN min_stars INTEGER NOT NULL DEFAULT 1"),
        ("show_stars",   "ALTER TABLE posts ADD COLUMN show_stars INTEGER NOT NULL DEFAULT 0"),
    ):
        if col not in pcols:
            cur.execute(ddl)

    cur.execute(
        "CREATE TABLE IF NOT EXISTS post_likes ("
        "post_id INTEGER NOT NULL, tg_user_id TEXT NOT NULL,"
        "PRIMARY KEY (post_id, tg_user_id))"
    )

    # Per-post view log — one row per open. tg_user_id is '' for anonymous /
    # web-preview opens; unique-visitor counts use the non-empty ids.
    cur.execute(
        "CREATE TABLE IF NOT EXISTS post_views ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "post_id INTEGER NOT NULL, tg_user_id TEXT NOT NULL DEFAULT '',"
        "ts INTEGER NOT NULL DEFAULT 0)"
    )

    # Migration: donations gain a post_id so Stars sent to a post can be
    # attributed to it (post donations carry no media_id).
    dcols = [r["name"] for r in cur.execute("PRAGMA table_info(donations)").fetchall()]
    if "post_id" not in dcols:
        cur.execute("ALTER TABLE donations ADD COLUMN post_id INTEGER NOT NULL DEFAULT 0")

    cur.executescript(
        """
        -- Whole-app visit log: one row per app open (for overall visitor stats).
        CREATE TABLE IF NOT EXISTS visits (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_user_id  TEXT NOT NULL DEFAULT '',
            ts          INTEGER NOT NULL DEFAULT 0
        );

        -- Per-photo view log: one row each time a media item is opened.
        CREATE TABLE IF NOT EXISTS media_views (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id    INTEGER NOT NULL,
            tg_user_id  TEXT NOT NULL DEFAULT '',
            ts          INTEGER NOT NULL DEFAULT 0
        );

        -- Job / advertising inquiries sent from the About page.
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT NOT NULL DEFAULT '',
            tg_user_id  TEXT NOT NULL DEFAULT '',
            body        TEXT NOT NULL DEFAULT '',
            seen        INTEGER NOT NULL DEFAULT 0,
            ts          INTEGER NOT NULL DEFAULT 0
        );
        """
    )

    # Seed four sample categories on a fresh install.
    have = cur.execute("SELECT COUNT(*) AS c FROM categories").fetchone()["c"]
    if not have:
        for i, name in enumerate(["cat1", "cat2", "cat3", "cat4"]):
            cur.execute(
                "INSERT INTO categories (name, sort_order) VALUES (?, ?)", (name, i)
            )

    # Seed default settings only if missing.
    defaults = {
        "logo_text": "",           # this copy's visible name, set in the admin panel
        "logo_image": "",          # filename in static/media; overrides logo_text when set
        "splash_enabled": "0",     # '0' off, '1' on
        "splash_filename": "",     # intro video in static/media
        "about_text": "",          # optional blurb shown in the About view
        "bot_username": "",        # Telegram bot @username (no @) for the mini-app link
        "miniapp_name": "",        # mini app short name (t.me/<bot>/<name>)
        "contact_chat_id": "",     # Telegram chat id that receives About-page inquiries
    }
    for key, value in defaults.items():
        cur.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )

    conn.commit()
    conn.close()


# ── Settings ──────────────────────────────────────────────────────────────

def get_settings():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def set_setting(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


# ── Media ─────────────────────────────────────────────────────────────────

def list_media():
    """Wall media only (media that belongs to a post is excluded)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM media WHERE post_id = 0 ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_post_media(post_id):
    """Media uploaded into a specific post, in order."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM media WHERE post_id = ? ORDER BY sort_order ASC, id ASC",
        (post_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_media(media_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def normalize_category_ids(value):
    """Accept a list or comma-separated string of ids; return a clean,
    de-duplicated 'a,b,c' string of at most 3 numeric ids."""
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value or [])
    out = []
    for p in parts:
        p = str(p).strip()
        if p.isdigit() and p not in out:
            out.append(p)
    return ",".join(out[:3])


def add_media(filename, m_type, title, description, date_label, year, size,
              is_locked, min_stars, category_ids="", post_id=0,
              width=0, height=0):
    conn = get_conn()
    cur = conn.cursor()
    # New item goes to the TOP of the wall (newest first); post media append.
    if post_id:
        order = cur.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS m FROM media WHERE post_id = ?",
            (post_id,),
        ).fetchone()["m"]
    else:
        order = cur.execute(
            "SELECT COALESCE(MIN(sort_order), 0) - 1 AS m FROM media WHERE post_id = 0"
        ).fetchone()["m"]
    cur.execute(
        """INSERT INTO media
           (filename, type, title, description, date_label, year, size,
            is_locked, min_stars, likes, sort_order, created_at, category_ids,
            post_id, width, height)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
        (filename, m_type, title, description, date_label, year, size,
         1 if is_locked else 0, max(0, int(min_stars)), order,
         int(time.time()), normalize_category_ids(category_ids), int(post_id),
         int(width), int(height)),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def update_media(media_id, fields):
    """Update an allow-listed set of columns for one media row."""
    allowed = {"title", "description", "date_label", "year", "size",
               "is_locked", "min_stars", "type", "filename", "category_ids",
               "width", "height", "show_stars"}
    sets, values = [], []
    for key, val in fields.items():
        if key not in allowed:
            continue
        if key in ("is_locked", "show_stars"):
            val = 1 if val in (1, "1", True, "true", "on") else 0
        if key in ("width", "height"):
            val = max(0, int(val or 0))
        if key == "min_stars":
            val = max(0, int(val))
        if key == "category_ids":
            val = normalize_category_ids(val)
        sets.append(f"{key} = ?")
        values.append(val)
    if not sets:
        return
    values.append(media_id)
    conn = get_conn()
    conn.execute(f"UPDATE media SET {', '.join(sets)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_media(media_id):
    """Delete the row and return its filename so the caller can remove the file."""
    conn = get_conn()
    row = conn.execute(
        "SELECT filename FROM media WHERE id = ?", (media_id,)
    ).fetchone()
    conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
    conn.execute("DELETE FROM media_likes WHERE media_id = ?", (media_id,))
    conn.execute("DELETE FROM unlocks WHERE media_id = ?", (media_id,))
    conn.commit()
    conn.close()
    return row["filename"] if row else None


def reorder_media(ordered_ids):
    """Persist a new wall order given a list of media ids, first = top."""
    conn = get_conn()
    for index, media_id in enumerate(ordered_ids):
        conn.execute(
            "UPDATE media SET sort_order = ? WHERE id = ?", (index, media_id)
        )
    conn.commit()
    conn.close()


# ── Categories ────────────────────────────────────────────────────────────

def list_categories():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM categories ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_category(name):
    conn = get_conn()
    cur = conn.cursor()
    max_order = cur.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS m FROM categories"
    ).fetchone()["m"]
    cur.execute(
        "INSERT INTO categories (name, sort_order) VALUES (?, ?)",
        (name.strip() or "untitled", max_order + 1),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def delete_category(category_id):
    """Remove a category and strip its id from every media item."""
    cid = str(int(category_id))
    conn = get_conn()
    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    for row in conn.execute(
            "SELECT id, category_ids FROM media WHERE category_ids != ''").fetchall():
        ids = [x for x in row["category_ids"].split(",") if x and x != cid]
        conn.execute("UPDATE media SET category_ids = ? WHERE id = ?",
                     (",".join(ids), row["id"]))
    conn.commit()
    conn.close()


# ── Posts (long reads with attached media) ────────────────────────────────

def _clean_ids(value):
    """Normalize a list or comma string of media ids into 'a,b,c' (order kept)."""
    parts = value.split(",") if isinstance(value, str) else list(value or [])
    out = []
    for p in parts:
        p = str(p).strip()
        if p.isdigit() and p not in out:
            out.append(p)
    return ",".join(out)


def list_posts():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM posts ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_post(post_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_post(title, body, category_ids="", hashtags="", min_stars=1):
    conn = get_conn()
    cur = conn.cursor()
    min_order = cur.execute(
        "SELECT COALESCE(MIN(sort_order), 0) AS m FROM posts"
    ).fetchone()["m"]
    cur.execute(
        """INSERT INTO posts
           (title, body, media_ids, sort_order, created_at,
            category_ids, hashtags, min_stars)
           VALUES (?, ?, '', ?, ?, ?, ?, ?)""",
        (title, body, min_order - 1, int(time.time()),
         normalize_category_ids(category_ids), hashtags or "",
         max(1, int(min_stars or 1))),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def update_post(post_id, fields):
    allowed = {"title", "body", "category_ids", "hashtags", "min_stars",
               "show_stars"}
    sets, values = [], []
    for key, val in fields.items():
        if key not in allowed:
            continue
        if key == "show_stars":
            val = 1 if val in (1, "1", True, "true", "on") else 0
        if key == "category_ids":
            val = normalize_category_ids(val)
        if key == "min_stars":
            val = max(1, int(val or 1))
        sets.append(f"{key} = ?")
        values.append(val)
    if not sets:
        return
    values.append(post_id)
    conn = get_conn()
    conn.execute(f"UPDATE posts SET {', '.join(sets)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_post(post_id):
    """Delete a post and its uploaded media; return media filenames to remove."""
    conn = get_conn()
    files = [r["filename"] for r in
             conn.execute("SELECT filename FROM media WHERE post_id = ?",
                          (post_id,)).fetchall()]
    conn.execute("DELETE FROM media WHERE post_id = ?", (post_id,))
    conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    conn.execute("DELETE FROM post_likes WHERE post_id = ?", (post_id,))
    conn.commit()
    conn.close()
    return files


def post_like_total(post_id):
    conn = get_conn()
    base = conn.execute("SELECT likes FROM posts WHERE id = ?", (post_id,)).fetchone()
    per_user = conn.execute(
        "SELECT COUNT(*) AS c FROM post_likes WHERE post_id = ?", (post_id,)
    ).fetchone()["c"]
    conn.close()
    return (base["likes"] if base else 0) + per_user


def user_liked_post(post_id, tg_user_id):
    if not tg_user_id:
        return False
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM post_likes WHERE post_id = ? AND tg_user_id = ?",
        (post_id, str(tg_user_id)),
    ).fetchone()
    conn.close()
    return row is not None


def toggle_post_like(post_id, tg_user_id, liked):
    conn = get_conn()
    cur = conn.cursor()
    if tg_user_id:
        if liked:
            cur.execute("INSERT OR IGNORE INTO post_likes (post_id, tg_user_id) "
                        "VALUES (?, ?)", (post_id, str(tg_user_id)))
        else:
            cur.execute("DELETE FROM post_likes WHERE post_id = ? AND tg_user_id = ?",
                        (post_id, str(tg_user_id)))
        base = cur.execute("SELECT likes FROM posts WHERE id = ?", (post_id,)).fetchone()
        per_user = cur.execute("SELECT COUNT(*) AS c FROM post_likes WHERE post_id = ?",
                               (post_id,)).fetchone()["c"]
        total = (base["likes"] if base else 0) + per_user
    else:
        delta = 1 if liked else -1
        cur.execute("UPDATE posts SET likes = MAX(0, likes + ?) WHERE id = ?",
                    (delta, post_id))
        row = cur.execute("SELECT likes FROM posts WHERE id = ?", (post_id,)).fetchone()
        total = row["likes"] if row else 0
    conn.commit()
    conn.close()
    return total


# ── Likes ─────────────────────────────────────────────────────────────────

def toggle_like(media_id, tg_user_id, liked):
    """
    Set this user's like state for a media item and return the fresh total.
    When no user id is available (web preview) we fall back to a raw counter.
    """
    conn = get_conn()
    cur = conn.cursor()

    if tg_user_id:
        if liked:
            cur.execute(
                "INSERT OR IGNORE INTO media_likes (media_id, tg_user_id) "
                "VALUES (?, ?)",
                (media_id, str(tg_user_id)),
            )
        else:
            cur.execute(
                "DELETE FROM media_likes WHERE media_id = ? AND tg_user_id = ?",
                (media_id, str(tg_user_id)),
            )
        # Likes total = base count seeded by admin + distinct user likes.
        base = cur.execute(
            "SELECT likes FROM media WHERE id = ?", (media_id,)
        ).fetchone()
        per_user = cur.execute(
            "SELECT COUNT(*) AS c FROM media_likes WHERE media_id = ?",
            (media_id,),
        ).fetchone()["c"]
        total = (base["likes"] if base else 0) + per_user
    else:
        # Anonymous fallback — nudge the stored counter directly.
        delta = 1 if liked else -1
        cur.execute(
            "UPDATE media SET likes = MAX(0, likes + ?) WHERE id = ?",
            (delta, media_id),
        )
        row = cur.execute(
            "SELECT likes FROM media WHERE id = ?", (media_id,)
        ).fetchone()
        total = row["likes"] if row else 0

    conn.commit()
    conn.close()
    return total


def like_total(media_id):
    conn = get_conn()
    base = conn.execute(
        "SELECT likes FROM media WHERE id = ?", (media_id,)
    ).fetchone()
    per_user = conn.execute(
        "SELECT COUNT(*) AS c FROM media_likes WHERE media_id = ?", (media_id,)
    ).fetchone()["c"]
    conn.close()
    return (base["likes"] if base else 0) + per_user


def user_liked(media_id, tg_user_id):
    if not tg_user_id:
        return False
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM media_likes WHERE media_id = ? AND tg_user_id = ?",
        (media_id, str(tg_user_id)),
    ).fetchone()
    conn.close()
    return row is not None


# ── Unlocks & donations (Telegram Stars) ──────────────────────────────────

def is_unlocked(media_id, tg_user_id):
    if not tg_user_id:
        return False
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM unlocks WHERE media_id = ? AND tg_user_id = ?",
        (media_id, str(tg_user_id)),
    ).fetchone()
    conn.close()
    return row is not None


def grant_unlock(media_id, tg_user_id):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO unlocks (media_id, tg_user_id, created_at) "
        "VALUES (?, ?, ?)",
        (media_id, str(tg_user_id), int(time.time())),
    )
    conn.commit()
    conn.close()


def record_donation(media_id, tg_user_id, stars_amount, purpose, post_id=0):
    conn = get_conn()
    conn.execute(
        """INSERT INTO donations
           (media_id, tg_user_id, stars_amount, purpose, timestamp, post_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (media_id, str(tg_user_id) if tg_user_id else None,
         int(stars_amount), purpose, int(time.time()), int(post_id or 0)),
    )
    conn.commit()
    conn.close()


# ── Stats (admin only) ──────────────────────────────────────────────────────

def record_post_view(post_id, tg_user_id):
    """Log one open of a post. Anonymous opens store '' for the user id."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO post_views (post_id, tg_user_id, ts) VALUES (?, ?, ?)",
        (int(post_id), str(tg_user_id or ""), int(time.time())),
    )
    conn.commit()
    conn.close()


def post_stats(post_id):
    """Engagement numbers for one post: views, unique visitors, likes, stars."""
    conn = get_conn()
    views = conn.execute(
        "SELECT COUNT(*) AS c FROM post_views WHERE post_id = ?", (post_id,)
    ).fetchone()["c"]
    uniques = conn.execute(
        "SELECT COUNT(DISTINCT tg_user_id) AS c FROM post_views "
        "WHERE post_id = ? AND tg_user_id != ''", (post_id,)
    ).fetchone()["c"]
    stars = conn.execute(
        "SELECT COALESCE(SUM(stars_amount), 0) AS s FROM donations WHERE post_id = ?",
        (post_id,),
    ).fetchone()["s"]
    conn.close()
    return {
        "views": views,
        "uniques": uniques,
        "stars": int(stars or 0),
        "likes": post_like_total(post_id),
    }


def record_visit(tg_user_id):
    """Log one whole-app open (for overall visitor stats)."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO visits (tg_user_id, ts) VALUES (?, ?)",
        (str(tg_user_id or ""), int(time.time())),
    )
    conn.commit()
    conn.close()


def record_media_view(media_id, tg_user_id):
    """Log one open of a photo/video item."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO media_views (media_id, tg_user_id, ts) VALUES (?, ?, ?)",
        (int(media_id), str(tg_user_id or ""), int(time.time())),
    )
    conn.commit()
    conn.close()


def media_stats(media_id):
    """Engagement for one media item: views, unique viewers, likes, stars."""
    conn = get_conn()
    views = conn.execute(
        "SELECT COUNT(*) AS c FROM media_views WHERE media_id = ?", (media_id,)
    ).fetchone()["c"]
    uniques = conn.execute(
        "SELECT COUNT(DISTINCT tg_user_id) AS c FROM media_views "
        "WHERE media_id = ? AND tg_user_id != ''", (media_id,)
    ).fetchone()["c"]
    stars = conn.execute(
        "SELECT COALESCE(SUM(stars_amount), 0) AS s FROM donations WHERE media_id = ?",
        (media_id,),
    ).fetchone()["s"]
    conn.close()
    return {
        "views": views,
        "uniques": uniques,
        "stars": int(stars or 0),
        "likes": like_total(media_id),
    }


def overall_stats():
    """Whole-app totals: visits and unique visitors."""
    conn = get_conn()
    visits = conn.execute("SELECT COUNT(*) AS c FROM visits").fetchone()["c"]
    uniques = conn.execute(
        "SELECT COUNT(DISTINCT tg_user_id) AS c FROM visits WHERE tg_user_id != ''"
    ).fetchone()["c"]
    conn.close()
    return {"visits": visits, "uniques": uniques}


# ── Messages (About-page inquiries) ─────────────────────────────────────────

def add_message(username, tg_user_id, body):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (username, tg_user_id, body, seen, ts) "
        "VALUES (?, ?, ?, 0, ?)",
        (str(username or ""), str(tg_user_id or ""), body, int(time.time())),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def list_messages():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM messages ORDER BY ts DESC, id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def unseen_message_count():
    conn = get_conn()
    c = conn.execute("SELECT COUNT(*) AS c FROM messages WHERE seen = 0").fetchone()["c"]
    conn.close()
    return c


def mark_messages_seen():
    conn = get_conn()
    conn.execute("UPDATE messages SET seen = 1 WHERE seen = 0")
    conn.commit()
    conn.close()


def delete_message(message_id):
    conn = get_conn()
    conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    conn.commit()
    conn.close()


# ── Social links ──────────────────────────────────────────────────────────

def list_social():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM social_links ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_social(platform, url, label, in_header=False):
    conn = get_conn()
    cur = conn.cursor()
    max_order = cur.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS m FROM social_links"
    ).fetchone()["m"]
    cur.execute(
        "INSERT INTO social_links (platform, url, label, sort_order, in_header) "
        "VALUES (?, ?, ?, ?, ?)",
        (platform, url, label, max_order + 1, 1 if in_header else 0),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def update_social(link_id, fields):
    """Update an allow-listed set of columns for one social link."""
    allowed = {"platform", "url", "label", "in_header"}
    sets, values = [], []
    for key, val in fields.items():
        if key not in allowed:
            continue
        if key == "in_header":
            val = 1 if val in (1, "1", True, "true", "on") else 0
        sets.append(f"{key} = ?")
        values.append(val)
    if not sets:
        return
    values.append(link_id)
    conn = get_conn()
    conn.execute(f"UPDATE social_links SET {', '.join(sets)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_social(link_id):
    conn = get_conn()
    conn.execute("DELETE FROM social_links WHERE id = ?", (link_id,))
    conn.commit()
    conn.close()


# ── Maintenance ───────────────────────────────────────────────────────────

def wipe_all(reset_settings=True):
    """Clear all content (media, likes, unlocks, donations, social links).
    Clears rows rather than dropping the file, so a running server keeps working.
    Returns the list of media filenames the caller should delete from disk."""
    conn = get_conn()
    filenames = [r["filename"] for r in
                 conn.execute("SELECT filename FROM media").fetchall()]
    conn.executescript(
        "DELETE FROM media;"
        "DELETE FROM media_likes;"
        "DELETE FROM unlocks;"
        "DELETE FROM donations;"
        "DELETE FROM social_links;"
    )
    if reset_settings:
        conn.execute(
            "UPDATE settings SET value = '' "
            "WHERE key IN ('logo_text', 'logo_image', 'about_text', 'splash_filename')"
        )
        conn.execute("UPDATE settings SET value = '0' WHERE key = 'splash_enabled'")
    conn.commit()
    conn.close()
    return filenames
