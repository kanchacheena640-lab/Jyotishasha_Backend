from datetime import datetime

def generate_panchang_events(panchang_data):
    events = []

    date = panchang_data.get("date") or datetime.utcnow().strftime("%Y-%m-%d")

    # 1. Tithi Event
    tithi = panchang_data.get("tithi", {})
    if tithi:
        events.append({
            "name": f"{tithi.get('name') or 'Unknown'} Tithi",
            "date": date,
            "type": "tithi",
            "priority": 2,
            "notify_before_days": 0,
            "meta": tithi
        })

    # 2. Nakshatra Event
    nakshatra = panchang_data.get("nakshatra", {})
    if nakshatra:
        events.append({
            "name": f"{nakshatra.get('name') or 'Unknown'} Nakshatra",
            "date": date,
            "type": "nakshatra",
            "priority": 2,
            "notify_before_days": 0,
            "meta": nakshatra
        })

    # 3. Panchak
    panchak = panchang_data.get("panchak", {})
    if panchak.get("active"):
        events.append({
            "name": "Panchak Active",
            "date": date,
            "type": "panchak",
            "priority": 3,
            "notify_before_days": 0,
            "meta": panchak
        })

    # 4. Today's Panchang (one per day, every day -- the daily
    # notification. "type"/"slug" here are what event_resolver.py needs
    # to build a resource identity, same convention ekadashi_engine
    # already uses; the rest of panchang_data is kept as-is so
    # notification_builder.py can reuse card_service.build_good_morning_card()
    # for content instead of recomputing it.
    events.append({
        "name": "Today's Panchang",
        "date": date,
        "type": "panchang",
        "priority": 2,
        "notify_before_days": 0,
        "meta": {**panchang_data, "type": "panchang", "slug": "today"}
    })

    return events