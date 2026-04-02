from datetime import datetime
from models import db, AstroEvent


# 🔹 Existing astro detectors (logic layer)
from services.events_engine import (
    find_next_pradosh,
    find_next_sankashti,
    find_next_amavasya,
    find_next_purnima,
    find_next_vinayaka_chaturthi,
    find_next_shivratri,
)

# 🔹 Adapter
from services.event_adapters.festival_adapter import normalize_event


def generate_events_for_date(date, lat, lon, language="en"):
    events = []

    # 🔸 PRADOSH
    pradosh = find_next_pradosh(date, lat, lon, language)
    if pradosh:
        events.append(normalize_event(pradosh))

    # 🔸 SANKASHTI
    sankashti = find_next_sankashti(date, lat, lon, language)
    if sankashti:
        events.append(normalize_event(sankashti))

    # 🔸 AMAVASYA
    amavasya = find_next_amavasya(date, lat, lon, language)
    if amavasya:
        events.append(normalize_event(amavasya))

    # 🔸 PURNIMA
    purnima = find_next_purnima(date, lat, lon, language)
    if purnima:
        events.append(normalize_event(purnima))

    # 🔸 CHATURTHI
    chaturthi = find_next_vinayaka_chaturthi(date, lat, lon, language)
    if chaturthi:
        events.append(normalize_event(chaturthi))

    # 🔸 SHIVRATRI
    shivratri = find_next_shivratri(date, lat, lon, language)
    if shivratri:
        events.append(normalize_event(shivratri))

    return events


def save_events_to_db(events):
    for event in events:

        # 🔹 duplicate check
        existing = AstroEvent.query.filter_by(
            name=event["name"],
            date=event["date"],
            type=event.get("type")
        ).first()

        if existing:
            continue

        # 🔥 META SAFETY
        meta = event.get("meta")

        if not meta:
            if event.get("type") == "transit":
                meta = {
                    "planet": event.get("planet"),
                    "rashi": event.get("rashi")
                }
            else:
                meta = {}

        # 🔥 CLEAN DIRTY DATE (defensive)
        if isinstance(meta, dict) and "date" in meta:
            meta["date"] = (
                str(meta["date"])
                .replace("20   026", "2026")
                .replace("20 026", "2026")
                .replace("22026", "2026")
            )

        # 🔥 EXTRA SAFETY (important)
        if event.get("type") == "transit":
            if not meta.get("planet") or not meta.get("rashi"):
                print(f"⚠️ Skipping invalid transit event: {event}")
                continue

        new_event = AstroEvent(
            name=event.get("name"),
            date=event.get("date"),
            type=event.get("type"),
            priority=event.get("priority", 1),
            notify_before_days=event.get("notify_before_days", 0),
            notify_same_day=event.get("notify_same_day", True),
            meta=meta
        )

        db.session.add(new_event)

    db.session.commit()