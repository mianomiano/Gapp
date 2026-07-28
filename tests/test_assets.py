"""The app must load zero external resources — see Global Constraints.

"Load" means fetched automatically when the page opens: stylesheets, scripts,
images, and CSS url()/@import. Outbound share links (wa.me, t.me, twitter.com,
instagram.com) are destinations the user chooses to navigate to, not resources,
so they are correctly left alone — the share sheet depends on them.

telegram.org is exempt: the Mini App SDK is required by Telegram itself and
resolves wherever the app is allowed to open at all.
"""
import re

# href/src on a loading element, plus CSS url() and @import.
LOADED = re.compile(
    rb"""(?:<(?:link|script|img|source|iframe)\b[^>]*?(?:href|src)\s*=\s*['"]"""
    rb"""|url\(\s*['"]?|@import\s+['"])"""
    rb"""(https?://[^'")\s>]+)""",
    re.IGNORECASE,
)

EXEMPT = (b"telegram.org",)


def _external_resources(html: bytes):
    """Off-site URLs the browser fetches without being asked."""
    found = set()
    for url in LOADED.findall(html):
        host = url.split(b"//", 1)[1].split(b"/", 1)[0]
        if not any(host.endswith(allowed) for allowed in EXEMPT):
            found.add(url)
    return sorted(found)


def test_index_loads_no_external_resources(client):
    assert _external_resources(client.get("/").data) == []


def test_admin_loads_no_external_resources(client):
    assert _external_resources(client.get("/admin").data) == []


def test_icon_stylesheet_is_served_locally(client):
    assert b"/static/vendor/tabler-icons.min.css" in client.get("/").data
    assert client.get("/static/vendor/tabler-icons.min.css").status_code == 200


def test_icon_font_actually_loads(client):
    """A 200 on the stylesheet is not enough — the first vendoring shipped a
    CSS whose src: was empty, so every icon rendered as a blank box."""
    css = client.get("/static/vendor/tabler-icons.min.css").data.decode("utf-8")

    src = re.search(r"src:\s*([^;}]+)", css)
    assert src, "no src: descriptor in the icon CSS"
    assert src.group(1).strip(), "src: descriptor is empty — icons will not render"

    url = re.search(r"url\(['\"]?([^'\")]+)", src.group(1))
    assert url, f"no url() in src: {src.group(1)!r}"

    # The path is relative to the stylesheet, which lives in /static/vendor/.
    served = client.get(f"/static/vendor/{url.group(1)}")
    assert served.status_code == 200, f"icon font 404s at {url.group(1)}"
    assert served.data[:4] == b"wOF2", "icon font is not a valid woff2 file"


def test_share_links_are_untouched(client):
    """Guards the fix above: the share sheet must keep its destinations."""
    html = client.get("/").data
    for destination in (b"wa.me", b"t.me", b"twitter.com", b"instagram.com"):
        assert destination in html, f"share destination lost: {destination}"
