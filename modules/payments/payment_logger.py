# modules/payments/payment_logger.py

"""
Structured logging for the payment lifecycle -- Payment Hardening
Phase 4, masked in Subscription Purchase System S16. Every entry is a
single-line JSON object via the standard `logging` module (no new
dependency), so it's both grep-able by a human and parseable by any
log aggregator without extra configuration.

This module owns exactly two things:
    new_correlation_id() -- one id per process_payment() call, so
                             every log line for a single payment
                             attempt can be traced together.
    log_payment_event()  -- the only place a payment-related log line
                             is built, so every entry has the same
                             shape (timestamp, correlation_id, event,
                             status, provider, product,
                             razorpay_order_id, razorpay_payment_id,
                             email, order_id, error).

Nothing here changes any business decision -- it is a pure side
effect, called from modules/payments/payment_service.py at each stage
of process_payment().

Masking (S16, S13 audit findings H-3/H-4): razorpay_order_id and
razorpay_payment_id carry a real payment/transaction identifier for
whichever provider is involved -- for GOOGLE_PLAY specifically, that is
the Google Play purchase_token (a long-lived, replayable, credential-
like value usable against Google's own APIs) or a provider order id.
This is the one place every one of those values passes through before
becoming a log line, so masking here protects every caller
(payment_service.py's own internal logging, and
routes_google_purchase_confirm.py) without needing to change any of
them individually. Only the first 6 characters and a length marker
are ever written -- enough for a human to spot "the same identifier
reappeared across these log lines" without the log itself ever holding
a complete, replayable value. This is a pure logging-output change;
nothing about what gets passed IN to this function, or any business
decision anywhere else, is affected.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger("payments")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

_MASK_VISIBLE_PREFIX = 6


def _mask_identifier(value: Optional[str]) -> Optional[str]:
    """Never let a complete purchase token / transaction identifier
    reach a log line. Keeps only a short, non-reconstructable prefix
    plus a length marker -- enough to correlate repeated appearances
    of the same identifier across log lines, never enough to replay
    or reconstruct it. None/empty pass through unchanged (nothing to
    mask)."""
    if not value:
        return value
    text = str(value)
    if len(text) <= _MASK_VISIBLE_PREFIX:
        return "*" * len(text)
    return f"{text[:_MASK_VISIBLE_PREFIX]}...(masked,len={len(text)})"


def new_correlation_id() -> str:
    """One id per payment attempt, threaded through every log line for
    that attempt so they can be correlated together."""
    return uuid.uuid4().hex


def log_payment_event(
    event: str,
    *,
    correlation_id: str,
    status: str,
    provider: Optional[str] = None,
    product: Optional[str] = None,
    razorpay_order_id: Optional[str] = None,
    razorpay_payment_id: Optional[str] = None,
    email: Optional[str] = None,
    order_id: Optional[int] = None,
    error: Optional[str] = None,
    exc_info: bool = False,
) -> None:
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "correlation_id": correlation_id,
        "event": event,
        "status": status,
        "provider": provider,
        "product": product,
        "razorpay_order_id": _mask_identifier(razorpay_order_id),
        "razorpay_payment_id": _mask_identifier(razorpay_payment_id),
        "email": email,
        "order_id": order_id,
        "error": error,
    }
    line = json.dumps(record, default=str)

    if error is not None or exc_info:
        logger.error(line, exc_info=exc_info)
    else:
        logger.info(line)
