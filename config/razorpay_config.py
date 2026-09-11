# config/razorpay_config.py

import os
import razorpay
from dotenv import load_dotenv

load_dotenv()  # Ensure .env is loaded

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")


class _LazyRazorpayClient:
    """Proxies every attribute access through to a real razorpay.Client(),
    constructed on FIRST actual use rather than merely by importing this
    module -- every existing `from config.razorpay_config import
    razorpay_client` call site (app.py + 5 service/route modules) keeps
    working completely unchanged, since attribute access (razorpay_client
    .order.create(...), etc.) is exactly what every real caller already
    does. The identical "Missing Razorpay API keys in .env" failure still
    happens, just at first real use instead of at import time -- no
    payment code path's behavior changes. This exists so a script that
    only needs `from app import app` for something unrelated to payments
    (e.g. scripts/campaign_worker_runner.py) is never forced to have
    RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET set just to boot."""
    _real_client = None

    def _get(self):
        if _LazyRazorpayClient._real_client is None:
            key_id = os.getenv("RAZORPAY_KEY_ID")
            key_secret = os.getenv("RAZORPAY_KEY_SECRET")
            if not key_id or not key_secret:
                raise Exception("Missing Razorpay API keys in .env")
            _LazyRazorpayClient._real_client = razorpay.Client(auth=(key_id, key_secret))
        return _LazyRazorpayClient._real_client

    def __getattr__(self, name):
        return getattr(self._get(), name)


razorpay_client = _LazyRazorpayClient()

# Payment Hardening -- Blocker 01 (Server-to-Server Payment Recovery):
# Razorpay's server webhook signs the raw request body with a SEPARATE
# secret (configured in the Razorpay Dashboard's Webhooks section), not
# RAZORPAY_KEY_SECRET -- that one only ever signs the checkout.js
# order_id|payment_id pair. Deliberately NOT required at boot the way
# the two keys above are: an environment that hasn't configured this
# yet should still start (every other payment path is unaffected) --
# it should simply be unable to trust/act on payment.captured webhook
# deliveries until it's set. See modules/payments/razorpay_provider.py.
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
