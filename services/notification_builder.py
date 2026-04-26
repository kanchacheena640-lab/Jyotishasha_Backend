from services.personalization_engine import (
    get_users_for_transit,
    get_users_for_dasha_change,
    get_current_dasha_users
)
from datetime import date, timedelta


def get_user_notifications(user, events, global_notifications):
    """
    Returns personalized + global notifications for a user
    """

    final_notifications = []
    seen = set()

    # ---------------------------
    # 🔹 GLOBAL
    # ---------------------------
    for n in (global_notifications or []):
        event_id = n.get("data", {}).get("event_id", f"global_{len(final_notifications)}")

        if event_id in seen:
            continue
        seen.add(event_id)

        final_notifications.append({
            "title": n.get("title"),
            "body": n.get("body"),
            "data": n.get("data", {}) or {}
        })

    # ---------------------------
    # 🔹 EVENT (VRAT / FESTIVAL)
    # ---------------------------

    LINK_MAP = {
        "ekadashi": "jyotishasha.com/ekadashi",
        # future:
        # "pradosh": "jyotishasha.com/pradosh",
        # "amavasya": "jyotishasha.com/amavasya",
    }

    for event in events:
        event_type = getattr(event, "type", None)
        event_name = getattr(event, "name", None)
        event_id = getattr(event, "id", None)

        if event_type not in ["vrat", "festival"]:
            continue

        event_id_str = f"event_{event_id}"

        if event_id_str in seen:
            continue
        seen.add(event_id_str)

        name_lower = (event_name or "").lower()

        # 🔍 link detect
        link = None
        for key in LINK_MAP:
            if key in name_lower:
                link = LINK_MAP[key]
                break

        # 🔥 BODY BUILD
        if link:
            body = f"""{event_name} Today 🙏

        Vrat vidhi, mahatva aur Paran time jaane  
        👉 Read Full Guide

        {link}"""
        else:   
            body = f"""{event_name} Today 🙏

        Is din ka vishesh mahatva hai  
        Niyamon ka dhyan rakhein"""

        final_notifications.append({
            "title": event_name,
            "body": body,
            "data": {
                "type": "event",
                "event_id": str(event_id)
            }
        })

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

    # 🔥 RETURN AT END ONLY
    return final_notifications