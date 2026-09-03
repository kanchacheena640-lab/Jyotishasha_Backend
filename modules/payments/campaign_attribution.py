# modules/payments/campaign_attribution.py

"""
Task 10A -- minimal, safe financial-conversion campaign attribution
propagation for browser-originated REPORT_PURCHASE transactions.

Campaign attribution is CONTEXT, never financial truth -- nothing in
this module ever touches amount/currency/order ownership/entitlement/
report completion. Its only job: let a browser-originated commercial
transaction carry its Task 2C first-touch campaign snapshot through to
the authoritative payment_verified/payment_failed event, WITHOUT
trusting whatever the browser resends at verification time.

ARCHITECTURE (forensically confirmed, not assumed): app.py's
/api/razorpay-order already forwards name/email/dob/tob/pob/product/
partner into Razorpay's own `notes` field at order-creation time
specifically so the server-to-server payment.captured webhook (the
recovery path, when the browser never calls back) can reconstruct the
Order even without the browser. This is an EXISTING, already-durable,
already-provider-persisted, transaction-owned metadata mechanism --
this module extends that SAME mechanism to carry campaign attribution
too, rather than adding a new database column/migration (none of
Order/ProcessedPayment has an existing JSON field suitable for this --
Order.partner_payload is a different, unrelated concept -- a partner's
own birth-detail JSON for compatibility reports -- and reusing it would
conflate two unrelated things).

Flow:
    browser (Task 2C immutable snapshot)
      -> POST /api/razorpay-order { ..., campaign_context? }
      -> sanitize_campaign_attribution_snapshot() (reuses, never forks,
         the same modules.activity_events.event_schemas.sanitize_
         campaign_context() the rest of this codebase already uses)
      -> build_razorpay_notes_fields() -> merged into Razorpay's own
         order.notes (durable, provider-side, survives redirects/
         retries/webhook delivery/browser loss)
      -> POST /webhook (Case A: notes arrive for free in the
         payment.captured event payload; Case B: RazorpayProvider.
         fetch_order_campaign_context() reads them back via one
         Razorpay API call)
      -> extract_campaign_context_from_notes() -> PaymentRequest.
         campaign_context -> PaymentService._emit_payment_event()
         -> record_event(campaign_context=...)

Never accepts amount/currency/gclid/fbclid/_fbc/_fbp/PII from this
snapshot -- see ATTRIBUTION_SNAPSHOT_FIELDS' own closed vocabulary.
"""

from __future__ import annotations

from typing import Dict, Optional

from modules.activity_events.event_schemas import sanitize_campaign_context

# Task 10A S5 -- the exact, minimal, frozen snapshot vocabulary.
# utm_source/utm_medium/utm_campaign always; referrer is included
# because it is already privacy-reviewed (origin+path only, never
# query/fragment/credentials -- modules/activity_events/
# anonymous_ingestion_service._normalize_referrer() and lib/
# analyticsAttribution.ts's normalizeReferrer() both already enforce
# this) and already accepted into activity_events' own campaign_context
# today -- no new privacy surface. The schema-only-unused bare "medium"
# key is deliberately excluded even though sanitize_campaign_context()
# would technically allow it (Task 10's own audit finding: no current
# producer ever populates it) -- Task 10A S5's explicit instruction.
ATTRIBUTION_SNAPSHOT_FIELDS = ("utm_source", "utm_medium", "utm_campaign", "referrer")

# Matches the existing per-value bound app.py's /api/razorpay-order
# already applies to name/email/dob/tob/pob/language when building
# Razorpay notes (str(value)[:256]) -- same convention, not a new one.
MAX_NOTE_VALUE_LENGTH = 256


def sanitize_campaign_attribution_snapshot(raw: Optional[dict]) -> Dict[str, str]:
    """Pure. Reuses the SAME, unmodified campaign_context sanitizer
    every other campaign_context boundary in this codebase already uses
    (modules.activity_events.event_schemas.sanitize_campaign_context) --
    never a second, incompatible sanitizer (Task 10A S6). Narrows the
    result further to ATTRIBUTION_SNAPSHOT_FIELDS only. Returns {}
    (never None, never raises) for missing/malformed/empty/entirely-
    invalid input -- an invalid campaign_context must never block a
    purchase (Task 10A S8)."""
    if not isinstance(raw, dict):
        return {}
    clean, _dropped = sanitize_campaign_context(raw)
    return {k: v for k, v in clean.items() if k in ATTRIBUTION_SNAPSHOT_FIELDS}


def build_razorpay_notes_fields(campaign_context: Dict[str, str]) -> Dict[str, str]:
    """Converts an already-sanitized campaign_context dict into the flat
    string key/value shape Razorpay's own `notes` field requires -- same
    per-value 256-char bound already used for name/email/dob elsewhere
    in app.py's /api/razorpay-order. Returns {} for an empty/falsy
    input; every value is coerced to a bounded string, matching the
    existing forwarding convention exactly."""
    return {k: str(v)[:MAX_NOTE_VALUE_LENGTH] for k, v in (campaign_context or {}).items() if v}


def extract_campaign_context_from_notes(notes: Optional[dict]) -> Optional[Dict[str, str]]:
    """The reverse of build_razorpay_notes_fields() -- pulls the
    attribution snapshot back out of a Razorpay order/payment's own
    `notes` dict (the durable transaction snapshot -- Task 10A S3/S13,
    NOT a fresh browser claim). Runs the SAME sanitizer again (defense-
    in-depth against a tampered or legacy notes value) before returning.
    Returns None (never {}) when nothing usable is present -- callers
    must treat that as 'no attribution recorded for this transaction',
    NEVER as source='direct' (Task 10A S8/S21, Task 10's own frozen
    DIRECT_TRAFFIC_LIMITATION)."""
    if not notes:
        return None
    candidate = {k: notes.get(k) for k in ATTRIBUTION_SNAPSHOT_FIELDS if notes.get(k)}
    snapshot = sanitize_campaign_attribution_snapshot(candidate)
    return snapshot or None
