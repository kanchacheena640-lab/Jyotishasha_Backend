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
