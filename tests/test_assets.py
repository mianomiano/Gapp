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


def test_share_links_are_untouched(client):
    """Guards the fix above: the share sheet must keep its destinations."""
    html = client.get("/").data
    for destination in (b"wa.me", b"t.me", b"twitter.com", b"instagram.com"):
        assert destination in html, f"share destination lost: {destination}"
