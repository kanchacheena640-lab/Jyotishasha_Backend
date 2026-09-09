"""
modules/models_user.py
-----------------------
Defines the AppUser model used for Jyotishasha App.
"""

from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB
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

    # -------------------------
    # U3B.1 -- static (natal) astrology facts, ALL reused/derived from
    # the SAME calculate_full_kundali() call that already populates
    # lagna/moon_sign/nakshatra above -- never a second calculation.
    # See modules/services/static_astrology_extractor.py for the single
    # authoritative extraction logic and the NULL/{}/sparse state
    # contract (frozen U3B architecture decision):
    #   not calculated  -> all 5 of these columns NULL
    #   calculated      -> static_astrology_calculated_at set;
    #                      static_yog/static_dosh are {} (calculated,
    #                      nothing active/present) or a sparse dict of
    #                      only the active/present entries -- inactive
    #                      traits are never stored explicitly.
    # -------------------------
    nakshatra_pada = db.Column(db.SmallInteger, nullable=True)
    static_yog = db.Column(JSONB, nullable=True)
    static_dosh = db.Column(JSONB, nullable=True)
    static_astrology_calculated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    static_astrology_version = db.Column(db.SmallInteger, nullable=True)

    # App prefs/state
    tz = db.Column(db.String(10), nullable=False, default="+05:30")
    # L2/L3: explicit authenticated app preference; content/bootstrap/profile
    # language does not write this field. NULL is unknown, never implicit
    # English audience membership. Rendering may independently fall back.
    lang = db.Column(db.String(5), nullable=True)
    subscription = db.Column(db.String(50), nullable=False, default="free")
    asknow_tokens = db.Column(db.Integer, nullable=False, default=0)
    fcm_token = db.Column(db.String(255), nullable=True)

    # Trust Foundation Phase 0: this column is guaranteed unique (where
    # non-null) in every environment by migrations/versions/
    # b3f8e6a2c9d4_..., which reconciles whatever unique-firebase_uid
    # index a given environment already had (production's own
    # pre-existing `unique_firebase_uid`, or -- as in local dev --
    # newly created there under the name below) rather than assuming
    # either "already exists" or "missing". The actual, live shape in
    # every environment is a PARTIAL unique index (WHERE firebase_uid
    # IS NOT NULL), not a plain column-level `unique=True` -- see
    # Phase 2 Database Drift Blocker Verification (Event Tracking
    # project). Declared explicitly below via __table_args__ instead of
    # `unique=True` so this model actually describes that reality;
    # NULL remains allowed (many profiles are never linked to a
    # Firebase login) and multiple NULLs are fine either way -- Postgres
    # never compares NULL to NULL as equal, under a partial index or a
    # plain unique constraint alike. Metadata-only correction: no DB
    # change, no identity/auth behavior change.
    firebase_uid = db.Column(db.String(255), nullable=True)


    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        db.Index(
            "unique_app_users_firebase_uid",
            "firebase_uid",
            unique=True,
            postgresql_where=db.text("firebase_uid IS NOT NULL"),
        ),
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

    # U4A.1 -- describes the schema migrations/versions/
    # 37fd90bfdfd5_add_dasha_timeline_constraints.py actually creates;
    # no DB change here, this only makes the model match reality.
    # UNIQUE(user_id, mahadasha, antardasha): within one profile's
    # single generated Vimshottari cycle each (mahadasha, antardasha)
    # pair occurs exactly once (proven in U4A.0) -- this is both the
    # duplicate-prevention guarantee AND the per-profile lookup index
    # (user_id is its leading column), so no separate user_id index is
    # declared. The (start_date, end_date) index serves the two
    # existing bulk (no user_id filter) readers in
    # services/personalization_engine.py.
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "mahadasha", "antardasha",
            name="uq_user_dasha_timeline_user_mahadasha_antardasha",
        ),
        db.Index(
            "ix_user_dasha_timeline_start_end",
            "start_date", "end_date",
        ),
    )
