"""Signed, emailed review links (F10-P15).

A review token proves "whoever holds this was sent the delivery email for order
N". It is an itsdangerous signature over the order id plus a short hash of the
order's email, keyed by REVIEW_LINK_SECRET -- a dedicated secret with NO
fallback: when it is missing or too short, tokens can be neither issued nor
accepted (fail closed), so a default/weak key can never mint valid links.
Binding the email hash means a token stops working if the order's email is
changed. The raw email is never inside the token.
"""
from __future__ import annotations

import hashlib
import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

TOKEN_SALT = "jyotishasha.report-review.v1"
TOKEN_MAX_AGE_SECONDS = 365 * 24 * 3600
MIN_SECRET_LENGTH = 32


class ReviewTokenError(Exception):
    """Raised for any unusable token; `.code` is safe to return to clients."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _secret() -> str | None:
    secret = os.getenv("REVIEW_LINK_SECRET", "")
    return secret if len(secret) >= MIN_SECRET_LENGTH else None


def review_links_enabled() -> bool:
    return _secret() is not None


def _email_hash(email: str) -> str:
    return hashlib.sha256((email or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def _serializer() -> URLSafeTimedSerializer:
    secret = _secret()
    if secret is None:
        raise ReviewTokenError("reviews_disabled")
    return URLSafeTimedSerializer(secret, salt=TOKEN_SALT, signer_kwargs={"digest_method": hashlib.sha256})


def issue_review_token(order_id: int, email: str) -> str:
    return _serializer().dumps({"o": int(order_id), "e": _email_hash(email)})


def read_review_token(token: str) -> tuple[int, str]:
    """Return (order_id, email_hash) or raise ReviewTokenError."""
    if not token or not isinstance(token, str) or len(token) > 512:
        raise ReviewTokenError("invalid_token")
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired:
        raise ReviewTokenError("expired_token")
    except BadSignature:
        raise ReviewTokenError("invalid_token")
    if not isinstance(data, dict) or not isinstance(data.get("o"), int) or not isinstance(data.get("e"), str):
        raise ReviewTokenError("invalid_token")
    return data["o"], data["e"]


def email_matches(order_email: str, email_hash: str) -> bool:
    import hmac
    return hmac.compare_digest(_email_hash(order_email), email_hash)
