from datetime import datetime
import bcrypt
from extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # Auth identity
    email = db.Column(db.String(120), unique=True, index=True, nullable=False)
    provider = db.Column(db.String(20), default="password")  # 'password' | 'google'

    # ✅ NEW: Firebase UID link
    firebase_uid = db.Column(db.String(200), unique=True, index=True, nullable=True)

    # Optional contact
    phone = db.Column(db.String(20), nullable=True)

    # Profile (birth details)
    name = db.Column(db.String(120), nullable=True)
    dob = db.Column(db.String(20), nullable=True)  # "YYYY-MM-DD"
    tob = db.Column(db.String(10), nullable=True)  # "HH:MM"
    pob = db.Column(db.String(200), nullable=True)

    # Secrets
    password_hash = db.Column(db.String(128), nullable=True)  # null for google users

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ---- helpers ----
    def set_password(self, raw_password: str) -> None:
        if not raw_password:
            self.password_hash = None
            return
        self.password_hash = bcrypt.hashpw(
            raw_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    def check_password(self, raw_password: str) -> bool:
        if not self.password_hash or not raw_password:
            return False
        try:
            return bcrypt.checkpw(
                raw_password.encode("utf-8"),
                self.password_hash.encode("utf-8"),
            )
        except Exception:
            return False

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "provider": self.provider,
            "phone": self.phone,
            "name": self.name,
            "dob": self.dob,
            "tob": self.tob,
            "pob": self.pob,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} provider={self.provider}>"
