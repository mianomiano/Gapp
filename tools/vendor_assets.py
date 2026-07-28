"""One-off: pull external assets into static/ so the app needs no CDN.

Run from the repo root:   python tools/vendor_assets.py
Optionally convert local fonts too:
                          python tools/vendor_assets.py "C:\\GAAP\\fonts"

Commit whatever it writes. Re-run only to bump the pinned version.
"""
import hashlib
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "static" / "vendor"
VENDOR_FONTS = VENDOR / "fonts"
FONTS = ROOT / "static" / "fonts"

# Pinned deliberately. @latest can change the glyph set without warning.
TABLER_VERSION = "3.31.0"
TABLER_BASE = f"https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@{TABLER_VERSION}"

# Google's CSS API returns woff2 URLs when asked with a modern UA.
GOOGLE_CSS = (
    "https://fonts.googleapis.com/css2"
    "?family=Space+Grotesk:wght@400;700&family=Share+Tech+Mono&display=swap"
)
# Google sniffs the User-Agent and serves .ttf to anything it does not
# recognise as a modern browser. A complete Chrome signature gets woff2.
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def fetch(url: str) -> bytes:
    print(f"  GET {url}")
    resp = requests.get(url, headers=UA, timeout=60)
    resp.raise_for_status()
    return resp.content


def vendor_tabler() -> None:
    """Download the icon CSS and its woff2, rewriting src to point locally.

    The whole src: descriptor is rebuilt rather than edited. Stripping the
    unwanted woff/ttf/eot entries with a regex is how this broke the first
    time: '\\.woff' also matches inside '.woff2', so the one format we
    actually keep got deleted and every icon rendered as an empty box.
    """
    VENDOR_FONTS.mkdir(parents=True, exist_ok=True)
    css = fetch(f"{TABLER_BASE}/dist/tabler-icons.min.css").decode("utf-8")

    # woff2 alone covers every browser Telegram runs on.
    name = "tabler-icons.woff2"
    (VENDOR_FONTS / name).write_bytes(fetch(f"{TABLER_BASE}/dist/fonts/{name}"))

    src = f"src:url('fonts/{name}') format('woff2')"
    css, count = re.subn(r"src:[^;}]*", src, css, count=1)
    if count != 1:
        sys.exit("Could not find the src: descriptor in the Tabler CSS.")

    (VENDOR / "tabler-icons.min.css").write_text(css, encoding="utf-8")
    print(f"  wrote {VENDOR / 'tabler-icons.min.css'}")


def vendor_default_fonts() -> None:
    """Download the two default families as woff2 so no CDN is needed.

    Google serves hash-named files, so each is saved under a deterministic
    name the template can reference directly.
    """
    FONTS.mkdir(parents=True, exist_ok=True)
    resp = requests.get(GOOGLE_CSS, headers=UA, timeout=60)
    resp.raise_for_status()

    # Google emits one @font-face per unicode subset (vietnamese, latin-ext,
    # latin). We keep only latin: these are fallbacks for the default English
    # UI, and a copy needing Cyrillic uploads its own font in admin — neither
    # Space Grotesk nor Share Tech Mono ships Cyrillic glyphs at all.
    latin = re.compile(r"unicode-range:[^;]*U\+0000-00FF")

    # family -> content hash -> weights sharing those exact bytes. A variable
    # font serves one file for every weight, so writing it per weight would
    # ship the same bytes twice.
    seen = {}
    for block in resp.text.split("@font-face"):
        family = re.search(r"font-family:\s*'([^']+)'", block)
        weight = re.search(r"font-weight:\s*(\d+)", block)
        url = re.search(r"url\((https://[^)]+\.(?:woff2|ttf))\)", block)
        if not (family and url):
            continue
        if "unicode-range" in block and not latin.search(block):
            continue
        data = fetch(url.group(1))
        if url.group(1).endswith(".ttf"):
            data = _ttf_to_woff2(data)
        digest = hashlib.md5(data).hexdigest()
        entry = seen.setdefault(family.group(1), {})
        entry.setdefault(digest, {"data": data, "weights": []})
        entry[digest]["weights"].append(int(weight.group(1)) if weight else 400)

    if not seen:
        sys.exit("No fonts found in the Google CSS response — check the UA header.")

    faces = []
    for family, variants in seen.items():
        slug = family.replace(" ", "")
        for variant in variants.values():
            weights = sorted(set(variant["weights"]))
            suffix = "var" if len(weights) > 1 else str(weights[0])
            name = f"{slug}-{suffix}.woff2"
            (FONTS / name).write_bytes(variant["data"])
            print(f"  wrote {FONTS / name}  ({len(variant['data']):,} bytes, "
                  f"weights {weights})")
            faces.append((slug, name, weights))

    print("\n  Paste into templates/index.html:\n")
    for slug, name, weights in faces:
        css_family = "AppMono" if "Mono" in slug else "AppDisplay"
        span = f"{weights[0]} {weights[-1]}" if len(weights) > 1 else str(weights[0])
        print(f"""    @font-face {{
      font-family: '{css_family}';
      src: url('/static/fonts/{name}') format('woff2');
      font-weight: {span};
      font-style: normal;
      font-display: swap;
    }}
""")


def _ttf_to_woff2(data: bytes) -> bytes:
    """Repack TrueType bytes as woff2, for when Google serves .ttf anyway."""
    import io

    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        sys.exit("Google served .ttf — install the converter: pip install fonttools brotli")

    font = TTFont(io.BytesIO(data))
    font.flavor = "woff2"
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def convert_local_ttf(source: Path) -> None:
    """Convert every .ttf in `source` to .woff2 in static/fonts.

    woff2 is 2-3x smaller than ttf, which matters on mobile data. Requires
    `pip install fonttools brotli` — dev-only, not a runtime dependency.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        sys.exit("Install the converter first:  pip install fonttools brotli")

    FONTS.mkdir(parents=True, exist_ok=True)
    for ttf in sorted(source.glob("*.ttf")):
        out = FONTS / (ttf.stem.replace(" ", "") + ".woff2")
        font = TTFont(str(ttf))
        font.flavor = "woff2"
        font.save(str(out))
        print(f"  {ttf.name} -> {out.name}")


if __name__ == "__main__":
    print(f"Vendoring Tabler icons {TABLER_VERSION}...")
    try:
        vendor_tabler()
        print("Vendoring default fonts...")
        vendor_default_fonts()
    except requests.RequestException as exc:
        sys.exit(f"Download failed: {exc}")

    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
        print(f"Converting .ttf files in {src}...")
        convert_local_ttf(src)
    print("Done.")
