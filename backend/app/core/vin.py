"""Optional VIN lookup through the free NHTSA vPIC service (spec §30).

No key, no cost. The app never depends on it: if it's slow or down, the mechanic types the
details. Only the VIN is sent.
"""

import json
import urllib.request
from collections.abc import Callable

from app.core.errors import AppError

VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
TIMEOUT_SECONDS = 6


class VinLookupUnavailable(AppError):
    status_code = 503
    code = "vin_lookup_unavailable"


def _fetch(url: str) -> dict:
    if not url.startswith("https://vpic.nhtsa.dot.gov/"):
        raise ValueError("unexpected VIN service URL")
    req = urllib.request.Request(url, headers={"User-Agent": "shop-app/1.0"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:  # noqa: S310 - fixed https URL
        return json.loads(r.read())


_fetcher: Callable[[str], dict] = _fetch


def set_fetcher(fn: Callable[[str], dict] | None) -> None:
    """Tests swap in a fake."""
    global _fetcher
    _fetcher = fn or _fetch


def _clean(v) -> str | None:
    v = (v or "").strip()
    return v if v and v.lower() not in ("not applicable", "null", "0") else None


def decode(vin: str) -> dict:
    try:
        data = _fetcher(VPIC_URL.format(vin=vin))
        r = data["Results"][0]
    except Exception as exc:
        raise VinLookupUnavailable(
            "VIN lookup isn't available right now. Enter the vehicle details by hand."
        ) from exc

    year = _clean(r.get("ModelYear"))
    make = _clean(r.get("Make"))
    if not (year or make):
        raise AppError(
            "No vehicle was found for that VIN. Check it for typos, or enter the details by hand.",
            status_code=404,
            code="vin_not_found",
        )
    displacement = _clean(r.get("DisplacementL"))
    cylinders = _clean(r.get("EngineCylinders"))
    engine_parts = []
    if displacement:
        try:
            engine_parts.append(f"{float(displacement):.1f}L")
        except ValueError:
            engine_parts.append(displacement)
    if cylinders:
        engine_parts.append(f"{cylinders}-cyl")
    if _clean(r.get("FuelTypePrimary")) and r["FuelTypePrimary"].lower() != "gasoline":
        engine_parts.append(r["FuelTypePrimary"].strip().lower())
    transmission = " ".join(
        p
        for p in [
            _clean(r.get("TransmissionStyle")),
            _clean(r.get("TransmissionSpeeds")) and f"{r['TransmissionSpeeds'].strip()}-speed",
        ]
        if p
    )
    error_code = (_clean(r.get("ErrorCode")) or "0").split(",")[0].strip()
    return {
        "vin": vin,
        "year": int(year) if year and year.isdigit() else None,
        "make": make.title() if make and make.isupper() and len(make) > 3 else make,
        "model": _clean(r.get("Model")),
        "trim": _clean(r.get("Trim")) or _clean(r.get("Series")),
        "engine": " ".join(engine_parts) or None,
        "transmission": transmission or None,
        "body": _clean(r.get("BodyClass")),
        # vPIC answers with a partial decode and a warning when the check digit is off.
        "warning": _clean(r.get("ErrorText")) if error_code not in ("0", "") else None,
    }
