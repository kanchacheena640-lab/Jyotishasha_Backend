from datetime import datetime
from extensions import db     
from models import AstroEvent

# 🔹 Existing astro detectors
from services.events_engine import (
    find_next_pradosh,
    find_next_sankashti,
    find_next_amavasya,
    find_next_purnima,
    find_next_vinayaka_chaturthi,
    find_next_shivratri,
)

# 🔹 Adapter (ONLY used in SAVE)
from services.event_adapters.festival_adapter import normalize_event


# =====================================================
# 🔹 GENERATE (RAW ONLY — NO NORMALIZATION HERE)
# =====================================================
def generate_events_for_date(date, lat, lon, language="en"):
    events = []

    def add(e):
        if e:
            events.append(e)

    add(find_next_pradosh(date, lat, lon, language))
    add(find_next_sankashti(date, lat, lon, language))
    add(find_next_amavasya(date, lat, lon, language))
    add(find_next_purnima(date, lat, lon, language))
    add(find_next_vinayaka_chaturthi(date, lat, lon, language))
    add(find_next_shivratri(date, lat, lon, language))

    return events


# =====================================================
# 🔹 SAVE (NORMALIZE ONLY ONCE HERE)
# =====================================================
def save_events_to_db(events):
    saved_count = 0

    for raw_event in events:

        # 🔥 normalize ONLY ONCE
        event = normalize_event(raw_event)
        if not event:
            continue

        # 🔹 date safety (string)
        event_date = event.get("date")
        if hasattr(event_date, "strftime"):
            event_date = event_date.strftime("%Y-%m-%d")
        else:
            event_date = str(event_date)[:10]

        event_name = event.get("name")
        event_type = event.get("type")

        if not event_name or not event_date:
            continue

        # 🔹 duplicate check
        existing = AstroEvent.query.filter_by(
            name=event_name,
            date=event_date,
            type=event_type
        ).first()

        if existing:
            continue

        # 🔹 meta safety
        meta = event.get("meta") or {}

        if isinstance(meta, dict) and "date" in meta:
            meta["date"] = (
                str(meta["date"])
                .replace("20   026", "2026")
                .replace("20 026", "2026")
                .replace("22026", "2026")
            )

        # 🔹 save
        new_event = AstroEvent(
            name=event_name,
            date=event_date,
            type=event_type,
            priority=event.get("priority", 3),
            notify_before_days=event.get("notify_before_days", 1),
            notify_same_day=event.get("notify_same_day", True),
            meta=meta
        )

        print(f"👉 Saving: {event_name} | {event_date}")

        db.session.add(new_event)
        saved_count += 1

    try:
        db.session.commit()
        print(f"✅ {saved_count} events saved to DB")
    except Exception as e:
        db.session.rollback()
        print(f"❌ DB ERROR: {e}")