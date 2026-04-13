"""
modules/user_service.py
------------------------
Service layer for AppUser model.

Handles creation, update, and retrieval of app-specific user records.
This isolates ORM logic from route logic, keeping the API clean.

Functions:
- register_or_update_user(data)
- get_user_by_id(user_id)
"""

from extensions import db
from modules.models_user import AppUser

# ---------- Register or Update ----------
def register_or_update_user(data: dict) -> AppUser:
    from modules.auth.models import User

    firebase_uid = data.get("firebase_uid")

    # 🚨 1. HARD RULE: firebase_uid must exist
    if not firebase_uid:
        raise ValueError("firebase_uid is required")

    # 🔥 2. Find existing AppUser by firebase_uid
    user = AppUser.query.filter_by(firebase_uid=firebase_uid).first()

    # 🔥 3. If not found → create
    if not user:
        user = AppUser(firebase_uid=firebase_uid)
        db.session.add(user)

    # 🔥 4. Sync from User table (IMPORTANT)
    main_user = User.query.filter_by(firebase_uid=firebase_uid).first()

    if main_user:
        user.name = main_user.name
        user.email = main_user.email
        user.phone = main_user.phone

    # 🔥 5. Override from incoming data (if provided)
    if data.get("name"):
        user.name = data["name"]

    if data.get("email"):
        user.email = data["email"]

    if data.get("phone"):
        user.phone = data["phone"]

    user.dob = data.get("dob", user.dob)
    user.tob = data.get("tob", user.tob)
    user.pob = data.get("pob", user.pob)
    user.lat = data.get("lat", user.lat)
    user.lng = data.get("lng", user.lng)
    user.tz = data.get("tz", user.tz or "+05:30")
    user.subscription = data.get("subscription", user.subscription or "free")

    # 🔥 6. FCM token
    if data.get("fcm_token"):
        user.fcm_token = data["fcm_token"]

    db.session.commit()
    return user

# ---------- Fetch by ID ----------
def get_user_by_id(user_id: int) -> AppUser | None:
    """Fetch a user by id"""
    return AppUser.query.get(user_id)
