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
    firebase_uid = data.get("firebase_uid")

    # 🔥 1. FIRST: try find by firebase_uid
    user = None
    if firebase_uid:
        user = AppUser.query.filter_by(firebase_uid=firebase_uid).first()

    # 🔥 2. fallback by id
    if not user:
        user_id = data.get("id")
        if user_id:
            user = AppUser.query.get(user_id)

    # 🔥 3. create new if not found
    if not user:
        user = AppUser()
        db.session.add(user)

    # 🔥 4. SAVE firebase_uid (MOST IMPORTANT)
    if firebase_uid:
        user.firebase_uid = firebase_uid

    # 🔥 5. बाकी fields (same)
    user.name = data.get("name", user.name)
    user.email = data.get("email", user.email)
    user.phone = data.get("phone", user.phone)
    user.dob = data.get("dob", user.dob)
    user.tob = data.get("tob", user.tob)
    user.pob = data.get("pob", user.pob)
    user.lat = data.get("lat", user.lat)
    user.lng = data.get("lng", user.lng)
    user.tz = data.get("tz", user.tz or "+05:30")
    user.subscription = data.get("subscription", user.subscription or "free")

    # 🔥 6. FCM also handle here (extra safety)
    if data.get("fcm_token"):
        user.fcm_token = data["fcm_token"]

    db.session.commit()
    return user

# ---------- Fetch by ID ----------
def get_user_by_id(user_id: int) -> AppUser | None:
    """Fetch a user by id"""
    return AppUser.query.get(user_id)
