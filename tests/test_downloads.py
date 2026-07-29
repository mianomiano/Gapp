"""The ZIP builder and its filename rules."""
import io
import zipfile

import pytest

import downloads


def fake_opener(files):
    """An open_file that serves bytes from a dict, and raises for anything else."""
    def _open(name):
        if name not in files:
            raise FileNotFoundError(name)
        return io.BytesIO(files[name])
    return _open


# ── slugify ───────────────────────────────────────────────────────────────

def test_slug_from_title():
    assert downloads.slugify("Neon Buttons Pack", 7) == "neon-buttons-pack"


def test_slug_strips_punctuation_and_case():
    assert downloads.slugify("  CSS/JS — Tricks!!  ", 7) == "css-js-tricks"


def test_slug_falls_back_to_id_when_title_is_empty():
    assert downloads.slugify("", 7) == "post-7"
    assert downloads.slugify("   ", 7) == "post-7"


def test_slug_falls_back_to_id_for_non_latin_titles():
    """Russian titles reduce to nothing — the archive still needs a name."""
    assert downloads.slugify("Кнопки", 12) == "post-12"


# ── archive contents ──────────────────────────────────────────────────────

def test_archive_always_has_the_three_files():
    zip_bytes = downloads.build_zip(
        {"id": 1, "title": "T", "body": "", "snippet_html": "",
         "snippet_css": "", "snippet_js": ""},
        [], fake_opener({}),
    )
    with zipfile.ZipFile(zip_bytes) as archive:
        assert set(archive.namelist()) == {"index.html", "style.css", "script.js"}


def test_snippet_columns_become_the_files():
    zip_bytes = downloads.build_zip(
        {"id": 1, "title": "Btn", "body": "", "snippet_html": "<button>Go</button>",
         "snippet_css": ".b{color:red}", "snippet_js": "console.log(1)"},
        [], fake_opener({}),
    )
    with zipfile.ZipFile(zip_bytes) as archive:
        assert archive.read("style.css").decode() == ".b{color:red}"
        assert archive.read("script.js").decode() == "console.log(1)"
        index = archive.read("index.html").decode()
        assert "<button>Go</button>" in index
        assert '<link rel="stylesheet" href="style.css">' in index
        assert '<script src="script.js"></script>' in index


def test_media_lands_under_assets():
    media = [{"filename": "a_1234.png", "type": "photo"},
             {"filename": "b_5678.webm", "type": "video"}]
    zip_bytes = downloads.build_zip(
        {"id": 1, "title": "T", "body": "", "snippet_html": "",
         "snippet_css": "", "snippet_js": ""},
        media, fake_opener({"a_1234.png": b"PNGDATA", "b_5678.webm": b"WEBMDATA"}),
    )
    with zipfile.ZipFile(zip_bytes) as archive:
        assert archive.read("assets/a_1234.png") == b"PNGDATA"
        assert archive.read("assets/b_5678.webm") == b"WEBMDATA"


def test_unreadable_media_is_skipped_not_fatal():
    """One missing file must not deny someone the content they paid for."""
    media = [{"filename": "here.png", "type": "photo"},
             {"filename": "gone.png", "type": "photo"}]
    zip_bytes = downloads.build_zip(
        {"id": 1, "title": "T", "body": "", "snippet_html": "",
         "snippet_css": "", "snippet_js": ""},
        media, fake_opener({"here.png": b"OK"}),
    )
    with zipfile.ZipFile(zip_bytes) as archive:
        names = archive.namelist()
        assert "assets/here.png" in names
        assert "assets/gone.png" not in names


def test_post_without_a_snippet_still_opens():
    """An image-only post downloads as a page that renders its attachments."""
    media = [{"filename": "shot_9.png", "type": "photo"}]
    zip_bytes = downloads.build_zip(
        {"id": 3, "title": "Shots", "body": "<p>hello</p>", "snippet_html": "",
         "snippet_css": "", "snippet_js": ""},
        media, fake_opener({"shot_9.png": b"X"}),
    )
    with zipfile.ZipFile(zip_bytes) as archive:
        index = archive.read("index.html").decode()
        assert "<h1>Shots</h1>" in index
        assert "<p>hello</p>" in index
        assert 'src="assets/shot_9.png"' in index


def test_video_attachments_render_as_video_tags():
    zip_bytes = downloads.build_zip(
        {"id": 3, "title": "V", "body": "", "snippet_html": "",
         "snippet_css": "", "snippet_js": ""},
        [{"filename": "clip_1.webm", "type": "video"}],
        fake_opener({"clip_1.webm": b"X"}),
    )
    with zipfile.ZipFile(zip_bytes) as archive:
        index = archive.read("index.html").decode()
        assert '<video src="assets/clip_1.webm"' in index


def test_title_is_escaped_in_the_document():
    """A title is plain text; it must not be able to close the <title> tag."""
    zip_bytes = downloads.build_zip(
        {"id": 1, "title": "</title><script>alert(1)</script>", "body": "",
         "snippet_html": "x", "snippet_css": "", "snippet_js": ""},
        [], fake_opener({}),
    )
    with zipfile.ZipFile(zip_bytes) as archive:
        index = archive.read("index.html").decode()
        assert "<script>alert(1)</script>" not in index
        assert "&lt;/title&gt;" in index


def test_archive_is_a_valid_readable_zip():
    zip_bytes = downloads.build_zip(
        {"id": 1, "title": "T", "body": "", "snippet_html": "",
         "snippet_css": "", "snippet_js": ""},
        [], fake_opener({}),
    )
    with zipfile.ZipFile(zip_bytes) as archive:
        assert archive.testzip() is None
