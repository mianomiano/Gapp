"""Building a post into a downloadable ZIP.

Everything here is generated on demand from data already in the post, so
there is nothing extra to upload or keep in sync: the snippet columns become
index.html / style.css / script.js, and the post's attached media become
assets/.

Access control is deliberately NOT in this module. The caller checks the
unlock first and only then asks for an archive — see the download endpoint in
app.py. Keeping the check outside means no code path can build an archive as
a side effect of something else and hand it to the wrong person.
"""
import html
import io
import re
import zipfile

# Media keeps its stored random-suffix filenames inside the archive. They are
# already unguessable, and renaming them to something tidy would break the
# relative paths written into index.html.
ASSETS_DIR = "assets"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(title, post_id):
    """A filesystem-safe stem for the archive.

    Non-Latin titles (Russian ones especially) reduce to nothing here, which
    is why the post id is always available as a fallback rather than letting
    an empty name through.
    """
    slug = _SLUG_STRIP.sub("-", (title or "").strip().lower()).strip("-")
    return slug or f"post-{post_id}"


def _asset_tag(filename, media_type):
    """One image or video element pointing at the archived copy."""
    src = f"{ASSETS_DIR}/{filename}"
    if media_type == "video":
        return (f'  <video src="{html.escape(src)}" controls playsinline '
                f'muted loop></video>')
    return f'  <img src="{html.escape(src)}" alt="">'


def standalone_html(post, media_rows):
    """index.html for the archive — openable with a double click.

    A post with a snippet becomes that snippet, verbatim, in a real document.
    A post without one becomes a plain page of its text and attachments, so
    an image-only post still downloads as something that opens.
    """
    title = html.escape(post.get("title") or "")
    snippet = post.get("snippet_html") or ""
    if snippet.strip():
        body = snippet
    else:
        parts = []
        if title:
            parts.append(f"  <h1>{title}</h1>")
        # The body is owner-authored rich text from the admin editor and is
        # already HTML; it goes in as-is, exactly as the app renders it.
        if post.get("body"):
            parts.append(f'  <div class="post-body">{post["body"]}</div>')
        parts.extend(_asset_tag(m["filename"], m["type"]) for m in media_rows)
        body = "\n".join(parts)

    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{title or 'Untitled'}</title>\n"
        '  <link rel="stylesheet" href="style.css">\n'
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        '  <script src="script.js"></script>\n'
        "</body>\n"
        "</html>\n"
    )


def build_zip(post, media_rows, open_file):
    """Return the archive as an in-memory buffer, positioned at the start.

    `open_file(filename)` yields a readable binary stream — the storage
    backend's `open`, injected so this works identically against local disk
    and R2, and so tests need neither.

    A media file that cannot be read is skipped rather than failing the whole
    download: one missing asset should not deny someone content they paid for.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", standalone_html(post, media_rows))
        archive.writestr("style.css", post.get("snippet_css") or "")
        archive.writestr("script.js", post.get("snippet_js") or "")

        for item in media_rows:
            name = item["filename"]
            try:
                with open_file(name) as src:
                    archive.writestr(f"{ASSETS_DIR}/{name}", src.read())
            except Exception:
                continue
    buf.seek(0)
    return buf
