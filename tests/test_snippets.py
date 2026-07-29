"""Uploading ready-made snippet files instead of pasting code."""
import io
import zipfile

import pytest

import snippets


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return buf.getvalue()


# ── single files ──────────────────────────────────────────────────────────

def test_html_file_fills_the_html_field():
    out = snippets.from_uploads([("button.html", b"<button>Go</button>")])
    assert out == {"snippet_html": "<button>Go</button>"}


def test_each_extension_maps_to_its_own_field():
    out = snippets.from_uploads([
        ("a.html", b"<b>x</b>"), ("a.css", b".b{}"), ("a.js", b"var a=1"),
    ])
    assert out == {"snippet_html": "<b>x</b>", "snippet_css": ".b{}",
                   "snippet_js": "var a=1"}


def test_htm_is_accepted_too():
    assert "snippet_html" in snippets.from_uploads([("old.htm", b"<i>x</i>")])


def test_unsupported_extension_is_rejected():
    with pytest.raises(snippets.SnippetError) as err:
        snippets.from_uploads([("thing.exe", b"MZ")])
    assert "thing.exe" in str(err.value)


def test_oversized_file_is_rejected():
    huge = b"x" * (snippets.MAX_FIELD_BYTES + 1)
    with pytest.raises(snippets.SnippetError):
        snippets.from_uploads([("big.css", huge)])


def test_non_utf8_file_still_lands():
    """Better an editable approximation than a rejected upload."""
    out = snippets.from_uploads([("latin.css", b"/* caf\xe9 */")])
    assert "caf" in out["snippet_css"]


# ── zip bundles ───────────────────────────────────────────────────────────

def test_zip_is_unpacked_into_the_three_fields():
    raw = make_zip({"index.html": "<b>hi</b>", "style.css": "b{color:red}",
                    "script.js": "var a=1"})
    out = snippets.from_uploads([("component.zip", raw)])
    assert out["snippet_html"] == "<b>hi</b>"
    assert out["snippet_css"] == "b{color:red}"
    assert out["snippet_js"] == "var a=1"


def test_zip_ignores_files_it_does_not_understand():
    raw = make_zip({"index.html": "<b>hi</b>", "readme.txt": "notes",
                    "logo.png": "\x89PNG"})
    out = snippets.from_uploads([("c.zip", raw)])
    assert set(out) == {"snippet_html"}


def test_top_level_file_wins_over_a_nested_one():
    raw = make_zip({"nested/deep/index.html": "<em>nested</em>",
                    "index.html": "<em>top</em>"})
    out = snippets.from_uploads([("c.zip", raw)])
    assert out["snippet_html"] == "<em>top</em>"


def test_zip_with_no_source_files_is_an_error():
    raw = make_zip({"notes.txt": "hello"})
    with pytest.raises(snippets.SnippetError) as err:
        snippets.from_uploads([("c.zip", raw)])
    assert "No .html" in str(err.value)


def test_corrupt_zip_is_an_error():
    with pytest.raises(snippets.SnippetError):
        snippets.from_uploads([("c.zip", b"not a zip at all")])


def test_archive_with_too_many_members_is_refused():
    raw = make_zip({f"f{i}.css": "a{}" for i in range(snippets.MAX_ZIP_MEMBERS + 1)})
    with pytest.raises(snippets.SnippetError) as err:
        snippets.from_uploads([("c.zip", raw)])
    assert "more than" in str(err.value)


def test_decompression_bomb_is_refused_before_reading():
    """One member that expands far past the budget must not be read at all."""
    raw = make_zip({"huge.css": "a" * (snippets.MAX_ZIP_TOTAL_BYTES + 10)})
    with pytest.raises(snippets.SnippetError) as err:
        snippets.from_uploads([("c.zip", raw)])
    assert "expands to more than" in str(err.value)


# ── ordering ──────────────────────────────────────────────────────────────

def test_a_later_file_replaces_an_earlier_one_of_the_same_kind():
    out = snippets.from_uploads([("a.css", b"first"), ("b.css", b"second")])
    assert out["snippet_css"] == "second"


def test_empty_selection_changes_nothing():
    assert snippets.from_uploads([]) == {}
    assert snippets.from_uploads([("", b""), ("a.css", b"")]) == {}


# ── through the admin endpoint ─────────────────────────────────────────────

def test_admin_can_upload_a_zip_onto_a_post(admin_client, temp_db):
    import database as db
    post_id = db.add_post("Card", "")
    raw = make_zip({"index.html": "<div class='card'>hi</div>",
                    "style.css": ".card{padding:20px}",
                    "script.js": "console.log('card')"})
    res = admin_client.patch(f"/api/admin/posts/{post_id}", data={
        "snippet_files": (io.BytesIO(raw), "card.zip"),
    }, content_type="multipart/form-data")
    assert res.status_code == 200
    post = db.get_post(post_id)
    assert post["snippet_html"] == "<div class='card'>hi</div>"
    assert post["snippet_css"] == ".card{padding:20px}"
    assert post["snippet_js"] == "console.log('card')"


def test_admin_can_upload_a_single_html_file(admin_client, temp_db):
    import database as db
    post_id = db.add_post("Btn", "")
    admin_client.patch(f"/api/admin/posts/{post_id}", data={
        "snippet_files": (io.BytesIO(b"<button>Buy</button>"), "btn.html"),
    }, content_type="multipart/form-data")
    assert db.get_post(post_id)["snippet_html"] == "<button>Buy</button>"


def test_an_upload_beats_the_textarea_in_the_same_save(admin_client, temp_db):
    """Picking a file is the more deliberate act of the two."""
    import database as db
    post_id = db.add_post("X", "")
    admin_client.patch(f"/api/admin/posts/{post_id}", data={
        "snippet_html": "stale textarea contents",
        "snippet_files": (io.BytesIO(b"<b>from file</b>"), "x.html"),
    }, content_type="multipart/form-data")
    assert db.get_post(post_id)["snippet_html"] == "<b>from file</b>"


def test_a_bad_upload_reports_the_reason_and_saves_nothing(admin_client, temp_db):
    import database as db
    post_id = db.add_post("X", "")
    res = admin_client.patch(f"/api/admin/posts/{post_id}", data={
        "title": "Renamed",
        "snippet_files": (io.BytesIO(b"MZ"), "virus.exe"),
    }, content_type="multipart/form-data")
    assert res.status_code == 400
    assert "virus.exe" in res.get_json()["error"]
    assert db.get_post(post_id)["title"] == "X", "the whole save must be refused"
