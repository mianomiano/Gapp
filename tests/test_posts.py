"""Post media handling and cell sizing."""
import io
import struct
import zlib


def _png(width, height):
    """A real PNG of the given size — the server reads its header to store
    dimensions, so a stub of arbitrary bytes would not do."""
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _post_with_media(admin_client, count, size=(40, 30)):
    resp = admin_client.post("/api/admin/posts", data={"title": "P", "body": "b"})
    post_id = resp.get_json()["id"]
    for i in range(count):
        # PATCH, not POST — the collection endpoint creates, this one updates.
        resp = admin_client.patch(f"/api/admin/posts/{post_id}", data={
            "media": (io.BytesIO(_png(*size)), f"img{i}.png"),
        }, content_type="multipart/form-data")
        assert resp.status_code == 200, f"attach failed: {resp.status_code}"
    return post_id


def test_post_returns_more_than_fifteen_images(admin_client, client):
    post_id = _post_with_media(admin_client, 20)
    data = client.get(f"/api/posts/{post_id}").get_json()
    assert len(data["media"]) == 20, "images past the fifteenth were dropped"


def test_post_media_is_a_single_list(admin_client, client):
    """The server used to split images and videos into two arrays that the
    client immediately re-merged."""
    post_id = _post_with_media(admin_client, 3)
    data = client.get(f"/api/posts/{post_id}").get_json()
    assert "media" in data
    assert "images" not in data and "videos" not in data


def test_media_rows_carry_dimensions(temp_db):
    import database as db
    media_id = db.add_media(filename="x.png", m_type="photo", title="", description="",
                            date_label="", year="", size="medium", is_locked=False,
                            min_stars=1, width=800, height=600)
    row = db.get_media(media_id)
    assert row["width"] == 800 and row["height"] == 600


def test_dimensions_default_to_zero_for_existing_rows(temp_db):
    """The migration adds the columns to a live database, so old rows have
    no dimensions and the client must cope."""
    import database as db
    media_id = db.add_media(filename="x.png", m_type="photo", title="", description="",
                            date_label="", year="", size="medium", is_locked=False,
                            min_stars=1)
    assert db.get_media(media_id)["width"] == 0


def test_upload_records_image_dimensions(admin_client, client):
    admin_client.post("/api/admin/media", data={
        "file": (io.BytesIO(_png(120, 60)), "wide.png"), "title": "wide",
    }, content_type="multipart/form-data")
    item = client.get("/api/media").get_json()[0]
    assert item["width"] == 120 and item["height"] == 60


def test_api_exposes_dimensions(admin_client, client):
    post_id = _post_with_media(admin_client, 1, size=(64, 16))
    media = client.get(f"/api/posts/{post_id}").get_json()["media"][0]
    assert media["width"] == 64 and media["height"] == 16
