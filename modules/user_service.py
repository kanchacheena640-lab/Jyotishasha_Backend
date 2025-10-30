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
    """
    Create or update an AppUser record.
    Used when app sends name, dob, pob etc. from profile form.
    """
    user_id = data.get("id")
    if user_id:
        user = AppUser.query.get(user_id)
        if not user:
            raise ValueError("User not found")
    else:
        user = AppUser()
        db.session.add(user)

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

    db.session.commit()
    return user


# ---------- Fetch by ID ----------
def get_user_by_id(user_id: int) -> AppUser | None:
    """Fetch a user by id"""
    return AppUser.query.get(user_id)
