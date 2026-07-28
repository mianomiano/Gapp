"""Header parsing for the four uploadable image formats."""
import io

import pytest

import imagesize

pytest.importorskip("PIL", reason="Pillow is a dev-only dependency, used to "
                                  "generate real files to parse")
from PIL import Image  # noqa: E402


def _encode(fmt, size=(37, 19), **kwargs):
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 30, 90)).save(buf, fmt, **kwargs)
    return buf.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "GIF", "JPEG", "WEBP"])
def test_reads_dimensions(fmt):
    assert imagesize.dimensions(_encode(fmt)) == (37, 19)


def test_reads_lossless_webp():
    assert imagesize.dimensions(_encode("WEBP", lossless=True)) == (37, 19)


def test_reads_progressive_jpeg():
    """Progressive JPEGs use SOF2 rather than SOF0."""
    assert imagesize.dimensions(_encode("JPEG", progressive=True)) == (37, 19)


def test_non_square_is_not_transposed():
    """A width/height swap would make every cell the wrong shape."""
    assert imagesize.dimensions(_encode("JPEG", size=(200, 50))) == (200, 50)
    assert imagesize.dimensions(_encode("PNG", size=(50, 200))) == (50, 200)


def test_unknown_format_returns_zero():
    assert imagesize.dimensions(b"not an image at all") == (0, 0)


def test_truncated_header_returns_zero():
    """A partial upload must not raise — it would break the request."""
    assert imagesize.dimensions(_encode("PNG")[:10]) == (0, 0)


def test_empty_input_returns_zero():
    assert imagesize.dimensions(b"") == (0, 0)
