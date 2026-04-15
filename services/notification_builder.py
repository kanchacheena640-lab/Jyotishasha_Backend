from services.personalization_engine import (
    get_users_for_transit,
    get_users_for_dasha_change,
    get_current_dasha_users
)


def get_user_notifications(user, events, global_notifications):
    """
    Returns personalized + global notifications for a user
    """

    final_notifications = []

    # ---------------------------
    # 🔹 GLOBAL
    # ---------------------------
    for n in (global_notifications or []):
        final_notifications.append({
            "title": n.get("title"),
            "body": n.get("body"),
            "data": n.get("data", {}) or {}   # 🔥 FORCE SAFE
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
    # 🔹 DASHA START WINDOW
    # ---------------------------
    dasha_users = get_users_for_dasha_change()

    for d in dasha_users:
        if d["user"].id != user.id:
            continue

        final_notifications.append({
            "title": f"{d['mahadasha']} Dasha Update 🔮",
            "body": f"{d['mahadasha']} - {d['antardasha']} phase शुरू हो गया है",
            "data": {
                "type": "dasha",
                "event_id": f"dasha_{d['user'].id}_{d['mahadasha']}_{d['antardasha']}",
                "mahadasha": d["mahadasha"],
                "antardasha": d["antardasha"]
            }
        })

    # ---------------------------
    # 🔹 RUNNING DASHA
    # ---------------------------
    running_users = get_current_dasha_users()

    for d in running_users:
        if d["user"].id != user.id:
            continue

        final_notifications.append({
            "title": f"{d['mahadasha']} Dasha Active 🧠",
            "body": f"आप अभी {d['mahadasha']} - {d['antardasha']} phase में हैं",
            "data": {
                "type": "dasha_running",
                "event_id": f"running_{d['user'].id}_{d['mahadasha']}_{d['antardasha']}",
                "mahadasha": d["mahadasha"],
                "antardasha": d["antardasha"]
            }
        })

    # 🔥 RETURN AT END ONLY
    return final_notifications