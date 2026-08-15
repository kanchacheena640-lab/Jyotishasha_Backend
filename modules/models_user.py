"""
modules/models_user.py
-----------------------
Defines the AppUser model used for Jyotishasha App.
"""

from datetime import datetime, timezone
from extensions import db

class AppUser(db.Model):
    __tablename__ = "app_users"

    id = db.Column(db.Integer, primary_key=True)

    # Basic
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)

    # Birth details
    dob = db.Column(db.String(20), nullable=True)
    tob = db.Column(db.String(10), nullable=True)
    pob = db.Column(db.String(200), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)


    # -------------------------
    # ⭐ NEW Personalized Fields
    # -------------------------
    lagna = db.Column(db.String(50))
    moon_sign = db.Column(db.String(50))
    nakshatra = db.Column(db.String(50))

    # App prefs/state
    tz = db.Column(db.String(10), nullable=False, default="+05:30")
    # N3 -- persisted content-language preference ("en" / "hi"), so
    # personalized-content notifications (e.g. Transit) can deterministically
    # pick EN vs HI copy/article server-side instead of guessing from the
    # device. Nullable/no DB default: every existing row reads as NULL until
    # that user's next bootstrap/profile save; callers must treat NULL as
    # "unknown" and fall back to "en" themselves (see
    # services/notification_builder.py) rather than this column silently
    # defaulting everyone to a language they never chose.
    lang = db.Column(db.String(5), nullable=True)
    subscription = db.Column(db.String(50), nullable=False, default="free")
    asknow_tokens = db.Column(db.Integer, nullable=False, default=0)
    fcm_token = db.Column(db.String(255), nullable=True)

    firebase_uid = db.Column(db.String(255), nullable=True)


    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "dob": self.dob,
            "tob": self.tob,
            "pob": self.pob,
            "lat": self.lat,
            "lng": self.lng,

            # new fields
            "lagna": self.lagna,
            "moon_sign": self.moon_sign,
            "nakshatra": self.nakshatra,

            "tz": self.tz,
            "subscription": self.subscription,
            "asknow_tokens": self.asknow_tokens,
            "fcm_token": self.fcm_token, 
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<AppUser id={self.id} name={self.name}>"
    
class UserDashaTimeline(db.Model):
    __tablename__ = "user_dasha_timeline"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("app_users.id"), nullable=False)

    mahadasha = db.Column(db.String(20), nullable=False)
    antardasha = db.Column(db.String(20), nullable=False)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    user = db.relationship("AppUser", backref="dasha_timeline")
