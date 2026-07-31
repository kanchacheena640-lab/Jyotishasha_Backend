# config/razorpay_config.py

import os
import razorpay
from dotenv import load_dotenv

load_dotenv()  # Ensure .env is loaded

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
    raise Exception("Missing Razorpay API keys in .env")

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

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
