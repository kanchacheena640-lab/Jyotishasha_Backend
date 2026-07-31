# modules/payments/pubsub_auth_service.py

"""
PubSubAuthService -- Google Cloud Pub/Sub push authentication
(Subscription Purchase System -- S7D).

Verifies that an incoming RTDN HTTP request genuinely came from Google
Cloud Pub/Sub, using the industry-standard mechanism Google itself
documents for authenticated push subscriptions: an OIDC ID token in
the `Authorization: Bearer <token>` header, signed by Google and
verifiable against Google's own published public keys.

Reuses google.oauth2.id_token.verify_oauth2_token() (already available
transitively via firebase-admin, same as S3's GooglePlayProvider) for
the actual cryptographic work -- signature verification against
Google's public certs, key-id lookup, expiry/issued-at checks, and
audience matching all happen inside that one call. This file never
implements its own JWT parsing or signature verification; hand-rolling
that would be exactly the kind of security-critical reinvention this
phase's "industry-standard authentication" instruction is meant to
avoid.

Only two things are layered on top of that library call:
    1. Bucketing the library's exceptions into the distinct,
       structured PubSubAuthStatus values this phase's validation asks
       for (issuer vs audience vs expiry vs signature vs malformed) --
       necessarily done by inspecting each exception's own message,
       since the library intentionally collapses these into a small
       number of exception types rather than one-per-reason. This is
       best-effort classification for observability; every branch
       below still ends in the same outcome (authenticated=False,
       reject), so a misclassified reason never changes behavior, only
       the logged label.
    2. The service-account 'email' claim check, which the library does
       not perform at all -- PUBSUB_AUTHORIZED_SERVICE_ACCOUNT_EMAIL is
       enforced here, only when configured.

Deliberately NOT implemented (this phase's own "Do NOT" list): nothing
here touches the RTDN dispatcher, GooglePlayProvider verification, or
any entitlement logic. This service answers exactly one question --
"did this HTTP request genuinely come from Google Pub/Sub" -- and
nothing about what the request's payload means.
"""

from __future__ import annotations

from typing import Optional

from google.auth import exceptions as google_auth_exceptions
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token

from config.pubsub_config import (
    get_authorized_service_account_email,
    get_expected_audience,
)
from modules.payments.pubsub_auth_models import PubSubAuthResult, PubSubAuthStatus

_BEARER_PREFIX = "Bearer "


class PubSubAuthService:
    def __init__(self):
        # A fresh transport per instance, matching this codebase's
        # existing convention of instantiating provider classes fresh
        # per call (see GooglePlayProvider) rather than introducing a
        # new singleton/session-caching pattern for this phase alone.
        self._request = google_auth_requests.Request()

    def verify_request(self, authorization_header: Optional[str]) -> PubSubAuthResult:
        if not authorization_header:
            return PubSubAuthResult(
                status=PubSubAuthStatus.MISSING_AUTHORIZATION_HEADER, authenticated=False,
                error_message="Authorization header is missing.",
            )

        if not authorization_header.startswith(_BEARER_PREFIX):
            return PubSubAuthResult(
                status=PubSubAuthStatus.MALFORMED_BEARER_TOKEN, authenticated=False,
                error_message="Authorization header is not a Bearer token.",
            )

        token = authorization_header[len(_BEARER_PREFIX):].strip()
        if not token or token.count(".") != 2:
            return PubSubAuthResult(
                status=PubSubAuthStatus.MALFORMED_BEARER_TOKEN, authenticated=False,
                error_message="Bearer token is not a well-formed JWT.",
            )

        expected_audience = get_expected_audience()
        if not expected_audience:
            # Fail closed: an unconfigured audience must never be
            # treated as "verification not required".
            return PubSubAuthResult(
                status=PubSubAuthStatus.CONFIG_ERROR, authenticated=False,
                error_message="PUBSUB_AUDIENCE is not configured -- refusing to accept "
                               "any push request until it is.",
            )

        try:
            claims = google_id_token.verify_oauth2_token(
                token, self._request, audience=expected_audience,
            )
        except google_auth_exceptions.GoogleAuthError as exc:
            return self._result_for_verification_error(exc)
        except Exception as exc:
            # Never let an unclassified verification failure raise out
            # of an auth check -- every outcome here is structured.
            return PubSubAuthResult(
                status=PubSubAuthStatus.UNKNOWN_ERROR, authenticated=False,
                error_message=str(exc),
            )

        service_account_email = claims.get("email")
        issuer = claims.get("iss")
        audience = claims.get("aud")

        authorized_email = get_authorized_service_account_email()
        if authorized_email and service_account_email != authorized_email:
            return PubSubAuthResult(
                status=PubSubAuthStatus.UNAUTHORIZED_SERVICE_ACCOUNT, authenticated=False,
                service_account_email=service_account_email, audience=audience, issuer=issuer,
                error_message=f"service account {service_account_email!r} is not "
                              f"authorized to call this endpoint.",
            )

        return PubSubAuthResult(
            status=PubSubAuthStatus.AUTHENTICATED, authenticated=True,
            service_account_email=service_account_email, audience=audience, issuer=issuer,
        )

    @staticmethod
    def _result_for_verification_error(exc: Exception) -> PubSubAuthResult:
        """Best-effort classification of a GoogleAuthError (and its
        MalformedError/InvalidValue subclasses) into a specific
        PubSubAuthStatus, by inspecting the library's own message --
        see this module's docstring for why a library-level exception
        is bucketed this way instead of by exception type alone."""
        message = str(exc)
        lowered = message.lower()

        if "wrong issuer" in lowered:
            status = PubSubAuthStatus.INVALID_ISSUER
        elif "wrong audience" in lowered:
            status = PubSubAuthStatus.INVALID_AUDIENCE
        elif "expired" in lowered or "too early" in lowered:
            status = PubSubAuthStatus.EXPIRED_TOKEN
        elif "signature" in lowered or "certificate" in lowered:
            status = PubSubAuthStatus.INVALID_SIGNATURE
        elif "segments" in lowered or "json object" in lowered:
            status = PubSubAuthStatus.MALFORMED_BEARER_TOKEN
        else:
            status = PubSubAuthStatus.UNKNOWN_ERROR

        return PubSubAuthResult(status=status, authenticated=False, error_message=message)
