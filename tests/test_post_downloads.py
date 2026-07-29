"""Download access control and the paid-invoice boundary.

The security-relevant assertions here are the ones about price: a paid
download must be billed at posts.price_stars and never at anything the
client sent.
"""
import io
import zipfile

import pytest

import database as db


@pytest.fixture
def post_id(temp_db):
    return db.add_post("Neon Buttons", "<p>body</p>")


def enable_downloads():
    db.set_setting("downloads_enabled", "1")


# ── the feature gate ──────────────────────────────────────────────────────

def test_downloads_are_off_by_default(client, post_id):
    res = client.get(f"/api/post_download/{post_id}")
    assert res.status_code == 404


def test_post_payload_hides_download_fields_when_disabled(client, post_id):
    body = client.get(f"/api/posts/{post_id}").get_json()
    assert body["downloadable"] is False
    assert body["accessMode"] == ""
    assert body["snippet"] == ""


def test_post_payload_exposes_them_once_enabled(client, post_id):
    enable_downloads()
    body = client.get(f"/api/posts/{post_id}").get_json()
    assert body["downloadable"] is True
    assert body["accessMode"] == "free_donate"


# ── free and free_donate ──────────────────────────────────────────────────

def test_free_post_downloads_without_payment(client, post_id):
    enable_downloads()
    db.update_post(post_id, {"access_mode": "free"})
    res = client.get(f"/api/post_download/{post_id}")
    assert res.status_code == 200
    assert res.mimetype == "application/zip"


def test_download_filename_comes_from_the_title(client, post_id):
    enable_downloads()
    res = client.get(f"/api/post_download/{post_id}")
    assert "neon-buttons.zip" in res.headers["Content-Disposition"]


def test_downloaded_archive_contains_the_snippet(client, post_id):
    enable_downloads()
    db.update_post(post_id, {"snippet_html": "<button>Go</button>",
                             "snippet_css": ".b{}", "snippet_js": "var a=1"})
    res = client.get(f"/api/post_download/{post_id}")
    with zipfile.ZipFile(io.BytesIO(res.data)) as archive:
        assert archive.read("script.js").decode() == "var a=1"
        assert "<button>Go</button>" in archive.read("index.html").decode()


# ── paid ──────────────────────────────────────────────────────────────────

def test_paid_post_is_refused_without_an_unlock(client, post_id):
    enable_downloads()
    db.update_post(post_id, {"access_mode": "paid", "price_stars": 25})
    res = client.get(f"/api/post_download/{post_id}?uid=555")
    assert res.status_code == 402
    assert res.get_json()["priceStars"] == 25


def test_paid_post_downloads_after_the_unlock_is_granted(client, post_id):
    enable_downloads()
    db.update_post(post_id, {"access_mode": "paid", "price_stars": 25})
    db.grant_post_unlock(post_id, "555")
    res = client.get(f"/api/post_download/{post_id}?uid=555")
    assert res.status_code == 200


def test_an_unlock_belongs_to_one_user_only(client, post_id):
    enable_downloads()
    db.update_post(post_id, {"access_mode": "paid", "price_stars": 25})
    db.grant_post_unlock(post_id, "555")
    assert client.get(f"/api/post_download/{post_id}?uid=999").status_code == 402


def test_anonymous_user_cannot_reach_a_paid_download(client, post_id):
    """No uid means no unlock record can match — the archive stays shut."""
    enable_downloads()
    db.update_post(post_id, {"access_mode": "paid", "price_stars": 25})
    assert client.get(f"/api/post_download/{post_id}").status_code == 402


def test_paid_at_zero_stars_is_treated_as_free(client, post_id):
    """Otherwise the post is both unpayable and undownloadable."""
    enable_downloads()
    db.update_post(post_id, {"access_mode": "paid", "price_stars": 0})
    assert client.get(f"/api/post_download/{post_id}").status_code == 200


# ── the invoice boundary ──────────────────────────────────────────────────

def test_unlock_invoice_ignores_a_client_supplied_price(client, post_id, monkeypatch):
    """The whole reason this is a separate endpoint from /api/post_invoice."""
    import app as app_module

    sent = {}

    class FakeResponse:
        def json(self):
            return {"ok": True, "result": "https://t.me/invoice/x"}

    def fake_post(url, json=None, timeout=None):
        sent.update(json)
        return FakeResponse()

    monkeypatch.setattr(app_module, "BOT_TOKEN", "test-token")
    monkeypatch.setattr(app_module.requests, "post", fake_post)

    enable_downloads()
    db.update_post(post_id, {"access_mode": "paid", "price_stars": 500})

    res = client.post("/api/post_unlock_invoice",
                      json={"postId": post_id, "uid": "555", "amount": 1,
                            "priceStars": 1, "price_stars": 1})
    assert res.status_code == 200
    assert res.get_json()["amount"] == 500
    assert sent["prices"] == [{"label": "Stars", "amount": 500}]


def test_unlock_invoice_refuses_a_post_that_is_not_paid(client, post_id, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "BOT_TOKEN", "test-token")
    enable_downloads()
    res = client.post("/api/post_unlock_invoice", json={"postId": post_id, "uid": "5"})
    assert res.status_code == 400


def test_unlock_invoice_is_unavailable_when_downloads_are_off(client, post_id, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "BOT_TOKEN", "test-token")
    db.update_post(post_id, {"access_mode": "paid", "price_stars": 25})
    res = client.post("/api/post_unlock_invoice", json={"postId": post_id, "uid": "5"})
    assert res.status_code == 404


# ── the poller grants the unlock ──────────────────────────────────────────

def test_successful_payment_grants_the_post_unlock(app, post_id):
    """A 'D<id>' payload is what /api/post_unlock_invoice sets."""
    import app as app_module

    app_module._handle_update({
        "message": {
            "from": {"id": 555},
            "successful_payment": {"invoice_payload": f"D{post_id}|555|download",
                                   "total_amount": 25},
        }
    })
    assert db.is_post_unlocked(post_id, "555") is True


def test_a_post_donation_does_not_grant_a_download(app, post_id):
    """'P<id>' is a tip. It must not open the paid archive."""
    import app as app_module

    app_module._handle_update({
        "message": {
            "from": {"id": 555},
            "successful_payment": {"invoice_payload": f"P{post_id}|555|donation",
                                   "total_amount": 25},
        }
    })
    assert db.is_post_unlocked(post_id, "555") is False


# ── stored values are validated ───────────────────────────────────────────

def test_unknown_access_mode_falls_back(temp_db, post_id):
    db.update_post(post_id, {"access_mode": "free_for_me"})
    assert db.get_post(post_id)["access_mode"] == "free_donate"


def test_negative_price_is_clamped(temp_db, post_id):
    db.update_post(post_id, {"price_stars": -5})
    assert db.get_post(post_id)["price_stars"] == 0


# ── the admin toggle ──────────────────────────────────────────────────────

def test_admin_can_turn_downloads_on(admin_client, temp_db):
    admin_client.post("/api/admin/settings",
                      data={"downloads_enabled": "1",
                            "downloads_enabled_present": "1"})
    assert db.get_settings()["downloads_enabled"] == "1"


def test_admin_can_turn_downloads_back_off(admin_client, temp_db):
    """An unchecked box submits nothing — the marker is what turns it off."""
    db.set_setting("downloads_enabled", "1")
    admin_client.post("/api/admin/settings",
                      data={"downloads_enabled_present": "1"})
    assert db.get_settings()["downloads_enabled"] == "0"


def test_other_settings_saves_leave_the_toggle_alone(admin_client, temp_db):
    """Saving the logo form must not silently disable downloads."""
    db.set_setting("downloads_enabled", "1")
    admin_client.post("/api/admin/settings", data={"logo_text": "Gapp"})
    assert db.get_settings()["downloads_enabled"] == "1"


def test_admin_saves_the_post_download_fields(admin_client, post_id):
    admin_client.patch(f"/api/admin/posts/{post_id}", data={
        "access_mode": "paid", "price_stars": "25",
        "snippet_html": "<b>x</b>", "snippet_css": "b{}", "snippet_js": "1",
        "preview_bg": "checker",
    })
    post = db.get_post(post_id)
    assert post["access_mode"] == "paid"
    assert post["price_stars"] == 25
    assert post["snippet_html"] == "<b>x</b>"
    assert post["preview_bg"] == "checker"


def test_snippet_srcdoc_combines_the_three_fields(app, post_id):
    import app as app_module
    db.set_setting("downloads_enabled", "1")
    db.update_post(post_id, {"snippet_html": "<b>hi</b>", "snippet_css": "b{color:red}",
                             "snippet_js": "var a=1"})
    doc = app_module.snippet_srcdoc(db.get_post(post_id))
    assert "<style>b{color:red}</style>" in doc
    assert "<b>hi</b>" in doc
    assert "<script>var a=1</script>" in doc


def test_snippet_srcdoc_is_empty_without_a_snippet(app, post_id):
    import app as app_module
    assert app_module.snippet_srcdoc(db.get_post(post_id)) == ""
