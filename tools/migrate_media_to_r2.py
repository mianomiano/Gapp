"""Copy everything in static/media into the configured R2 bucket.

Run once, after setting the R2_* variables in .env, before deploying:

    python tools/migrate_media_to_r2.py            # show what would happen
    python tools/migrate_media_to_r2.py --upload   # actually upload

Filenames are preserved exactly, because they are what the database stores.
Nothing is deleted from local disk — keep it until the deployed app is
confirmed working, then remove it by hand if you want the space back.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv          # noqa: E402

load_dotenv(ROOT / ".env")

import storage                          # noqa: E402  (after load_dotenv)

LOCAL = ROOT / "static" / "media"


def main() -> None:
    upload = "--upload" in sys.argv

    store = storage.backend()
    if not isinstance(store, storage.R2Storage):
        sys.exit(
            "R2 is not configured — nothing to migrate to.\n"
            "Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, "
            "R2_BUCKET and R2_PUBLIC_URL in .env first."
        )

    files = sorted(p for p in LOCAL.glob("*") if p.is_file()
                   and p.name != ".gitkeep")
    if not files:
        print("static/media is empty — nothing to upload.")
        return

    total = sum(p.stat().st_size for p in files)
    print(f"{len(files)} file(s), {total / 1024 / 1024:.1f} MB")
    if not upload:
        for p in files:
            print(f"  would upload  {p.name}  ({p.stat().st_size / 1024:.0f} KB)")
        print("\nDry run. Re-run with --upload to do it.")
        return

    done = failed = 0
    for p in files:
        try:
            with p.open("rb") as handle:
                store.save(p.name, handle)
            print(f"  uploaded  {p.name}")
            done += 1
        except storage.StorageError as exc:
            print(f"  FAILED    {p.name}: {exc}")
            failed += 1

    print(f"\nuploaded {done}, failed {failed}")
    if failed:
        sys.exit(1)
    print(f"Spot-check one in a browser: {store.url(files[0].name)}")


if __name__ == "__main__":
    main()
