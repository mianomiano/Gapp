"""Stars button visibility.

The donation button and the unlock button are the same element in the UI.
Governing both with one setting would make locked content permanently
unviewable the moment the owner turned donations off — so unlocking never
obeys the setting.
"""
import pytest


def _media(temp_db, **kwargs):
    import database as db
    fields = dict(filename="x.png", m_type="photo", title="", description="",
                  date_label="", year="", size="medium", is_locked=False,
                  min_stars=1)
    fields.update(kwargs)
    return db.add_media(**fields)


@pytest.fixture
def locked_item(temp_db):
    return _media(temp_db, is_locked=True, min_stars=10, title="Locked")


def test_default_mode_shows_the_button(client, temp_db):
    item_id = _media(temp_db)
    assert client.get(f"/api/media/{item_id}").get_json()["showStars"] is True


def test_mode_off_hides_the_donation_button(client, temp_db):
    import database as db
    item_id = _media(temp_db)
    db.set_setting("stars_mode", "off")
    assert client.get(f"/api/media/{item_id}").get_json()["showStars"] is False


def test_mode_off_still_allows_unlocking_locked_content(client, temp_db, locked_item):
    """The whole point of the split — 'off' means stop asking for money, not
    destroy access to paid content."""
    import database as db
    db.set_setting("stars_mode", "off")
    item = client.get(f"/api/media/{locked_item}").get_json()
    assert item["isLocked"] is True
    assert item["canUnlock"] is True


def test_mode_checked_respects_the_per_item_flag(client, temp_db):
    import database as db
    on, off = _media(temp_db), _media(temp_db)
    db.update_media(on, {"show_stars": "1"})
    db.set_setting("stars_mode", "checked")
    assert client.get(f"/api/media/{on}").get_json()["showStars"] is True
    assert client.get(f"/api/media/{off}").get_json()["showStars"] is False


def test_posts_carry_the_flag_too(admin_client, client, temp_db):
    import database as db
    post_id = admin_client.post("/api/admin/posts",
                                data={"title": "P"}).get_json()["id"]
    db.set_setting("stars_mode", "checked")
    assert client.get(f"/api/posts/{post_id}").get_json()["showStars"] is False

    db.update_post(post_id, {"show_stars": "1"})
    assert client.get(f"/api/posts/{post_id}").get_json()["showStars"] is True


def test_admin_can_set_the_mode(admin_client):
    resp = admin_client.post("/api/admin/settings", data={"stars_mode": "checked"})
    assert resp.status_code == 200
    import database as db
    assert db.get_settings()["stars_mode"] == "checked"


def test_invalid_mode_is_rejected(admin_client):
    admin_client.post("/api/admin/settings", data={"stars_mode": "banana"})
    import database as db
    assert db.get_settings().get("stars_mode", "") != "banana"


def test_unlock_invoice_works_regardless_of_mode(client, temp_db, locked_item, monkeypatch):
    """A locked item must still be purchasable with donations switched off."""
    import database as db
    import app as app_module
    db.set_setting("stars_mode", "off")
    monkeypatch.setattr(app_module, "BOT_TOKEN", "test-token")

    class FakeResponse:
        @staticmethod
        def json():
            return {"ok": True, "result": "https://t.me/invoice/abc"}

    monkeypatch.setattr(app_module.requests, "post",
                        lambda *a, **k: FakeResponse())
    resp = client.post("/api/invoice", json={"mediaId": locked_item, "uid": "42"})
    assert resp.status_code == 200
    assert resp.get_json()["purpose"] == "unlock"
