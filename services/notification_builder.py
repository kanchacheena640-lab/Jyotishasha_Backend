from services.personalization_engine import (
    get_users_for_transit,
    get_users_for_dasha_change
)


def get_user_notifications(user, events, global_notifications):
    """
    Returns personalized + global notifications for a user
    """

    final_notifications = []

    # ---------------------------
    # 🔹 GLOBAL
    # ---------------------------
    final_notifications.extend(global_notifications or [])

    # ---------------------------
    # 🔹 TRANSIT
    # ---------------------------
    transit_map = {}

    # 🔹 Build map (1 DB call per event)
    for event in events:
        if event.type != "transit" or not event.id:
            continue

        try:
            transit_map[event.id] = get_users_for_transit(event)
        except Exception as e:
            print(f"❌ Transit map error for event {event.id}: {str(e)}")
            continue


    # 🔹 Assign to current user
    for event in events:
        if event.type != "transit" or not event.id:
            continue

        for u in transit_map.get(event.id, []):
            try:
                if u["user"].id != user.id:
                    continue

                final_notifications.append({
                    "title": f"{u['planet']} Transit Alert",
                    "body": f"{u['planet']} आपके {u['house']} भाव में प्रवेश कर चुका है",
                    "data": {
                        "type": "transit",
                        "event_id": str(event.id),
                        "planet": u["planet"],
                        "house": str(u["house"])
                    }
                })

            except Exception as e:
                print(f"❌ Transit user error: {str(e)}")
                continue

    # ---------------------------
    # 🔹 DASHA (placeholder)
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

    return final_notifications