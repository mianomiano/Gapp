"""Shared pytest fixtures.

Every test runs against a throwaway SQLite file, never the live gallery.db.
database.DB_PATH is read inside get_conn() at call time, so repointing the
module attribute before init_db() is enough to isolate the whole app.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database as db  # noqa: E402


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the database module at an empty file and create the schema."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    return path


@pytest.fixture
def app(temp_db, tmp_path, monkeypatch):
    """The Flask app, wired to the temp DB and a temp media directory."""
    import app as app_module

    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(app_module, "MEDIA_DIR", media)
    app_module.app.config.update(TESTING=True, SECRET_KEY="test-key")
    return app_module.app


@pytest.fixture
def client(app):
    """Anonymous visitor."""
    return app.test_client()


@pytest.fixture
def admin_client(app):
    """Logged-in admin — skips the password round trip."""
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["is_admin"] = True
    return c
