"""Media storage: local disk by default, Cloudflare R2 when configured.

The local backend must keep working with no configuration at all — that is
what a fresh copy of this app runs on, and what development uses.
"""
import io

import pytest

import storage


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_BACKEND", None)      # clear the cache
    monkeypatch.delenv("R2_BUCKET", raising=False)
    monkeypatch.setattr(storage, "LOCAL_DIR", tmp_path)
    return storage.backend()


def test_defaults_to_local_when_r2_is_not_configured(local):
    assert isinstance(local, storage.LocalStorage)


def test_local_save_writes_the_file(local):
    local.save("a.png", io.BytesIO(b"bytes"))
    assert (storage.LOCAL_DIR / "a.png").read_bytes() == b"bytes"


def test_local_url_is_the_static_path(local):
    assert local.url("a.png") == "/static/media/a.png"


def test_local_delete_removes_the_file(local):
    local.save("a.png", io.BytesIO(b"x"))
    local.delete("a.png")
    assert not (storage.LOCAL_DIR / "a.png").exists()


def test_local_delete_of_a_missing_file_is_silent(local):
    local.delete("never-existed.png")       # must not raise


def test_local_ignores_a_path_in_the_name(local):
    """A traversal in a stored filename must not escape the media directory."""
    with pytest.raises(ValueError):
        local.save("../../escape.png", io.BytesIO(b"x"))


def test_r2_is_selected_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "_BACKEND", None)
    for key, value in {
        "R2_ACCOUNT_ID": "acct",
        "R2_ACCESS_KEY_ID": "key",
        "R2_SECRET_ACCESS_KEY": "secret",
        "R2_BUCKET": "media",
        "R2_PUBLIC_URL": "https://cdn.example.com",
    }.items():
        monkeypatch.setenv(key, value)

    pytest.importorskip("boto3", reason="only needed when R2 is in use")
    assert isinstance(storage.backend(), storage.R2Storage)


def test_r2_url_uses_the_public_base(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_URL", "https://cdn.example.com/")
    r2 = storage.R2Storage.__new__(storage.R2Storage)   # no network, no client
    r2.public_base = "https://cdn.example.com"
    assert r2.url("a.png") == "https://cdn.example.com/a.png"


def test_incomplete_r2_config_falls_back_to_local(monkeypatch, tmp_path):
    """Half-configured R2 must not take the app down — better to serve from
    disk than to fail every request."""
    monkeypatch.setattr(storage, "_BACKEND", None)
    monkeypatch.setattr(storage, "LOCAL_DIR", tmp_path)
    monkeypatch.setenv("R2_BUCKET", "media")
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)
    assert isinstance(storage.backend(), storage.LocalStorage)


def test_database_path_defaults_beside_the_app():
    import database as db
    assert db.DB_PATH.name == "gallery.db"


def test_database_path_honours_the_env_var(tmp_path, monkeypatch):
    """Railway and friends wipe the container filesystem on redeploy, so the
    database has to be able to live on a mounted volume."""
    import importlib
    import database
    monkeypatch.setenv("DB_PATH", str(tmp_path / "vol" / "data.db"))
    reloaded = importlib.reload(database)
    try:
        assert reloaded.DB_PATH == tmp_path / "vol" / "data.db"
        assert reloaded.DB_PATH.parent.is_dir(), "parent directory not created"
    finally:
        monkeypatch.delenv("DB_PATH", raising=False)
        importlib.reload(database)
