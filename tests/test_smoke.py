def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"<!DOCTYPE html>" in resp.data


def test_admin_api_requires_login(client):
    assert client.get("/api/admin/media").status_code == 401


def test_admin_api_allows_logged_in(admin_client):
    assert admin_client.get("/api/admin/media").status_code == 200


def test_tests_do_not_touch_the_real_database(temp_db):
    import database as db
    assert db.DB_PATH == temp_db
    assert "gallery.db" not in str(db.DB_PATH)
