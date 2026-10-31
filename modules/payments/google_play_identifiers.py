# modules/payments/google_play_identifiers.py

"""
Google Play identifiers that are safe to send to the Android Publisher API.

A purchase token is both the Google API path segment that is verified AND
the payment ledger's identity (ProcessedPayment.payment_id, ChatPack's
razorpay_payment_id). Those two must be the exact same string. A client
value such as "TOKEN#1", "TOKEN?x" or "a/../TOKEN" is a different ledger
key but, once turned into a URL, verifies the same (or another) purchase --
so one purchase could be redeemed again and again. Every Google-bound
identifier is therefore checked here BEFORE any API call:

- purchase token: only RFC 3986 unreserved characters (A-Z a-z 0-9 . _ ~ -),
  which is what Google Play tokens are made of, with at least one letter or
  digit (so "." / ".." can never be a dot-segment), at most 255 characters
  (the ledger column width). Nothing is trimmed, decoded or rewritten: the
  value that passes is byte-for-byte the value verified and stored.
- product id: Google Play's own product-id rule -- lowercase letters, digits,
  "_" and ".", starting with a letter or digit, at most 139 characters.

path_segment() percent-encodes a value for use as ONE path segment; for a
value that passed the checks above it is the identity, so the URL Google
sees carries exactly the stored string.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

MAX_PURCHASE_TOKEN_LENGTH = 255  # models_processed_payments.ProcessedPayment.payment_id

_PURCHASE_TOKEN = re.compile(r"[A-Za-z0-9._~-]+")
_ALPHANUMERIC = re.compile(r"[A-Za-z0-9]")
_PRODUCT_ID = re.compile(r"[a-z0-9][a-z0-9._]{0,138}")


def is_valid_purchase_token(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_PURCHASE_TOKEN_LENGTH
        and _PURCHASE_TOKEN.fullmatch(value) is not None
        and _ALPHANUMERIC.search(value) is not None
    )


def is_valid_product_id(value: Any) -> bool:
    return isinstance(value, str) and _PRODUCT_ID.fullmatch(value) is not None


def path_segment(value: str) -> str:
    """Percent-encode `value` as a single URL path segment ("/" included)."""
    return quote(value, safe="")
