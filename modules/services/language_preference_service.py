"""Authenticated app preference utilities; no profile/content side effects."""
from extensions import db
from modules.models_user import AppUser


def normalize_language(value):
    if not isinstance(value, str) or value.strip().lower() not in ("en", "hi"):
        raise ValueError("lang must be en or hi")
    return value.strip().lower()


def content_language(data):
    """Bootstrap compatibility is rendering-only, never preference authority."""
    values = [normalize_language(data[k]) for k in ("lang", "language") if k in data]
    if len(set(values)) > 1:
        raise ValueError("lang and language conflict")
    return values[0] if values else "en"


def language_profile(uid):
    rows = AppUser.query.filter_by(firebase_uid=uid).limit(2).all()
    if len(rows) > 1:
        raise RuntimeError("ambiguous_profile")
    return rows[0] if rows else None


def preference_state(profile):
    try:
        lang = normalize_language(profile.lang) if profile else None
    except ValueError:
        lang = None
    return {"lang": lang, "profile_ready": profile is not None}


def write_language(profile, lang):
    profile.lang = normalize_language(lang)
    db.session.commit()
    return preference_state(profile)
