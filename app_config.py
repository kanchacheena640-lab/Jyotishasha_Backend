import os

# ------------------ DATABASE CONFIG ------------------ #
SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
SQLALCHEMY_TRACK_MODIFICATIONS = False

# ------------------ SECURITY KEYS ------------------ #
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-this-in-prod")
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret")

# ------------------ BACKGROUND TASK TOGGLE ------------------ #
# 🔁 Toggle this switch to control Celery/Redis usage
# --------------------------------------------------------------
# USE_CELERY = False → Simple direct mode (no Redis, no worker)
# USE_CELERY = True  → Full async mode (Celery + Redis enabled)
# --------------------------------------------------------------
USE_CELERY = False

# ------------------ PAID REPORT AI MODEL (Q3 Batch 0) ------------------ #
# The ONE authoritative model for paid-report generation (both
# standard_v1 and love_premium_v1) -- see modules/payments/
# report_ai_client.py, the single call site that reads this constant.
# Deliberately scoped to paid reports only: Quest/chat/smartchat/AI
# Prediction Lab each keep their own separate model configuration,
# untouched by this constant.
PAID_REPORT_AI_MODEL = "gpt-5.6-luna"

# ------------------ APP DOWNLOAD CTA STORE URLS (Q3 Batch 1 visual QA) ------------------ #
# Q2.1's own locked rule: the only shared closing CTA a paid-report PDF
# may carry is "download the Jyotishasha App" -- never a fake/guessed
# store link. JYOTISHASHA_PLAY_STORE_URL is the exact official URL
# explicitly confirmed by the project owner (Q3 Batch 1 visual QA
# correction round) -- no longer constructed/inferred from the package
# id. (Earlier this was built from _PACKAGE_ID ("com.jyotishasha.app"),
# the same id seeded into the live app_version_policy table by
# migrations/versions/c7d2f5a9e1b3_add_app_version_policy_table.py --
# still the same app/listing, just the owner's own exact URL now, not
# a derived one.) Android remains the only platform this app ships on
# -- there is no verified iOS App Store listing, so
# JYOTISHASHA_APP_STORE_URL stays None (never a fabricated
# apps.apple.com link) until one is separately provided.
JYOTISHASHA_PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.jyotishasha.app&pcampaignid=web_share"
JYOTISHASHA_APP_STORE_URL = None
