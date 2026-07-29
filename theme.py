"""Per-copy appearance, stored in settings and injected as a :root override.

The templates already reference every one of these as a CSS custom property,
so overriding them restyles the whole app without touching a stylesheet and
without a build step.

Everything here ends up inside a <style> tag, so each value is validated
rather than trusted — a setting containing "} body { display:none" would
otherwise rewrite the page, and one containing "</style>" would break out of
it entirely.
"""
import re

HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# No path separators: the filename is interpolated into a url(), and a
# traversal would let the page reference arbitrary files on disk.
FONT_FILE = re.compile(r"^[A-Za-z0-9_-]+\.(?:woff2|woff|otf|ttf)$")

# setting key -> CSS custom property it overrides
COLOR_KEYS = {
    "accent_color": "--green",
    "bg_page": "--bg-page",
    "bg_base": "--bg-base",
    "bg_raised": "--bg-raised",
}

RADIUS_MIN, RADIUS_MAX = 0, 12

# Uploaded fonts re-declare the families the templates already use, so
# nothing else has to change. A later @font-face wins over the earlier one.
FONT_KEYS = (
    ("font_display", "AppDisplay", "--font-display"),
    ("font_mono", "AppMono", "--font-mono"),
)

THEME_KEYS = tuple(COLOR_KEYS) + ("cell_radius", "font_display", "font_mono")


def _expand(hex_value):
    """#abc -> (170, 187, 204). Both CSS hex lengths, as three ints."""
    digits = hex_value.lstrip("#")
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))


def _colors(settings):
    out = []
    for key, prop in COLOR_KEYS.items():
        value = (settings.get(key) or "").strip()
        if value and HEX.match(value):
            out.append(f"  {prop}: {value};")

    # The accent is not one colour but a family: a dim variant for borders and
    # a translucent one for fills. Those were fixed greens, so choosing a new
    # accent used to repaint the thin highlights and leave every border and
    # filled panel behind — which read as "the colour did not change".
    accent = (settings.get("accent_color") or "").strip()
    if accent and HEX.match(accent):
        red, green, blue = _expand(accent)
        # ~38% toward black: dark enough to sit as a border against the page,
        # light enough to stay recognisably the same hue.
        dim = tuple(round(channel * 0.38) for channel in (red, green, blue))
        out.append("  --green-dim: #%02x%02x%02x;" % dim)
        out.append(f"  --green-bg: rgba({red}, {green}, {blue}, 0.05);")
        out.append(f"  --green-soft: rgba({red}, {green}, {blue}, 0.12);")
    return out


def _radius(settings):
    raw = (settings.get("cell_radius") or "").strip()
    if not raw:
        return []
    try:
        value = int(float(raw))
    except ValueError:
        return []
    return [f"  --cell-radius: {max(RADIUS_MIN, min(RADIUS_MAX, value))}px;"]


def _default_font_url(filename):
    """Where an uploaded font lives when no resolver is supplied."""
    return f"/static/fonts/{filename}"


def _fonts(settings, font_url=_default_font_url):
    faces, variables = [], []
    for key, family, var in FONT_KEYS:
        filename = (settings.get(key) or "").strip()
        if not filename or not FONT_FILE.match(filename):
            continue
        faces.append(
            "@font-face {\n"
            f"  font-family: '{family}';\n"
            f"  src: url('{font_url(filename)}');\n"
            "  font-weight: 400 700;\n"
            "  font-style: normal;\n"
            "  font-display: swap;\n"
            "}"
        )
        variables.append(f"  {var}: '{family}', system-ui, sans-serif;")
    return faces, variables


def css_overrides(settings, font_url=_default_font_url):
    """A stylesheet fragment for the current settings, or '' if none apply.

    `font_url` resolves a stored font filename to a URL. It is injected because
    uploaded fonts live wherever the storage backend puts them — local disk in
    a plain copy, R2 on a host whose filesystem is wiped on every deploy.
    """
    faces, font_vars = _fonts(settings, font_url)
    declarations = _colors(settings) + _radius(settings) + font_vars
    if not declarations and not faces:
        return ""
    blocks = list(faces)
    if declarations:
        blocks.append(":root {\n" + "\n".join(declarations) + "\n}")
    return "\n".join(blocks)
