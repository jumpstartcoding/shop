"""Server-side PDFs with WeasyPrint (HTML + CSS -> PDF). No browser screenshots.

Fonts are bundled (Barlow, SIL OFL) so documents look the same on a laptop and on Lambda.
"""

import base64
import hashlib
import logging
import sys
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.errors import AppError
from app.core.storage import get_storage

HERE = Path(__file__).parent
# WeasyPrint warns about its font-subsetting fallback on every render; it isn't actionable.
log = structlog.get_logger()
logging.getLogger("weasyprint").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)
METHOD_LABEL = {
    "cash": "Cash",
    "check": "Check",
    "card": "Card",
    "online": "Online payment",
    "other": "Other",
}


def _money(cents: int | None) -> str:
    cents = cents or 0
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _date(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        value = datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)
    return value.strftime("%b %-d, %Y")


def _datetime(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime("%b %-d, %Y at %-I:%M %p %Z").strip()


def _qty(value) -> str:
    s = str(value)
    return s.rstrip("0").rstrip(".") if "." in s else s


@lru_cache
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(HERE / "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        money=_money,
        date=_date,
        datetime=_datetime,
        qty=_qty,
        method=lambda m: METHOD_LABEL.get(m, m),
    )
    return env


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def render_html(snapshot: dict, signature: dict | None = None) -> str:
    storage = get_storage()
    logo = None
    if snapshot.get("business", {}).get("logo_key"):
        try:
            logo = _data_uri(storage.get(snapshot["business"]["logo_key"]), "image/png")
        except Exception:  # a missing logo must never block a document
            logo = None

    def photo(p: dict) -> str | None:
        """Photos are embedded from their thumbnails (480 px, plenty for print)."""
        try:
            return _data_uri(storage.get(p["thumb_key"]), "image/jpeg")
        except Exception:
            return None

    template = {"receipt": "receipt.html", "history": "history.html"}.get(
        snapshot["doc_type"], "document.html"
    )
    return (
        _env()
        .get_template(template)
        .render(
            doc=snapshot,
            signature=signature,
            logo=logo,
            photo=photo,
            fonts=(HERE / "fonts").as_uri(),
        )
    )


def _weasyprint_html():
    """WeasyPrint loads Pango and GObject from the operating system when first imported. If
    they're missing, fail with a message that says what to install instead of a bare 500."""
    try:
        from weasyprint import HTML
    except OSError as exc:
        if sys.platform == "darwin":
            fix = (
                "On a Mac: run `brew install pango`, then start the server with "
                "`export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` set in the same terminal."
            )
        else:
            fix = "On Debian/Ubuntu: `apt install libpango-1.0-0 libpangoft2-1.0-0`."
        log.error("pdf_engine_unavailable", error=str(exc))
        raise AppError(
            "PDFs can't be made on this computer because WeasyPrint's text libraries "
            f"(Pango) weren't found. Nothing was sent or saved. {fix}",
            status_code=503,
            code="pdf_unavailable",
        ) from exc
    return HTML


def render_pdf(snapshot: dict, signature: dict | None = None) -> bytes:
    HTML = _weasyprint_html()  # noqa: N806

    html = render_html(snapshot, signature)
    return HTML(string=html, base_url=str(HERE)).write_pdf()


def signature_block(auth, content_sha256: str, signature_png: bytes | None) -> dict:
    """What the signed PDF prints about the signer. Built from the stored authorization."""
    return {
        "decision": auth.decision,
        "method": auth.method,
        "signer_name": auth.signer_name,
        "typed_name": auth.typed_name,
        "image": _data_uri(signature_png, "image/png") if signature_png else None,
        "signed_at": auth.signed_at,
        "statement": auth.statement,
        "content_sha256": content_sha256,
        "authorization_id": auth.id,
        "note": auth.note,
    }


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
