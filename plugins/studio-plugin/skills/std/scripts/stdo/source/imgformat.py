"""What an image file is, by its bytes (m1-plan §6.1, S12): PNG, or JPEG with a frame header (SOF C0–CF except C4 · C8
· CC). WebP, AVIF, GIF and SVG are recognized and refused (s2v renders PNG and JPEG). Also the pixel size."""

import struct

PNG_SIG = b"\x89PNG\r\n\x1a\n"
SOF = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
NO_LENGTH = set(range(0xD0, 0xD8)) | {0x01, 0xD8}
EXTENSIONS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".jpe": "jpeg", ".webp": "webp", ".avif": "avif",
              ".gif": "gif", ".svg": "svg"}
USABLE = ("png", "jpeg")


def _jpeg(d):
    """(width, height) of a JPEG's frame, or None (no frame header before the scan, or a broken file)."""
    i, n = 2, len(d)
    while i < n:
        if d[i] != 0xFF:
            return None
        while i < n and d[i] == 0xFF:
            i += 1
        if i >= n:
            return None
        m = d[i]
        i += 1
        if m in NO_LENGTH:
            continue
        if m in (0xD9, 0xDA):
            return None  # the end, or the scan, before any frame header
        if i + 2 > n:
            return None
        length = (d[i] << 8) | d[i + 1]
        if length < 2:
            return None
        if m in SOF:
            if i + 7 > n:
                return None
            h, w = struct.unpack(">HH", d[i + 3:i + 7])
            return w, h
        i += length
    return None


def detect(data):
    """(format, width, height): format is png · jpeg · webp · avif · gif · svg · unknown."""
    if data.startswith(PNG_SIG) and len(data) >= 24 and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data.startswith(b"\xff\xd8"):
        size = _jpeg(data)
        return ("jpeg",) + size if size else ("unknown", None, None)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", None, None
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "avif", None, None
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", None, None
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return "svg", None, None
    return "unknown", None, None


def extension_format(path):
    import os
    return EXTENSIONS.get(os.path.splitext(path)[1].lower())
