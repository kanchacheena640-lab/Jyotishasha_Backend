# config/pubsub_config.py

"""
Configuration for Google Cloud Pub/Sub push authentication
(Subscription Purchase System -- S7D). Same role as
config/google_play_config.py: env-var-driven configuration only, no
verification logic -- that lives in
modules/payments/pubsub_auth_service.py.

PUBSUB_AUDIENCE
    The 'aud' claim every push OIDC token must carry. Google's own
    recommendation is to set this to the exact push endpoint URL
    configured on the Pub/Sub subscription (e.g.
    "https://api.jyotishasha.com/webhooks/google-play/rtdn"). Read
    fresh on every call (not cached at import time) so it can be
    changed/tested without a process restart.

PUBSUB_AUTHORIZED_SERVICE_ACCOUNT_EMAIL
    Optional. The specific service account email Pub/Sub is expected
    to sign push tokens with. Enforced only "when configured" --
    PubSubAuthService.verify_request() skips this check entirely if
    this is unset, exactly as this phase's own requirements specify.
"""

from __future__ import annotations

import os
from typing import Optional


def get_expected_audience() -> Optional[str]:
    return os.environ.get("PUBSUB_AUDIENCE")


def get_authorized_service_account_email() -> Optional[str]:
    return os.environ.get("PUBSUB_AUTHORIZED_SERVICE_ACCOUNT_EMAIL")
