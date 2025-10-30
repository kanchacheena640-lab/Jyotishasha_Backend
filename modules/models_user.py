"""
modules/models_user.py
-----------------------
Defines the AppUser model used for Jyotishasha App.

This model stores user profile data for personalized features
(AskNow chat, Horoscope, Muhurth etc.) and is separate from the
authentication User model inside modules/auth.

Phase-1 Scope:
- Fixed timezone (+05:30)
- Subscription and AskNow tokens tracking
- No auth / JWT linkage yet
"""

from datetime import datetime
from extensions import db

class AppUser(db.Model):
    __tablename__ = "app_users"  # separate from auth.users

    id = db.Column(db.Integer, primary_key=True)

    # Basic
    name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), nullable=True)   # not unique here (auth handles identity)
    phone = db.Column(db.String(20), nullable=True)

    # Birth details
    dob = db.Column(db.String(20), nullable=True)      # "YYYY-MM-DD"
    tob = db.Column(db.String(10), nullable=True)      # "HH:MM"
    pob = db.Column(db.String(200), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    # App prefs/state
    tz = db.Column(db.String(10), nullable=False, default="+05:30")  # IST locked in Phase-1
    subscription = db.Column(db.String(50), nullable=False, default="free")  # free/monthly/yearly/pro
    asknow_tokens = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
            "tz": self.tz,
            "subscription": self.subscription,
            "asknow_tokens": self.asknow_tokens,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<AppUser id={self.id} name={self.name}>"
