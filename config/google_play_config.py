# config/google_play_config.py

"""
Google Play Developer API credentials -- follows the exact same
convention already established for Firebase in extensions.py::
init_firebase() (a raw JSON string in an environment variable, parsed
with json.loads()) rather than inventing a new one.

Deliberately NOT required at import time the way Razorpay's keys are
(config/razorpay_config.py raises if missing): an environment that
hasn't configured Google Play yet must still be able to boot and run
every other payment path unaffected. GooglePlayProvider.verify() is
what handles a missing/unusable credential gracefully, returning a
structured AUTH_ERROR result rather than crashing.

No new pip dependency: google-auth and google.oauth2.service_account
are already present transitively via firebase-admin (confirmed already
installed in this environment), so this reuses exactly what's already
there instead of adding google-api-python-client.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"

GOOGLE_PLAY_PACKAGE_NAME: Optional[str] = os.environ.get("GOOGLE_PLAY_PACKAGE_NAME")

_authorized_session: Optional[AuthorizedSession] = None
_init_error: Optional[str] = None


def _build_session() -> Optional[AuthorizedSession]:
    global _init_error
    raw_json = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON")
    if not raw_json:
        _init_error = "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON is not configured"
        return None
    try:
        info = json.loads(raw_json)
        credentials = Credentials.from_service_account_info(
            info, scopes=[ANDROID_PUBLISHER_SCOPE],
        )
        return AuthorizedSession(credentials)
    except Exception as exc:
        _init_error = f"Failed to initialize Google Play credentials: {exc}"
        return None


def get_android_publisher_session() -> Optional[AuthorizedSession]:
    """
    Lazy singleton, mirroring config/payment_provider_registry.py's own
    get_default_registry() shape. Returns None (never raises) if
    credentials are missing or malformed -- callers must treat that as
    "cannot verify right now", not crash.
    """
    global _authorized_session
    if _authorized_session is None:
        _authorized_session = _build_session()
    return _authorized_session


def get_init_error() -> Optional[str]:
    """Populated only after get_android_publisher_session() has been
    called at least once and failed -- lets a caller surface exactly
    why verification is unavailable."""
    return _init_error
