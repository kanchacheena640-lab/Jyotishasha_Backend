# modules/payments/pubsub_auth_models.py

"""
Structured result type for Google Cloud Pub/Sub push authentication
(Subscription Purchase System -- S7D). Same role as
google_play_models.py: shape only, no verification logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


class PubSubAuthStatus:
    """
    The outcome of authenticating one incoming Pub/Sub push request.

        AUTHENTICATED                -- signature, expiry, issuer, and
                                         audience all check out, and
                                         (when configured) the token's
                                         email claim matches the
                                         authorized service account.
        MISSING_AUTHORIZATION_HEADER -- no Authorization header at all.
        MALFORMED_BEARER_TOKEN       -- header present but not
                                         "Bearer <token>", or the token
                                         itself is not a well-formed
                                         JWT (wrong number of segments,
                                         unparseable header/payload).
        INVALID_SIGNATURE            -- the JWT's signature does not
                                         verify against Google's
                                         published public keys (or the
                                         token's key id matches none of
                                         them).
        EXPIRED_TOKEN                -- the token's exp (or iat, if
                                         issued in the future) claim
                                         fails the timing check.
        INVALID_ISSUER                -- the verified token's 'iss' is
                                         not one of Google's own OIDC
                                         issuers.
        INVALID_AUDIENCE               -- the verified token's 'aud'
                                         does not match
                                         PUBSUB_AUDIENCE.
        UNAUTHORIZED_SERVICE_ACCOUNT -- the token verified correctly in
                                         every other respect, but its
                                         'email' claim does not match
                                         PUBSUB_AUTHORIZED_SERVICE_
                                         ACCOUNT_EMAIL (only checked
                                         when that is configured).
        CONFIG_ERROR                  -- PUBSUB_AUDIENCE is not
                                         configured at all -- fails
                                         closed (rejected) rather than
                                         silently accepting
                                         unauthenticated requests.
        UNKNOWN_ERROR                  -- any other verification
                                         failure; error_message carries
                                         the detail for investigation
                                         rather than guessing which
                                         bucket it belongs in.
    """
    AUTHENTICATED = "AUTHENTICATED"
    MISSING_AUTHORIZATION_HEADER = "MISSING_AUTHORIZATION_HEADER"
    MALFORMED_BEARER_TOKEN = "MALFORMED_BEARER_TOKEN"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    EXPIRED_TOKEN = "EXPIRED_TOKEN"
    INVALID_ISSUER = "INVALID_ISSUER"
    INVALID_AUDIENCE = "INVALID_AUDIENCE"
    UNAUTHORIZED_SERVICE_ACCOUNT = "UNAUTHORIZED_SERVICE_ACCOUNT"
    CONFIG_ERROR = "CONFIG_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class PubSubAuthResult:
    """Normalized, read-only outcome of one authentication attempt.
    Never raises -- every failure mode above is a distinct, structured
    status rather than an exception, so the route can translate this
    directly into an HTTP response without its own try/except."""
    status: str  # PubSubAuthStatus
    authenticated: bool

    service_account_email: Optional[str] = None
    audience: Optional[str] = None
    issuer: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "authenticated": self.authenticated,
            "service_account_email": self.service_account_email,
            "audience": self.audience,
            "issuer": self.issuer,
            "error_message": self.error_message,
        }
