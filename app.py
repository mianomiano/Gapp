"""
Gallery — Flask server.

Serves the Telegram Mini App, a small JSON API the front-end talks to, a
password-protected admin panel, and a background thread that handles Telegram
Stars payments (so donations / unlocks actually work).

Run it:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in BOT_TOKEN and ADMIN_PASSWORD
    python app.py
"""

import json
import os
import re
import secrets
import threading
import time
from functools import wraps
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import (
    Flask, jsonify, render_template, request, send_file, send_from_directory,
    session, redirect, url_for, abort,
)
from werkzeug.utils import secure_filename

import database as db
import downloads
import i18n
import imagesize
import snippets
import storage
import theme

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "static" / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
FONTS_DIR = BASE_DIR / "static" / "fonts"

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
PORT = int(os.environ.get("PORT", "5000"))

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Upload limits / whitelist.
FONT_EXT = {"woff2", "woff", "otf", "ttf"}
IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
VIDEO_EXT = {"mp4", "webm", "mov"}
ALLOWED_EXT = IMAGE_EXT | VIDEO_EXT
MAX_UPLOAD_MB = 64

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

db.init_db()

# Shown when nothing has been named yet in the admin panel. Deliberately
# generic — a copy of this app must never display someone else's name.
DEFAULT_BRAND = "Gallery"


def brand_name():
    """The visible name of this copy, from the admin panel."""
    return (db.get_settings().get("logo_text") or "").strip() or DEFAULT_BRAND


@app.context_processor
def inject_globals():
    """Per-copy identity and language, available to every template.

    Rendered server-side so the header shows the right mark and the right
    language on first paint, instead of flashing defaults until
    /api/settings comes back.
    """
    settings = db.get_settings()
    logo = (settings.get("logo_image") or "").strip()
    lang = i18n.current_language()
    strings = i18n.translations(lang)

    def subset(*prefixes):
        """Only the strings a given page's JavaScript can use. The gallery has
        no reason to ship the admin panel's help text to every visitor."""
        return json.dumps(
            {k: v for k, v in strings.items() if k.startswith(prefixes)},
            ensure_ascii=False,
        )

    return {
        "brand": (settings.get("logo_text") or "").strip() or DEFAULT_BRAND,
        "brand_logo": media_url(logo),
        "lang": lang,
        "t": lambda key: strings.get(key, key),
        "i18n_app_json": subset("nav.", "app.", "share."),
        "i18n_admin_json": subset("admin."),
        "languages": i18n.choices(),
        # Uploaded fonts are stored through the storage backend, so their URL
        # comes from there rather than being assumed to be on this host.
        "theme_css": theme.css_overrides(settings, font_url=media_url),
    }


# ── Helpers ───────────────────────────────────────────────────────────────

def ext_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def type_for_ext(extension):
    return "video" if extension in VIDEO_EXT else "photo"


def media_url(filename):
    """Public URL for a stored file — a local /static path or an R2 URL,
    depending on how this copy is configured. Empty in, empty out, so callers
    can pass an unset setting straight through."""
    filename = (filename or "").strip()
    return storage.backend().url(filename) if filename else ""


def save_upload(file_storage):
    """Validate and store an uploaded file under a randomized name. Returns
    (stored_filename, detected_type, width, height) or raises ValueError.

    Width/height come from the file header so the wall can reserve the right
    space before the image loads. Videos report (0, 0) — the client measures
    those on load, as it did for everything before.
    """
    if not file_storage or not file_storage.filename:
        raise ValueError("No file provided.")
    extension = ext_of(file_storage.filename)
    if extension not in ALLOWED_EXT:
        raise ValueError(f"Unsupported file type: .{extension}")
    safe_stem = secure_filename(file_storage.filename.rsplit(".", 1)[0]) or "file"
    stored = f"{safe_stem[:40]}_{secrets.token_hex(6)}.{extension}"

    header = file_storage.stream.read(64 * 1024)
    file_storage.stream.seek(0)
    width, height = imagesize.dimensions(header)

    storage.backend().save(stored, file_storage.stream)
    return stored, type_for_ext(extension), width, height


STARS_MODES = ("off", "all", "checked")
DEFAULT_STARS_MODE = "all"


def stars_visible(row):
    """Whether the voluntary Send Stars button shows for this item.

    Deliberately does NOT govern unlocking. The two share one button in the
    UI, so gating unlocks on this setting would make locked content
    permanently unviewable the moment donations were switched off — see
    tests/test_stars.py.
    """
    mode = db.get_settings().get("stars_mode") or DEFAULT_STARS_MODE
    if mode == "off":
        return False
    if mode == "checked":
        return bool(row["show_stars"])
    return True


def downloads_enabled():
    """Whether this copy offers downloadable content at all.

    Off by default: a recipient's copy is a gallery, and switching the whole
    section on is a deliberate act in the admin panel rather than something
    that appears the moment they upgrade.
    """
    return (db.get_settings().get("downloads_enabled") or "") == "1"


def post_access(post, tg_user_id=None):
    """How this post may be downloaded, and whether this user may right now.

    The price is read from the post row and never from the request — a
    client-supplied price lets anyone edit a 500★ asset down to 1★. Every
    caller that bills for a download gets its amount from here.
    """
    mode = post.get("access_mode") or db.DEFAULT_ACCESS_MODE
    if mode not in db.ACCESS_MODES:
        mode = db.DEFAULT_ACCESS_MODE
    price = max(0, int(post.get("price_stars") or 0))
    # A 'paid' post priced at zero would otherwise be unpayable *and*
    # undownloadable — treat it as free rather than stranding the content.
    paid = mode == "paid" and price > 0
    return {
        "mode": mode,
        "price": price,
        "paid": paid,
        "unlocked": (not paid) or db.is_post_unlocked(post["id"], tg_user_id),
    }


def snippet_srcdoc(post):
    """The post's snippet as one standalone document for the preview iframe.

    Assembled server-side so the client never has to concatenate three fields
    and get the ordering wrong. Empty string when the post has no snippet.
    """
    html_part = post.get("snippet_html") or ""
    css = post.get("snippet_css") or ""
    js = post.get("snippet_js") or ""
    if not (html_part.strip() or css.strip() or js.strip()):
        return ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<style>{css}</style></head><body>{html_part}"
        f"<script>{js}</script></body></html>"
    )


def media_public(item, tg_user_id=None):
    """Shape a media row for the public API, hiding src for locked items the
    current user has not unlocked."""
    unlocked = (not item["is_locked"]) or db.is_unlocked(item["id"], tg_user_id)
    return {
        "id": item["id"],
        "type": item["type"],
        "title": item["title"],
        "desc": item["description"],
        "date": item["date_label"],
        "year": item["year"],
        "size": item["size"],
        "isLocked": bool(item["is_locked"]),
        "unlocked": unlocked,
        "minStars": item["min_stars"],
        "likes": db.like_total(item["id"]),
        "liked": db.user_liked(item["id"], tg_user_id),
        "categories": [int(x) for x in (item.get("category_ids") or "").split(",") if x],
        "src": media_url(item["filename"]) if unlocked else "",
        # 0 when unknown (videos, or rows predating the width/height columns);
        # the client then measures the element on load instead.
        "width": item["width"],
        "height": item["height"],
        # Two separate flags on purpose: donations can be switched off, but a
        # locked item must always keep a way to be unlocked.
        "showStars": stars_visible(item),
        "canUnlock": bool(item["is_locked"]),
    }


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("admin"))
        return view(*args, **kwargs)
    return wrapper


# ── Public pages ──────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Public API ────────────────────────────────────────────────────────────

@app.route("/api/media")
def api_media():
    uid = request.args.get("uid", "")
    return jsonify([media_public(m, uid) for m in db.list_media()])


@app.route("/api/media/<int:media_id>")
def api_media_one(media_id):
    item = db.get_media(media_id)
    if not item:
        abort(404)
    uid = request.args.get("uid", "")
    return jsonify(media_public(item, uid))


@app.route("/api/visit", methods=["POST"])
def api_visit():
    """Logged once per app open for overall visitor stats (admin previews skip)."""
    if session.get("is_admin"):
        return jsonify({"ok": True})
    data = request.get_json(silent=True) or {}
    db.record_visit(str(data.get("uid") or ""))
    return jsonify({"ok": True})


@app.route("/api/media_view", methods=["POST"])
def api_media_view():
    """Logged when a photo/video is opened, for per-photo view stats."""
    if session.get("is_admin"):
        return jsonify({"ok": True})
    data = request.get_json(silent=True) or {}
    media_id = data.get("mediaId")
    if media_id:
        db.record_media_view(int(media_id), str(data.get("uid") or ""))
    return jsonify({"ok": True})


@app.route("/api/contact", methods=["POST"])
def api_contact():
    """A Job / Advertising inquiry from the About page: store it and (if a
    contact chat id is configured) forward it to the owner via the bot."""
    data = request.get_json(silent=True) or {}
    body = (data.get("message") or "").strip()
    if not body:
        return jsonify({"error": "Empty message."}), 400
    body = body[:2000]
    username = (data.get("username") or "").lstrip("@").strip()[:64]
    uid = str(data.get("uid") or "")
    db.add_message(username, uid, body)

    settings = db.get_settings()
    chat_id = (settings.get("contact_chat_id") or "").strip()
    if BOT_TOKEN and chat_id:
        who = f"@{username}" if username else (f"id {uid}" if uid else "anonymous")
        text = f"📩 New inquiry from {who}:\n\n{body}"
        try:
            requests.post(f"{TELEGRAM_API}/sendMessage",
                          json={"chat_id": chat_id, "text": text}, timeout=15)
        except requests.RequestException:
            pass  # already stored; admin inbox is the fallback
    return jsonify({"ok": True})


@app.route("/api/like", methods=["POST"])
def api_like():
    data = request.get_json(silent=True) or {}
    media_id = data.get("mediaId")
    liked = bool(data.get("liked"))
    uid = str(data.get("uid") or "")
    if not media_id:
        return jsonify({"error": "mediaId required"}), 400
    total = db.toggle_like(int(media_id), uid, liked)
    return jsonify({"likes": total, "liked": liked})


@app.route("/api/invoice", methods=["POST"])
def api_invoice():
    """Create a Telegram Stars invoice link for a donation or a content unlock."""
    if not BOT_TOKEN:
        return jsonify({"error": "BOT_TOKEN not configured on the server."}), 503

    data = request.get_json(silent=True) or {}
    media_id = data.get("mediaId")
    uid = str(data.get("uid") or "")
    item = db.get_media(int(media_id)) if media_id else None
    if not item:
        return jsonify({"error": "Unknown media item."}), 404

    purpose = "unlock" if item["is_locked"] else "donation"
    amount = max(1, int(item["min_stars"]))  # Stars must be >= 1
    # Payload travels back to us untouched in successful_payment.
    payload = f"{item['id']}|{uid}|{purpose}"

    title = ("Unlock: " if purpose == "unlock" else "Support: ") + (
        item["title"] or brand_name()
    )
    description = (
        f"Unlock “{item['title']}” to view it."
        if purpose == "unlock"
        else f"Send {amount}★ to support this work."
    )

    try:
        resp = requests.post(
            f"{TELEGRAM_API}/createInvoiceLink",
            json={
                "title": title[:32],
                "description": description[:255],
                "payload": payload,
                "currency": "XTR",                       # Telegram Stars
                "prices": [{"label": "Stars", "amount": amount}],
            },
            timeout=15,
        )
        body = resp.json()
    except requests.RequestException as exc:
        return jsonify({"error": f"Telegram request failed: {exc}"}), 502

    if not body.get("ok"):
        return jsonify({"error": body.get("description", "createInvoiceLink failed")}), 502

    return jsonify({"invoiceUrl": body["result"], "purpose": purpose, "amount": amount})


@app.route("/api/categories")
def api_categories():
    return jsonify([{"id": c["id"], "name": c["name"]} for c in db.list_categories()])


def _post_categories(post):
    names = {str(c["id"]): c["name"] for c in db.list_categories()}
    ids = [x for x in (post.get("category_ids") or "").split(",") if x]
    return [{"id": int(i), "name": names[i]} for i in ids if i in names]


def _post_hashtags(post):
    try:
        tags = json.loads(post.get("hashtags") or "[]")
    except (ValueError, TypeError):
        return []
    out = []
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, dict) and t.get("text"):
                out.append({"text": str(t["text"]), "color": str(t.get("color") or "")})
    return out


@app.route("/api/posts")
def api_posts():
    uid = request.args.get("uid", "")
    on = downloads_enabled()
    result = []
    for p in db.list_posts():
        media = db.list_post_media(p["id"])
        cover = media_url(media[0]["filename"]) if media else ""
        text = " ".join(re.sub(r"<[^>]+>", " ", p["body"] or "").split())
        access = post_access(p, uid)
        result.append({
            "id": p["id"],
            "title": p["title"],
            "excerpt": text[:160],
            "cover": cover,
            "count": len(media),
            "categories": _post_categories(p),
            "hashtags": _post_hashtags(p),
            # The card needs the price before the post is opened, so a paid
            # one can be styled and badged in the list.
            "accessMode": access["mode"] if on else "",
            "priceStars": access["price"] if on else 0,
            "unlocked": access["unlocked"] if on else False,
        })
    return jsonify(result)


@app.route("/api/posts/<int:post_id>")
def api_post_one(post_id):
    post = db.get_post(post_id)
    if not post:
        abort(404)
    uid = request.args.get("uid", "")
    # Count the open as a view — but not the admin's own previews.
    if not session.get("is_admin"):
        db.record_post_view(post_id, uid)
    # One list, uncapped. This used to truncate images to 15 with no warning
    # and split them from videos, which the client immediately re-merged.
    media = db.list_post_media(post_id)
    access = post_access(post, uid)
    on = downloads_enabled()
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
        "showStars": stars_visible(post),
        # Downloads — all four collapse to off/empty when the feature is
        # disabled, so the front-end needs no separate feature check.
        "downloadable": on,
        "accessMode": access["mode"] if on else "",
        "priceStars": access["price"] if on else 0,
        "unlocked": access["unlocked"] if on else False,
        "previewBg": post.get("preview_bg") or "dark",
        "snippet": snippet_srcdoc(post) if on else "",
    })


@app.route("/api/post_like", methods=["POST"])
def api_post_like():
    data = request.get_json(silent=True) or {}
    post_id = data.get("postId")
    if not post_id:
        return jsonify({"error": "postId required"}), 400
    liked = bool(data.get("liked"))
    uid = str(data.get("uid") or "")
    total = db.toggle_post_like(int(post_id), uid, liked)
    return jsonify({"likes": total, "liked": liked})


@app.route("/api/post_invoice", methods=["POST"])
def api_post_invoice():
    """Telegram Stars invoice to support a post (donation)."""
    if not BOT_TOKEN:
        return jsonify({"error": "BOT_TOKEN not configured on the server."}), 503
    data = request.get_json(silent=True) or {}
    post = db.get_post(int(data["postId"])) if data.get("postId") else None
    if not post:
        return jsonify({"error": "Unknown post."}), 404
    uid = str(data.get("uid") or "")
    amount = max(1, int(post["min_stars"]))
    payload = f"P{post['id']}|{uid}|donation"
    title = ("Support: " + (post["title"] or brand_name()))[:32]
    description = f"Send {amount}★ to support this post."[:255]
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/createInvoiceLink",
            json={"title": title, "description": description, "payload": payload,
                  "currency": "XTR", "prices": [{"label": "Stars", "amount": amount}]},
            timeout=15,
        )
        body = resp.json()
    except requests.RequestException as exc:
        return jsonify({"error": f"Telegram request failed: {exc}"}), 502
    if not body.get("ok"):
        return jsonify({"error": body.get("description", "createInvoiceLink failed")}), 502
    return jsonify({"invoiceUrl": body["result"], "amount": amount})


@app.route("/api/post_download/<int:post_id>")
def api_post_download(post_id):
    """Send the post as a ZIP, after checking this user may have it.

    A GET so the browser and Telegram's in-app browser can both take it as a
    normal download. The unlock is verified here, before anything is built —
    see downloads.py, which deliberately performs no access checks itself.
    """
    if not downloads_enabled():
        return jsonify({"error": "Downloads are not enabled."}), 404
    post = db.get_post(post_id)
    if not post:
        return jsonify({"error": "Unknown post."}), 404

    uid = request.args.get("uid", "")
    access = post_access(post, uid)
    if not access["unlocked"]:
        # 402 rather than 403: the client turns this into "pay to download"
        # instead of an error, and the price it needs is in the body.
        return jsonify({"error": "This download must be unlocked first.",
                        "priceStars": access["price"]}), 402

    media = db.list_post_media(post_id)
    archive = downloads.build_zip(post, media, storage.backend().open)
    filename = downloads.slugify(post["title"], post_id) + ".zip"
    return send_file(archive, mimetype="application/zip",
                     as_attachment=True, download_name=filename)


@app.route("/api/post_unlock_invoice", methods=["POST"])
def api_post_unlock_invoice():
    """Telegram Stars invoice to buy a paid download.

    Separate from /api/post_invoice on purpose. That one bills an amount the
    visitor chose; this one bills posts.price_stars and nothing else. Sharing
    an endpoint would put a client-supplied amount one refactor away from the
    paid path — see the spec's "two invoice paths, different trust levels".
    """
    if not BOT_TOKEN:
        return jsonify({"error": "BOT_TOKEN not configured on the server."}), 503
    if not downloads_enabled():
        return jsonify({"error": "Downloads are not enabled."}), 404
    data = request.get_json(silent=True) or {}
    post = db.get_post(int(data["postId"])) if data.get("postId") else None
    if not post:
        return jsonify({"error": "Unknown post."}), 404

    access = post_access(post, str(data.get("uid") or ""))
    if not access["paid"]:
        return jsonify({"error": "This post is not a paid download."}), 400

    uid = str(data.get("uid") or "")
    amount = access["price"]           # from the row, never from the request
    payload = f"D{post['id']}|{uid}|download"
    title = ("Download: " + (post["title"] or brand_name()))[:32]
    description = f"Unlock the download for {amount}★."[:255]
    try:
        resp = requests.post(
            f"{TELEGRAM_API}/createInvoiceLink",
            json={"title": title, "description": description, "payload": payload,
                  "currency": "XTR", "prices": [{"label": "Stars", "amount": amount}]},
            timeout=15,
        )
        body = resp.json()
    except requests.RequestException as exc:
        return jsonify({"error": f"Telegram request failed: {exc}"}), 502
    if not body.get("ok"):
        return jsonify({"error": body.get("description", "createInvoiceLink failed")}), 502
    return jsonify({"invoiceUrl": body["result"], "amount": amount})


def _miniapp_link(settings):
    """Build the t.me mini-app deep link from the configured bot + app name."""
    bot = (settings.get("bot_username") or "").lstrip("@").strip()
    name = (settings.get("miniapp_name") or "").strip()
    if bot and name:
        return f"https://t.me/{bot}/{name}"
    if bot:
        return f"https://t.me/{bot}?startapp"
    return ""


@app.route("/api/settings")
def api_settings():
    """Public settings + social links for the topbar logo and About view."""
    settings = db.get_settings()
    return jsonify({
        "logoText": settings.get("logo_text", ""),
        "logoImage": media_url(settings.get("logo_image")),
        "aboutText": settings.get("about_text", ""),
        "splashEnabled": settings.get("splash_enabled") == "1",
        "splashSrc": media_url(settings.get("splash_filename")),
        "miniAppLink": _miniapp_link(settings),
        "social": [
            {"platform": s["platform"], "url": s["url"], "label": s["label"],
             "inHeader": bool(s["in_header"])}
            for s in db.list_social()
        ],
    })


# ── Admin: auth ───────────────────────────────────────────────────────────

@app.route("/admin")
def admin():
    if not session.get("is_admin"):
        return render_template("admin.html", authed=False)
    return render_template("admin.html", authed=True)


@app.route("/admin/login", methods=["POST"])
def admin_login():
    password = (request.form.get("password")
                or (request.get_json(silent=True) or {}).get("password") or "")
    if ADMIN_PASSWORD and secrets.compare_digest(password, ADMIN_PASSWORD):
        session["is_admin"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Wrong password."}), 401


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return jsonify({"ok": True})


# ── Admin: media ──────────────────────────────────────────────────────────

def with_urls(rows):
    """Attach each row's real public URL.

    The admin panel used to build '/static/media/' + filename itself, which is
    only correct on the local backend. On R2 the files are not on this server
    at all and every thumbnail 404s, so the URL has to come from the storage
    layer — the same place the public API gets it.
    """
    out = []
    for row in rows:
        item = dict(row)
        item["url"] = media_url(item.get("filename"))
        out.append(item)
    return out


@app.route("/api/admin/media", methods=["GET"])
@admin_required
def admin_list_media():
    return jsonify(with_urls(db.list_media()))


@app.route("/api/admin/media", methods=["POST"])
@admin_required
def admin_add_media():
    try:
        stored, detected_type, width, height = save_upload(request.files.get("file"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    form = request.form
    media_id = db.add_media(
        filename=stored,
        m_type=form.get("type") or detected_type,
        title=form.get("title", ""),
        description=form.get("description", ""),
        date_label=form.get("date_label", ""),
        year=form.get("year", ""),
        size=form.get("size", "medium"),
        is_locked=form.get("is_locked") in ("1", "true", "on", True),
        min_stars=form.get("min_stars", 1) or 1,
        category_ids=form.getlist("category_ids"),
        width=width,
        height=height,
    )
    return jsonify({"ok": True, "id": media_id})


@app.route("/api/admin/media/<int:media_id>", methods=["PATCH"])
@admin_required
def admin_update_media(media_id):
    if not db.get_media(media_id):
        abort(404)
    # Optional file replacement.
    if request.files.get("file"):
        try:
            stored, detected_type, width, height = save_upload(request.files.get("file"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        old = db.get_media(media_id)
        db.update_media(media_id, {"filename": stored, "type": detected_type,
                                   "width": width, "height": height})
        _remove_file(old["filename"])
    fields = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    fields.pop("file", None)
    # Multi-valued category checkboxes: rebuild from the full list (empty = cleared).
    if request.form is not None and "category_ids_present" in request.form:
        fields["category_ids"] = ",".join(request.form.getlist("category_ids"))
        fields.pop("category_ids_present", None)
    # An unchecked box sends nothing, so the marker distinguishes "cleared"
    # from "not part of this form".
    if "show_stars_present" in fields:
        fields["show_stars"] = "1" if request.form.get("show_stars") else "0"
        fields.pop("show_stars_present", None)
    db.update_media(media_id, fields)
    return jsonify({"ok": True})


@app.route("/api/admin/media/<int:media_id>", methods=["DELETE"])
@admin_required
def admin_delete_media(media_id):
    filename = db.delete_media(media_id)
    _remove_file(filename)
    return jsonify({"ok": True})


@app.route("/api/admin/media/reorder", methods=["POST"])
@admin_required
def admin_reorder_media():
    data = request.get_json(silent=True) or {}
    ordered = [int(x) for x in data.get("order", [])]
    db.reorder_media(ordered)
    return jsonify({"ok": True})


# ── Admin: categories ─────────────────────────────────────────────────────

@app.route("/api/admin/categories", methods=["GET"])
@admin_required
def admin_list_categories():
    return jsonify(db.list_categories())


@app.route("/api/admin/categories", methods=["POST"])
@admin_required
def admin_add_category():
    data = request.get_json(silent=True) or request.form
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Category name required."}), 400
    cat_id = db.add_category(name)
    return jsonify({"ok": True, "id": cat_id})


@app.route("/api/admin/categories/<int:category_id>", methods=["DELETE"])
@admin_required
def admin_delete_category(category_id):
    db.delete_category(category_id)
    return jsonify({"ok": True})


# ── Admin: posts ──────────────────────────────────────────────────────────

@app.route("/api/admin/posts", methods=["GET"])
@admin_required
def admin_list_posts():
    return jsonify(db.list_posts())


# ── Admin: stats ──────────────────────────────────────────────────────────

_STAT_KEYS = ("views", "uniques", "likes", "stars")


def _load_stats_seen():
    """Last-seen stats snapshot for the 'new since you checked' badges.
    Shape: {"posts": {id: {..}}, "photos": {id: {..}}, "overall": {..}}."""
    try:
        seen = json.loads(db.get_settings().get("stats_seen") or "{}")
    except (ValueError, TypeError):
        seen = {}
    seen.setdefault("posts", {})
    seen.setdefault("photos", {})
    seen.setdefault("overall", {})
    return seen


def _stats_snapshot():
    """Current stats for every post + photo + the overall totals."""
    return {
        "posts": {str(p["id"]): db.post_stats(p["id"]) for p in db.list_posts()},
        "photos": {str(m["id"]): db.media_stats(m["id"]) for m in db.list_media()},
        "overall": db.overall_stats(),
    }


@app.route("/api/admin/stats", methods=["GET"])
@admin_required
def admin_stats():
    seen = _load_stats_seen()
    changed = 0

    def rows_for(items, seen_bucket):
        nonlocal changed
        out = []
        for it in items:
            s = it["_stats"]
            prev = seen_bucket.get(str(it["id"]), {})
            delta = {k: s[k] - int(prev.get(k, 0)) for k in _STAT_KEYS}
            row_changed = any(v > 0 for v in delta.values())
            if row_changed:
                changed += 1
            out.append({"id": it["id"], "label": it["label"],
                        "changed": row_changed, "delta": delta, **s})
        return out

    posts = rows_for(
        [{"id": p["id"], "label": p["title"], "_stats": db.post_stats(p["id"])}
         for p in db.list_posts()], seen["posts"])
    photos = rows_for(
        [{"id": m["id"], "label": (m["title"] or m["filename"]),
          "_stats": db.media_stats(m["id"])} for m in db.list_media()], seen["photos"])

    overall = db.overall_stats()
    prev_overall = seen.get("overall", {})
    overall_delta = {k: overall[k] - int(prev_overall.get(k, 0))
                     for k in ("visits", "uniques")}
    if any(v > 0 for v in overall_delta.values()):
        changed += 1

    return jsonify({
        "overall": {**overall, "delta": overall_delta},
        "photos": photos,
        "posts": posts,
        "changed": changed,
    })


@app.route("/api/admin/stats/seen", methods=["POST"])
@admin_required
def admin_stats_seen():
    """Snapshot current stats as 'seen' so future changes show as new again."""
    db.set_setting("stats_seen", json.dumps(_stats_snapshot()))
    return jsonify({"ok": True})


# ── Admin: messages (About-page inquiries) ─────────────────────────────────

@app.route("/api/admin/messages", methods=["GET"])
@admin_required
def admin_list_messages():
    return jsonify({"messages": db.list_messages(),
                    "unseen": db.unseen_message_count()})


@app.route("/api/admin/messages/seen", methods=["POST"])
@admin_required
def admin_messages_seen():
    db.mark_messages_seen()
    return jsonify({"ok": True})


@app.route("/api/admin/messages/<int:message_id>", methods=["DELETE"])
@admin_required
def admin_delete_message(message_id):
    db.delete_message(message_id)
    return jsonify({"ok": True})


def _save_post_media(post_id):
    """Save any uploaded files (field 'media') into the post."""
    for fs in request.files.getlist("media"):
        if not fs or not fs.filename:
            continue
        try:
            stored, detected, width, height = save_upload(fs)
        except ValueError:
            continue
        db.add_media(filename=stored, m_type=detected, title="", description="",
                     date_label="", year="", size="medium", is_locked=False,
                     min_stars=1, post_id=post_id, width=width, height=height)


@app.route("/api/admin/posts", methods=["POST"])
@admin_required
def admin_add_post():
    f = request.form
    post_id = db.add_post(
        title=f.get("title", ""),
        body=f.get("body", ""),
        category_ids=f.getlist("category_ids"),
        hashtags=f.get("hashtags", ""),
        min_stars=f.get("min_stars", 1) or 1,
    )
    _save_post_media(post_id)
    return jsonify({"ok": True, "id": post_id})


@app.route("/api/admin/posts/<int:post_id>", methods=["PATCH"])
@admin_required
def admin_update_post(post_id):
    if not db.get_post(post_id):
        abort(404)
    fields = {}
    for key in ("title", "body", "hashtags", "min_stars",
                "access_mode", "price_stars", "snippet_html", "snippet_css",
                "snippet_js", "preview_bg"):
        if key in request.form:
            fields[key] = request.form.get(key, "")
    if "category_ids_present" in request.form:
        fields["category_ids"] = ",".join(request.form.getlist("category_ids"))
    if "show_stars_present" in request.form:
        fields["show_stars"] = "1" if request.form.get("show_stars") else "0"

    # Ready-made snippet files, the alternative to pasting into the textareas.
    # Applied after the form fields so picking a file wins over whatever the
    # (untouched) textarea still held.
    uploaded = [(f.filename, f.read()) for f in request.files.getlist("snippet_files")
                if f and f.filename]
    if uploaded:
        try:
            fields.update(snippets.from_uploads(uploaded))
        except snippets.SnippetError as exc:
            return jsonify({"error": str(exc)}), 400

    db.update_post(post_id, fields)
    _save_post_media(post_id)        # any newly uploaded media appended
    return jsonify({"ok": True})


@app.route("/api/admin/posts/<int:post_id>", methods=["DELETE"])
@admin_required
def admin_delete_post(post_id):
    for filename in db.delete_post(post_id):
        _remove_file(filename)
    return jsonify({"ok": True})


@app.route("/api/admin/posts/<int:post_id>/media", methods=["GET"])
@admin_required
def admin_post_media(post_id):
    return jsonify(with_urls(db.list_post_media(post_id)))


# ── Admin: social links ───────────────────────────────────────────────────

@app.route("/api/admin/social", methods=["GET"])
@admin_required
def admin_list_social():
    return jsonify(db.list_social())


@app.route("/api/admin/social", methods=["POST"])
@admin_required
def admin_add_social():
    data = request.get_json(silent=True) or request.form
    link_id = db.add_social(
        platform=data.get("platform", ""),
        url=data.get("url", ""),
        label=data.get("label", ""),
        in_header=str(data.get("in_header", "")) in ("1", "true", "on", "True"),
    )
    return jsonify({"ok": True, "id": link_id})


@app.route("/api/admin/social/<int:link_id>", methods=["PATCH"])
@admin_required
def admin_update_social(link_id):
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    # Checkbox: present marker lets an unchecked box clear the flag.
    if request.form is not None and "in_header_present" in request.form:
        data["in_header"] = "1" if request.form.get("in_header") in ("1", "on", "true") else "0"
        data.pop("in_header_present", None)
    db.update_social(link_id, data)
    return jsonify({"ok": True})


@app.route("/api/admin/social/<int:link_id>", methods=["DELETE"])
@admin_required
def admin_delete_social(link_id):
    db.delete_social(link_id)
    return jsonify({"ok": True})


# ── Admin: settings (logo, splash, about) ─────────────────────────────────

@app.route("/api/admin/settings", methods=["GET"])
@admin_required
def admin_get_settings():
    return jsonify(db.get_settings())


@app.route("/api/admin/settings", methods=["POST"])
@admin_required
def admin_set_settings():
    # Plain text fields.
    for key in ("logo_text", "about_text", "bot_username", "miniapp_name",
                "contact_chat_id") + theme.THEME_KEYS:
        if key in request.form:
            db.set_setting(key, request.form.get(key, "").strip())

    # Checkbox: an unchecked box is not submitted, so the marker field is what
    # distinguishes "saved as off" from "this form was not part of the post".
    if "downloads_enabled_present" in request.form:
        on = request.form.get("downloads_enabled") in ("1", "true", "on")
        db.set_setting("downloads_enabled", "1" if on else "0")

    # Font uploads. Separate field names from the settings keys, so the stored
    # value stays the randomised filename we chose rather than anything the
    # browser sent. theme.py revalidates it before building a url().
    #
    # These go through the storage backend, not onto this server's disk. They
    # used to land in static/fonts, which on a host with an ephemeral
    # filesystem meant every redeploy silently reverted the app to its bundled
    # fonts while the setting still named the uploaded one — a 404 in a
    # @font-face, which fails invisibly.
    for field, setting in (("font_display_file", "font_display"),
                           ("font_mono_file", "font_mono")):
        upload = request.files.get(field)
        if not upload or not upload.filename:
            continue
        extension = ext_of(upload.filename)
        if extension not in FONT_EXT:
            return jsonify({"error": f"Unsupported font type: .{extension}"}), 400
        stem = re.sub(r"[^A-Za-z0-9_-]", "", Path(upload.filename).stem)[:40] or "font"
        stored = f"{stem}_{secrets.token_hex(4)}.{extension}"
        try:
            storage.backend().save(stored, upload.stream)
        except (storage.StorageError, ValueError) as exc:
            return jsonify({"error": f"Could not store the font: {exc}"}), 502
        db.set_setting(setting, stored)

    # Stars mode is validated against the known set rather than stored raw —
    # an unrecognised value would fall through to "show everywhere".
    if "stars_mode" in request.form:
        mode = request.form.get("stars_mode", "").strip()
        if mode in STARS_MODES:
            db.set_setting("stars_mode", mode)

    # Language: only accept codes that have a file on disk, so a bad value
    # cannot leave the app rendering raw keys.
    if "language" in request.form:
        code = request.form.get("language", "").strip().lower()
        if code in i18n.available():
            db.set_setting("language", code)

    # Splash on/off checkbox.
    if "splash_enabled" in request.form:
        on = request.form.get("splash_enabled") in ("1", "true", "on")
        db.set_setting("splash_enabled", "1" if on else "0")

    # Logo image upload (optional).
    if request.files.get("logo_image"):
        try:
            stored, _, _, _ = save_upload(request.files.get("logo_image"))
            db.set_setting("logo_image", stored)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    if request.form.get("clear_logo_image") in ("1", "true", "on"):
        old = db.get_settings().get("logo_image")
        db.set_setting("logo_image", "")
        _remove_file(old)

    # Splash video upload (optional).
    if request.files.get("splash_video"):
        try:
            stored, detected, _, _ = save_upload(request.files.get("splash_video"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if detected != "video":
            _remove_file(stored)
            return jsonify({"error": "Splash must be a video file."}), 400
        old = db.get_settings().get("splash_filename")
        db.set_setting("splash_filename", stored)
        _remove_file(old)
    if request.form.get("clear_splash") in ("1", "true", "on"):
        old = db.get_settings().get("splash_filename")
        db.set_setting("splash_filename", "")
        db.set_setting("splash_enabled", "0")
        _remove_file(old)

    return jsonify({"ok": True, "settings": db.get_settings()})


def _remove_file(filename):
    """Delete a stored file, ignoring if it is already gone. Best-effort in
    both backends — a failed delete leaves an orphan, never a broken page."""
    if filename:
        storage.backend().delete(filename)


# Explicit static route. Only reached when media lives on local disk; with R2
# configured the URLs point at the bucket and never come back here.
@app.route("/static/media/<path:filename>")
def media_file(filename):
    return send_from_directory(MEDIA_DIR, filename)


# ── Telegram Stars payment poller ─────────────────────────────────────────

def _telegram_poller():
    """
    Long-poll getUpdates so Stars payments complete without a webhook.

    Two updates matter:
      * pre_checkout_query  -> must answer ok=True within ~10s or payment fails.
      * message.successful_payment -> the trustworthy "paid" signal; we read the
        invoice payload we set earlier and record the donation / grant unlock.
    """
    if not BOT_TOKEN:
        print("[stars] BOT_TOKEN not set — payment poller disabled. "
              "Donations/unlocks will not work until you add it to .env.")
        return

    print("[stars] payment poller started.")
    offset = None
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": json.dumps(
                ["pre_checkout_query", "message"])}
            if offset is not None:
                params["offset"] = offset
            resp = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=40)
            body = resp.json()
            if not body.get("ok"):
                time.sleep(3)
                continue

            for update in body.get("result", []):
                offset = update["update_id"] + 1
                _handle_update(update)
        except requests.RequestException:
            time.sleep(3)
        except Exception as exc:  # keep the thread alive no matter what
            print(f"[stars] poller error: {exc}")
            time.sleep(3)


def _handle_update(update):
    # 1) Approve the pre-checkout so Telegram lets the payment through.
    if "pre_checkout_query" in update:
        pcq = update["pre_checkout_query"]
        try:
            requests.post(
                f"{TELEGRAM_API}/answerPreCheckoutQuery",
                json={"pre_checkout_query_id": pcq["id"], "ok": True},
                timeout=15,
            )
        except requests.RequestException:
            pass
        return

    # 2) Record the completed payment.
    message = update.get("message") or {}
    payment = message.get("successful_payment")
    if not payment:
        return

    payload = payment.get("invoice_payload", "")
    amount = payment.get("total_amount", 0)  # in Stars for XTR
    parts = payload.split("|")
    first = parts[0] if parts else ""
    uid = parts[1] if len(parts) > 1 and parts[1] else (
        str(message.get("from", {}).get("id", "")))
    purpose = parts[2] if len(parts) > 2 else "donation"

    # Paid download — payload starts with 'D<post_id>'. Checked before the
    # 'P' branch below because both are post payments; only this one grants
    # permanent access to the archive.
    if first.startswith("D") and first[1:].isdigit():
        post_id = int(first[1:])
        db.record_donation(None, uid, amount, "download", post_id=post_id)
        if uid:
            db.grant_post_unlock(post_id, uid)
        print(f"[stars] download unlocked: post={post_id} uid={uid} amount={amount}")
        return

    # Post donation — payload starts with 'P<post_id>'.
    if first.startswith("P") and first[1:].isdigit():
        db.record_donation(None, uid, amount, "post", post_id=int(first[1:]))
        print(f"[stars] post donation: post={first[1:]} uid={uid} amount={amount}")
        return

    media_id = int(first) if first.isdigit() else None
    if media_id:
        db.record_donation(media_id, uid, amount, purpose)
        if purpose == "unlock" and uid:
            db.grant_unlock(media_id, uid)
        print(f"[stars] {purpose} recorded: media={media_id} uid={uid} amount={amount}")


def start_poller():
    thread = threading.Thread(target=_telegram_poller, daemon=True)
    thread.start()


def serve():
    """Run the app, preferring a production server when one is installed.

    Everything starts from here rather than from a WSGI entry point on
    purpose: start_poller() only runs under __main__, so launching this app
    with `gunicorn app:app` would serve pages perfectly while silently never
    processing a single Stars payment. Keep the start command `python app.py`.

    Only ever run ONE instance. The poller uses Telegram long-polling, and a
    second one causes getUpdates conflicts that break payments for both.
    """
    start_poller()
    try:
        from waitress import serve as waitress_serve
    except ImportError:
        print("[server] waitress not installed — using the Flask development "
              "server. Fine locally; install waitress for deployment.")
        # threaded=True so the poller and requests run concurrently.
        app.run(host="0.0.0.0", port=PORT, threaded=True)
        return

    print(f"[server] waitress on 0.0.0.0:{PORT}")
    waitress_serve(app, host="0.0.0.0", port=PORT, threads=8)


if __name__ == "__main__":
    serve()
