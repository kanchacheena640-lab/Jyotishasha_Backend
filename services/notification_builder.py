from services.personalization_engine import (
    get_users_for_transit,
    get_users_for_dasha_change,
    get_current_dasha_users
)
from services.relative_day import get_relative_day, TODAY, TOMORROW, YESTERDAY
from services.card_service import build_good_morning_card
from datetime import date, timedelta
from models import AstroEvent

LINK_MAP = {
    "ekadashi": "jyotishasha.com/ekadashi",
    # future:
    # "pradosh": "jyotishasha.com/pradosh",
    # "amavasya": "jyotishasha.com/amavasya",
}

_DAY_WORD = {
    TODAY: "Today",
    TOMORROW: "Tomorrow",
    YESTERDAY: "Yesterday",
}


def build_event_content(event):
    """
    The single place that turns a vrat/festival AstroEvent into
    notification title/body/data -- used for both the personalized Bell
    (get_user_notifications' EVENT section) and the Step 5A topic
    broadcast (event_scheduler.py), so both always say the same thing.
    Not user-specific: same event always produces the same content.

    Today/Tomorrow/Yesterday wording comes from relative_day.py -- the
    one place that compares event.date to "now" -- never hand-rolled
    here, which is what previously let this text disagree with
    card_service's Event Detail wording for the same event.
    """
    event_type = getattr(event, "type", None)
    event_name = getattr(event, "name", None)
    event_id = getattr(event, "id", None)
    event_date = getattr(event, "date", None)

    if event_type not in ["vrat", "festival"] or not event_id:
        return None

    relative_day = get_relative_day(event_date)
    day_word = _DAY_WORD.get(relative_day, "Today")

    name_lower = (event_name or "").lower()

    link = None
    for key in LINK_MAP:
        if key in name_lower:
            link = LINK_MAP[key]
            break

    if link:
        body = f"""{event_name} {day_word} 🙏

        Vrat vidhi, mahatva aur Paran time jaane
        👉 Read Full Guide

        {link}"""
    else:
        body = f"""{event_name} {day_word} 🙏

        Is din ka vishesh mahatva hai
        Niyamon ka dhyan rakhein"""

    title = f"{event_name} {day_word}" if relative_day in _DAY_WORD else event_name

    return {
        "title": title,
        "body": body,
        "data": {
            "type": "event",
            "event_id": str(event_id)
        }
    }


def get_user_notifications(user, events, global_notifications):
    """
    Returns personalized + global notifications for a user
    """

    final_notifications = []
    seen = set()

    # ---------------------------
    # 🔹 GLOBAL (application-wide generic notifications ONLY)
    # ---------------------------
    # AstroEvent-based notifications are the EVENT section's job below --
    # GLOBAL must never emit one, or the same AstroEvent ends up notified
    # twice under two different identities (see the v1.0 architecture
    # freeze). The only thing that legitimately reaches here is the
    # event-less generic fallback event_scheduler.py builds when there's
    # nothing to say today (data.type == "general").
    for n in (global_notifications or []):
        data = n.get("data", {}) or {}

        if data.get("type") != "general":
            continue

        event_id = data.get("event_id", f"global_{len(final_notifications)}")

        if event_id in seen:
            continue
        seen.add(event_id)

        final_notifications.append({
            "title": n.get("title"),
            "body": n.get("body"),
            "data": data
        })

    # ---------------------------
    # 🔹 EVENT (VRAT / FESTIVAL) -- sole owner of AstroEvent notifications
    # ---------------------------
    # One AstroEvent produces exactly one notification. This is the only
    # section allowed to turn a vrat/festival AstroEvent into a
    # notification; its dedup identity (event_scheduler.py) is the
    # AstroEvent's own id, so there is exactly one code path and one key
    # per event -- never two. Content comes from build_event_content()
    # above, shared with the Step 5A topic broadcast.
    for event in events:
        event_id = getattr(event, "id", None)

        if event_id in seen:
            continue

        content = build_event_content(event)
        if not content:
            continue

        seen.add(event_id)
        final_notifications.append(content)

    # ---------------------------
    # 🔹 TRANSIT
    # ---------------------------
    transit_map = {}

    # 🔹 Build map (1 DB call per event)
    for event in events:
        event_type = getattr(event, "type", None)
        event_id = getattr(event, "id", None)

        if event_type != "transit" or not event_id:
            continue

        try:
            transit_map[event_id] = get_users_for_transit(event)
        except Exception as e:
            print(f"❌ Transit map error for event {event_id}: {str(e)}")
            continue

    # 🔹 Assign to current user
    for event in events:
        event_type = getattr(event, "type", None)
        event_id = getattr(event, "id", None)

        if event_type != "transit" or not event_id:
            continue

        for u in transit_map.get(event_id, []):
            try:
                if u["user"].id != user.id:
                    continue

                event_id_str = f"transit_{event_id}_{u['planet']}_{u['house']}"

                if event_id_str in seen:
                    continue
                seen.add(event_id_str)

                final_notifications.append({
                    "title": f"{u['planet']} Transit Alert",
                    "body": f"{u['planet']} आपके {u['house']} भाव में प्रवेश कर चुका है",
                    "data": {
                        "type": "transit",
                        "event_id": str(event_id),
                        "planet": u["planet"],
                        "house": str(u["house"])
                    }
                })

            except Exception as e:
                print(f"❌ Transit user error: {str(e)}")
                continue

    # ---------------------------
    # 🔹 DASHA T-5 ALERT
    # ---------------------------
    t_minus_5_users = get_users_for_dasha_change(days_before=5)

    for d in t_minus_5_users:
        if d["user"].id != user.id:
            continue

        event_id_str = f"dasha_pre_{d['user'].id}_{d['mahadasha']}_{d['antardasha']}"

        if event_id_str in seen:
            continue
        seen.add(event_id_str)

        final_notifications.append({
            "title": "⏳ Dasha Change Coming",
            "body": f"5 din baad aapki {d['mahadasha']} - {d['antardasha']} dasha shuru hogi",
            "data": {
                "type": "dasha_pre",
                "event_id": event_id_str,
                "mahadasha": d["mahadasha"],
                "antardasha": d["antardasha"]
            }
        })

    # ---------------------------
    # 🔹 DASHA START (SAME DAY)
    # ---------------------------
    dasha_users = get_users_for_dasha_change()

    for d in dasha_users:
        if d["user"].id != user.id:
            continue

        event_id_str = f"dasha_{d['user'].id}_{d['mahadasha']}_{d['antardasha']}"

        if event_id_str in seen:
            continue
        seen.add(event_id_str)

        final_notifications.append({
            "title": f"{d['mahadasha']} Dasha Update 🔮",
            "body": f"{d['mahadasha']} - {d['antardasha']} phase शुरू हो गया है",
            "data": {
                "type": "dasha",
                "event_id": event_id_str,
                "mahadasha": d["mahadasha"],
                "antardasha": d["antardasha"]
            }
        })

    # ---------------------------
    # 🔹 PANCHAK
    # ---------------------------
    for event in events:
        try:
            event_type = getattr(event, "type", None)
            event_name = getattr(event, "name", None)
            event_id = getattr(event, "id", None)
            event_date = getattr(event, "date", None)

            if event_type != "panchak" or not event_id or not event_date:
                continue

            # 🔥 Only notify on the FIRST day of this Panchak window.
            # AstroEvent gets a fresh "panchak" row every day it stays active,
            # so a row dated "yesterday" means today is a continuation, not the start.
            prev_day = event_date - timedelta(days=1)

            already_running = AstroEvent.query.filter_by(
                type="panchak",
                date=prev_day
            ).first()

            if already_running:
                continue

            event_id_str = f"panchak_{event_id}"

            if event_id_str in seen:
                continue
            seen.add(event_id_str)

            final_notifications.append({
                "title": event_name or "Panchak Alert",
                "body": f"""{event_name or "Panchak"} शुरू हो गया है 🙏

        Is samay nirmaan, yatra aur mahatvapurn karyon se bachein
        Niyamon ka dhyan rakhein""",
                "data": {
                    "type": "panchak",
                    "event_id": str(event_id)
                }
            })

        except Exception as e:
            print(f"❌ Panchak event error: {str(e)}")
            continue

    # ---------------------------
    # 🔹 PANCHANG (Today's Panchang -- one per day, not personalized)
    # ---------------------------
    for event in events:
        try:
            event_type = getattr(event, "type", None)
            event_id = getattr(event, "id", None)

            if event_type != "panchang" or not event_id:
                continue

            event_id_str = f"panchang_{event_id}"

            if event_id_str in seen:
                continue
            seen.add(event_id_str)

            # Reuse the existing card content builder instead of
            # recomputing Abhijit Muhurta / Rahu Kaal here.
            good_morning = build_good_morning_card(event.meta or {}) or {}
            times = good_morning.get("meta", {})

            tithi_name = ((event.meta or {}).get("tithi") or {}).get("name") or "Not available"

            body = (
                f"Today's Tithi: {tithi_name}\n"
                f"Best Time (Shubh): {times.get('abhijit', 'Not available')}\n"
                f"Avoid Time (Ashubh): {times.get('rahu_kaal', 'Not available')}"
            )

            final_notifications.append({
                "title": "🌅 Today's Panchang",
                "body": body,
                "data": {
                    "type": "panchang",
                    "event_id": str(event_id)
                }
            })

        except Exception as e:
            print(f"❌ Panchang notification error: {str(e)}")
            continue

    # 🔥 RETURN AT END ONLY
    return final_notifications