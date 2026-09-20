"""Screenshot capture -- the last observation tier, on explicit calls only.

Only `inspect_screen` / `inspect_region` reach this module; nothing here runs on
a timer or in the background, so the bridge never continuously samples the
screen. Images are fitted to the protocol's base64 budget by downscaling first
and only then trading format/quality, since a smaller true-colour image reads
better than a heavily compressed full-size one.
"""

from __future__ import annotations

import base64
import io
from typing import Optional

from .errors import backend_unavailable

try:
    import mss
    from PIL import Image
except ImportError:  # pragma: no cover - requires mss/Pillow
    mss = None
    Image = None

# contracts.md caps images at 2 MB base64; the schema allows 2.8 MB. Staying
# under the documented figure leaves room for the rest of the JSON frame.
MAX_BASE64_CHARS = 2_000_000
MIN_DIMENSION = 320


def capture(bounds: Optional[dict] = None) -> dict:
    """Returns a schema-shaped Image object for the screen or a region."""
    if mss is None or Image is None:
        raise backend_unavailable("mss/Pillow are not installed; screen capture is unavailable")

    with mss.mss() as sct:
        if bounds is not None:
            monitor = {
                "left": int(bounds["x"]),
                "top": int(bounds["y"]),
                "width": max(1, int(bounds["width"])),
                "height": max(1, int(bounds["height"])),
            }
        else:
            monitor = sct.monitors[0]  # index 0 is the union of all displays
        raw = sct.grab(monitor)

    image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    mime, data = _encode_within_budget(image)
    result = {"mime_type": mime, "data": data, "scope": "region" if bounds is not None else "screen"}
    if bounds is not None:
        result["bounds"] = {
            "x": float(bounds["x"]),
            "y": float(bounds["y"]),
            "width": float(bounds["width"]),
            "height": float(bounds["height"]),
        }
    return result


def _encode_within_budget(image) -> tuple[str, str]:
    candidate = image
    for _ in range(6):
        encoded = _encode(candidate, "PNG")
        if len(encoded) <= MAX_BASE64_CHARS:
            return "image/png", encoded
        if min(candidate.size) <= MIN_DIMENSION:
            break
        candidate = candidate.resize(
            (max(MIN_DIMENSION, int(candidate.width * 0.75)), max(1, int(candidate.height * 0.75))),
            Image.LANCZOS,
        )

    for quality in (85, 70, 55, 40):
        encoded = _encode(candidate, "JPEG", quality=quality)
        if len(encoded) <= MAX_BASE64_CHARS:
            return "image/jpeg", encoded

    raise backend_unavailable("Captured image could not be reduced below the protocol size limit")


def _encode(image, fmt: str, **options) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
