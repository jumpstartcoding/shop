"""Turning an uploaded picture into the two JPEGs the app stores.

Phones already shrink photos before upload (see frontend/src/lib/photos.ts), but the server
never trusts that: every upload is decoded with Pillow, rotated upright from its EXIF
orientation, flattened to RGB, resized, and re-encoded. Re-encoding drops all metadata, so a
photo taken in the bay never carries the phone's GPS position to a customer.
"""

import io
from dataclasses import dataclass

from app.core.images import BadImage

ACCEPTED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_BYTES = 4_000_000  # Lambda request limit is 6 MB; this leaves room for encoding
MAX_PIXELS = 50_000_000
FULL_SIDE = 1600
THUMB_SIDE = 480


@dataclass
class ProcessedPhoto:
    full: bytes
    thumb: bytes
    width: int
    height: int


def process_photo(raw: bytes, content_type: str | None) -> ProcessedPhoto:
    from PIL import Image, ImageOps, UnidentifiedImageError

    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype not in ACCEPTED_TYPES:
        raise BadImage(
            "Photos must be JPEG, PNG, or WebP. On an iPhone, take the photo with the "
            "Add photo button so it's converted automatically."
        )
    if not raw:
        raise BadImage("The photo was empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BadImage("That photo is too large (over 4 MB). Try taking it again.")
    try:
        img = Image.open(io.BytesIO(raw))
        if img.width * img.height > MAX_PIXELS:
            raise BadImage("That photo has too many pixels.")
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise BadImage("That file isn't a photo the app can read.") from exc
    if min(img.width, img.height) < 32:
        raise BadImage("That photo is too small.")

    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        img = background
    else:
        img = img.convert("RGB")

    full = img.copy()
    full.thumbnail((FULL_SIDE, FULL_SIDE), Image.Resampling.LANCZOS)
    thumb = img.copy()
    thumb.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    return ProcessedPhoto(
        full=_jpeg(full, 82),
        thumb=_jpeg(thumb, 76),
        width=full.width,
        height=full.height,
    )


def _jpeg(img, quality: int) -> bytes:
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()
