"""Turning uploaded files into a post's snippet columns.

The admin panel's three textareas are for editing by hand. This is the other
way in: hand it the files you already have — a .html, a .css, a .js, or one
.zip containing them — and it fills the same three columns.

A .zip is the interesting case, because it is the shape most component
downloads arrive in. Only the first file of each kind is taken; a bundle with
five stylesheets is ambiguous and guessing which one matters would be worse
than the admin choosing.
"""
import io
import zipfile

# Extension -> the column it fills.
FIELD_FOR_EXT = {
    "html": "snippet_html",
    "htm": "snippet_html",
    "css": "snippet_css",
    "js": "snippet_js",
}

# A snippet is source code pasted into a database column, not an asset. Well
# past anything hand-written, and small enough that a runaway file cannot fill
# the disk one save at a time.
MAX_FIELD_BYTES = 512 * 1024

# Decompression limits. A zip can claim to be 2 KB and expand to gigabytes, so
# the budget is checked against the declared sizes before anything is read.
MAX_ZIP_MEMBERS = 200
MAX_ZIP_TOTAL_BYTES = 4 * 1024 * 1024


class SnippetError(ValueError):
    """The upload could not be used. The message is shown to the admin."""


def _ext(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _decode(raw, source):
    """Source files are text. UTF-8, then Latin-1 so an oddly-encoded file
    still lands as something editable rather than being rejected outright."""
    if len(raw) > MAX_FIELD_BYTES:
        raise SnippetError(f"{source} is larger than {MAX_FIELD_BYTES // 1024} KB.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def from_zip(raw):
    """Pull the first html / css / js member out of an archive."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise SnippetError(f"Not a readable .zip: {exc}") from exc

    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > MAX_ZIP_MEMBERS:
            raise SnippetError(f"Archive has more than {MAX_ZIP_MEMBERS} files.")
        # Declared sizes, checked before reading a single byte.
        if sum(info.file_size for info in members) > MAX_ZIP_TOTAL_BYTES:
            raise SnippetError("Archive expands to more than "
                              f"{MAX_ZIP_TOTAL_BYTES // (1024 * 1024)} MB.")

        found = {}
        # Sorted so the result does not depend on how the zip was written, and
        # so a top-level index.html beats one nested in a subfolder.
        for info in sorted(members, key=lambda i: (i.filename.count("/"), i.filename)):
            field = FIELD_FOR_EXT.get(_ext(info.filename))
            if not field or field in found:
                continue
            found[field] = _decode(archive.read(info), info.filename)

    if not found:
        raise SnippetError("No .html, .css or .js file inside the archive.")
    return found


def from_uploads(uploads):
    """Fields from a list of (filename, bytes) pairs.

    A .zip is expanded; anything else is matched on its extension. Later files
    of the same kind win, so re-picking one file in the browser replaces it
    rather than being silently ignored.
    """
    fields = {}
    for name, raw in uploads:
        if not name or not raw:
            continue
        extension = _ext(name)
        if extension == "zip":
            fields.update(from_zip(raw))
            continue
        field = FIELD_FOR_EXT.get(extension)
        if not field:
            raise SnippetError(
                f"{name}: expected .html, .css, .js or .zip.")
        fields[field] = _decode(raw, name)
    return fields
