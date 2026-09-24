# modules/payments/order_attribution.py

"""
Reports Ads P0.1 -- sanitize and persist advertising attribution against
the INTERNAL Order (models.OrderAttribution, table order_attributions).

Wire contract (POST /api/razorpay-order, optional top-level `attribution`
object, built by jyotishasha-frontend/lib/adAttribution.ts):

    {
      "attribution_type": "latest_click" | "first_touch" | "none",
      "utm_source": ..., "utm_medium": ..., "utm_campaign": ...,
      "utm_content": ..., "utm_term": ...,
      "gclid": ..., "gbraid": ..., "wbraid": ..., "fbclid": ...,
      "landing_page": "/path", "referrer": "https://host/path",
      "first_touch": { ...same keys, no attribution_type... },
      "consent": {"geo_policy": "NORMAL", "analytics": true|false|null,
                  "advertising": true|false|null}
    }

RULES
  * Everything is optional. Absent / not-a-dict `attribution` -> no row,
    nothing happens (an older client, or a direct request). A present
    object always yields a row, even with no campaign fields
    (attribution_type "none"), so "captured, nothing found" is
    distinguishable from "nothing sent".
  * Allowlist only: unknown keys are ignored. No name/email/phone/birth
    data can enter -- no such column exists and no such key is read.
  * Never trusted: every value is re-validated here regardless of what the
    browser already did. Non-strings are ignored; control characters are
    stripped; values containing "@" (email-shaped) are dropped; free text
    is truncated to MAX_VALUE_LENGTH; click identifiers must match a strict
    charset and are DROPPED, never truncated (a truncated click id is a
    corrupt one); landing_page is reduced to a bare path; referrer must be
    http(s) and is reduced to origin + path (no query, fragment, userinfo).
  * Best-effort by design: record_order_attribution() never raises and
    never touches the payment path. Missing/invalid attribution can never
    fail an order.
  * 1:1 with the Order (UNIQUE order_id): the first write wins; a repeat
    call for the same order is a no-op.

Relationship to the existing campaign_context (modules/payments/
campaign_attribution.py): UNCHANGED. campaign_context still travels in
Razorpay notes and lands on the payment_verified ledger event. That is a
deliberate, temporary duplication of utm_source/medium/campaign/referrer
for P0.1 (minimum regression risk); a later phase can read attribution
from this table instead and retire the notes path.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from extensions import db
from models import OrderAttribution

_logger = logging.getLogger(__name__)

MAX_VALUE_LENGTH = 256

ATTRIBUTION_TYPES = frozenset({"latest_click", "first_touch", "none"})
GEO_POLICIES = frozenset({"NORMAL", "US_PRIVACY", "EUROPE_CONSENT", "SAFE_FALLBACK"})

TEXT_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
CLICK_ID_FIELDS = ("gclid", "gbraid", "wbraid", "fbclid")
SIGNAL_FIELDS = TEXT_FIELDS + CLICK_ID_FIELDS

_CLICK_ID_RE = re.compile(r"^[A-Za-z0-9_\-.]{1,256}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _clean_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = _CONTROL_RE.sub("", value).strip()
    if not cleaned or "@" in cleaned:
        return None
    return cleaned[:MAX_VALUE_LENGTH]


def _clean_click_id(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if _CLICK_ID_RE.match(stripped) else None


def _clean_landing_page(value: Any) -> Optional[str]:
    text = _clean_text(value)
    if not text or not text.startswith("/") or text.startswith("//"):
        return None
    return text.split("?", 1)[0].split("#", 1)[0][:MAX_VALUE_LENGTH] or None


def _clean_referrer(value: Any) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}{parts.path}"[:MAX_VALUE_LENGTH]


def _clean_touch(raw: Any) -> Dict[str, str]:
    """One touch's allowlisted, sanitized fields (only those present)."""
    if not isinstance(raw, dict):
        return {}
    touch: Dict[str, str] = {}
    for key in TEXT_FIELDS:
        v = _clean_text(raw.get(key))
        if v:
            touch[key] = v
    for key in CLICK_ID_FIELDS:
        v = _clean_click_id(raw.get(key))
        if v:
            touch[key] = v
    landing = _clean_landing_page(raw.get("landing_page"))
    if landing:
        touch["landing_page"] = landing
    referrer = _clean_referrer(raw.get("referrer"))
    if referrer:
        touch["referrer"] = referrer
    return touch


def _has_signal(touch: Dict[str, str]) -> bool:
    return any(k in touch for k in SIGNAL_FIELDS)


def sanitize_order_attribution(raw: Any) -> Optional[Dict[str, Any]]:
    """Pure. None when `raw` is not a dict (nothing to persist); otherwise
    the exact column values for a OrderAttribution row."""
    if not isinstance(raw, dict):
        return None

    touch = _clean_touch(raw)

    declared = raw.get("attribution_type")
    if declared in ATTRIBUTION_TYPES:
        attribution_type = declared
    else:
        attribution_type = "first_touch" if _has_signal(touch) else "none"
    # A claimed click/first-touch with no signal at all is not one.
    if attribution_type != "none" and not _has_signal(touch):
        attribution_type = "none"

    first_touch = _clean_touch(raw.get("first_touch"))

    consent = raw.get("consent") if isinstance(raw.get("consent"), dict) else {}
    policy = consent.get("geo_policy")

    values: Dict[str, Any] = {
        "attribution_type": attribution_type,
        "first_touch": first_touch or None,
        "consent_geo_policy": policy if policy in GEO_POLICIES else None,
        "consent_analytics": consent.get("analytics") if isinstance(consent.get("analytics"), bool) else None,
        "consent_advertising": consent.get("advertising") if isinstance(consent.get("advertising"), bool) else None,
    }
    for key in SIGNAL_FIELDS + ("landing_page", "referrer"):
        values[key] = touch.get(key)
    return values


def record_order_attribution(order_id: int, raw: Any) -> Optional[OrderAttribution]:
    """Persist attribution for an already-committed internal Order.
    Never raises; returns the row, or None if nothing was persisted."""
    try:
        values = sanitize_order_attribution(raw)
        if values is None:
            return None
        existing = OrderAttribution.query.filter_by(order_id=order_id).first()
        if existing is not None:
            return existing
        row = OrderAttribution(order_id=order_id, **values)
        db.session.add(row)
        db.session.commit()
        return row
    except Exception:
        db.session.rollback()
        _logger.warning(
            "order_attribution: could not persist attribution for Order.id=%s "
            "(swallowed -- the order and payment are unaffected)",
            order_id, exc_info=True,
        )
        return None
