"""Where uploaded media lives.

Two backends behind one interface:

  * LocalStorage — files under static/media, served by Flask. The default,
    and what a fresh copy of this app runs on with no configuration at all.
  * R2Storage — Cloudflare R2 via its S3-compatible API, for hosts with an
    ephemeral filesystem (Railway, Fly, Render) where local files vanish on
    every redeploy.

Selected by environment, so the same code runs in both places and nobody
has to create a cloud account to use the app.

Note on access: media URLs are public in both backends, and locked items are
protected by an unguessable filename rather than by access control — which is
how this app has always worked. Real protection for paid content belongs on
the download endpoint, where the server can check the unlock before sending
anything.
"""
import os
import shutil
from pathlib import Path

LOCAL_DIR = Path(__file__).resolve().parent / "static" / "media"
LOCAL_URL_PREFIX = "/static/media"

# Set once on first use. Tests reset it to force re-selection.
_BACKEND = None


class StorageError(RuntimeError):
    """Raised when a backend cannot complete an operation."""


def _safe_name(name: str) -> str:
    """Reject anything that is not a bare filename. Callers already generate
    randomised names; this stops a crafted one from escaping the directory."""
    if not name or "/" in name or "\\" in name or Path(name).name != name:
        raise ValueError(f"unsafe storage name: {name!r}")
    return name


class LocalStorage:
    """Files on the local disk, served by Flask's static route."""

    def save(self, name, fileobj):
        _safe_name(name)
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOCAL_DIR / name, "wb") as out:
            shutil.copyfileobj(fileobj, out)
        return name

    def url(self, name):
        return f"{LOCAL_URL_PREFIX}/{name}"

    def delete(self, name):
        try:
            (LOCAL_DIR / _safe_name(name)).unlink()
        except (FileNotFoundError, OSError, ValueError):
            pass          # already gone, or never valid — nothing to undo

    def open(self, name):
        return open(LOCAL_DIR / _safe_name(name), "rb")


class R2Storage:
    """Cloudflare R2 through its S3-compatible API."""

    def __init__(self, account_id, access_key, secret_key, bucket, public_base):
        import boto3                       # imported here: only R2 needs it
        from botocore.config import Config

        self.bucket = bucket
        self.public_base = public_base.rstrip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            # R2 ignores regions but the SDK insists on one.
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def save(self, name, fileobj):
        _safe_name(name)
        try:
            self.client.upload_fileobj(
                fileobj, self.bucket, name,
                ExtraArgs={"ContentType": _content_type(name)},
            )
        except Exception as exc:           # botocore raises a wide family
            raise StorageError(f"R2 upload failed for {name}: {exc}") from exc
        return name

    def url(self, name):
        return f"{self.public_base}/{name}"

    def delete(self, name):
        try:
            self.client.delete_object(Bucket=self.bucket, Key=_safe_name(name))
        except Exception:
            pass          # deletion is best-effort, same as the local backend

    def open(self, name):
        import io
        buf = io.BytesIO()
        self.client.download_fileobj(self.bucket, _safe_name(name), buf)
        buf.seek(0)
        return buf


CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif",
    "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
}


def _content_type(name):
    """R2 serves whatever Content-Type we set. Without it browsers download
    images instead of displaying them."""
    return CONTENT_TYPES.get(name.rsplit(".", 1)[-1].lower(),
                             "application/octet-stream")


def backend():
    """The configured backend, chosen once and reused."""
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = _select()
    return _BACKEND


def _select():
    settings = {key: os.environ.get(key, "").strip() for key in (
        "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET", "R2_PUBLIC_URL",
    )}
    if not all(settings.values()):
        # Partial configuration falls back rather than failing every request —
        # serving from disk beats a dead app.
        if any(settings.values()):
            missing = [k for k, v in settings.items() if not v]
            print(f"[storage] R2 partially configured, missing {missing} — "
                  "using local disk.")
        return LocalStorage()

    try:
        store = R2Storage(
            settings["R2_ACCOUNT_ID"], settings["R2_ACCESS_KEY_ID"],
            settings["R2_SECRET_ACCESS_KEY"], settings["R2_BUCKET"],
            settings["R2_PUBLIC_URL"],
        )
    except ImportError:
        print("[storage] R2 configured but boto3 is not installed — "
              "using local disk. Run: pip install boto3")
        return LocalStorage()

    print(f"[storage] using R2 bucket '{settings['R2_BUCKET']}'.")
    return store
