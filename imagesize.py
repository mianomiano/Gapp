"""Read an image's pixel size from its header bytes.

Only the four formats the uploader accepts (PNG, JPEG, GIF, WebP), and only
enough of each header to find the dimensions — so the app keeps its "nothing
to install" promise instead of depending on Pillow for two integers.

Videos are not covered: their dimensions need a real demuxer. They return
(0, 0), and the client falls back to measuring the element once it loads,
exactly as it did for everything before this existed.
"""
import struct


def dimensions(data: bytes):
    """(width, height), or (0, 0) if the format is unknown or the header is
    truncated. Never raises — a bad upload must not break the request."""
    try:
        for reader in (_png, _gif, _webp, _jpeg):
            size = reader(data)
            if size:
                return size
    except (struct.error, IndexError, ValueError):
        pass
    return (0, 0)


def _png(data):
    # 8-byte signature, then an IHDR chunk whose payload starts with w/h.
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _gif(data):
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    return struct.unpack("<HH", data[6:10])


def _webp(data):
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    kind = data[12:16]
    if kind == b"VP8 ":              # lossy
        return struct.unpack("<HH", data[26:30])
    if kind == b"VP8L":              # lossless: 14 bits each, packed
        bits = int.from_bytes(data[21:25], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if kind == b"VP8X":              # extended: 24-bit values, minus one
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return (w, h)
    return None


def _jpeg(data):
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # SOF0-SOF15 carry the frame size; C4/C8/CC are not frame headers.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return (width, height)
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2                   # standalone marker, no payload
            continue
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None
