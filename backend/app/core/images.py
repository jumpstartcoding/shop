"""Validating images that arrive as data URLs (drawn signatures, the shop logo).

Images are decoded with Pillow and re-encoded as fresh PNGs, so whatever was uploaded is
never stored or served as-is.
"""

import base64
import binascii
import io

from app.core.errors import AppError

_PREFIXES = {"data:image/png;base64,": "png", "data:image/jpeg;base64,": "jpeg"}


class BadImage(AppError):
    status_code = 422
    code = "bad_image"


def decode_data_url(data_url: str, *, max_bytes: int, allow_jpeg: bool = False) -> bytes:
    prefix = next((p for p in _PREFIXES if data_url.startswith(p)), None)
    if prefix is None or (_PREFIXES[prefix] == "jpeg" and not allow_jpeg):
        raise BadImage("The image must be a PNG" + (" or JPEG." if allow_jpeg else "."))
    payload = data_url[len(prefix) :]
    if len(payload) > max_bytes * 4 // 3 + 4:
        raise BadImage("That image is too large.")
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BadImage("The image couldn't be read.") from exc


def clean_png(
    raw: bytes, *, max_side: int, min_side: int = 1, flatten_white: bool = False
) -> bytes:
    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(raw))
        if img.width * img.height > 25_000_000:
            raise BadImage("That image is too large.")
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise BadImage("The image couldn't be read.") from exc
    if img.width < min_side or img.height < min_side:
        raise BadImage("The image is too small.")
    img = img.convert("RGBA")
    img.thumbnail((max_side, max_side))
    if flatten_white:
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.alpha_composite(img)
        img = bg.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def has_ink(png: bytes, *, min_dark_pixels: int = 150) -> bool:
    """A drawn signature should contain some strokes, not be a blank canvas."""
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("L")
    hist = img.histogram()
    return sum(hist[:160]) >= min_dark_pixels
