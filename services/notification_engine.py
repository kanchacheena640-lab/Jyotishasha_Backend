from datetime import datetime, timedelta, timezone
from models import AstroEvent
from firebase_admin import messaging
from collections import defaultdict

# 🔥 GLOBAL IST
IST = timezone(timedelta(hours=5, minutes=30))


# -------------------------------
# 🔹 GET TODAY DATE
# -------------------------------
def get_today_date():
    return datetime.now(IST).date()


# -------------------------------
# 🔹 SAME-DAY EVENTS
# -------------------------------
def get_today_notifications():
    today = get_today_date()

    return AstroEvent.query.filter(
        AstroEvent.date == today
    ).all()


# -------------------------------
# 🔹 BUILD NOTIFICATIONS
# -------------------------------
def build_notifications(target_date=None):
    notifications = []

    if not target_date:
        target_date = get_today_date()

    print(f"\n🧪 TARGET DATE: {target_date}")

    # 🔹 GET TODAY EVENTS
    today_events = AstroEvent.query.filter(
        AstroEvent.date == target_date
    ).all()

    print(f"🧪 Today events count: {len(today_events)}")

    # 🔹 GET PRE-EVENTS
    all_db_events = AstroEvent.query.all()
    print(f"🧪 Total DB events: {len(all_db_events)}")

    pre_events = []

    for event in all_db_events:
        if event.notify_before_days is None:
            continue

        try:
            event_date = event.date

            if isinstance(event_date, str):
                event_date = datetime.strptime(event_date, "%Y-%m-%d").date()

            notify_date = event_date - timedelta(days=event.notify_before_days)

            if notify_date == target_date:
                print(f"📅 Pre-event matched: {event.name}")
                pre_events.append(event)

        except Exception as e:
            print(f"❌ Pre-event error (event {event.id}): {str(e)}")

    print(f"🧪 Pre events count: {len(pre_events)}")

    # 🔹 MERGE
    all_events = today_events + pre_events
    print(f"🧪 Total events after merge: {len(all_events)}")

    all_events = deduplicate_events(all_events)
    print(f"🧪 After dedup: {len(all_events)}")

    all_events = sort_by_priority(all_events)

    # 🔹 BUILD NOTIFICATIONS
    for e in all_events:
        event_type = (e.type or "").lower().strip()

        print(f"🔍 Processing: {e.name} | type={event_type}")

        # 🔥 ONLY VALIDATION (no normalization here)
        if event_type not in ["festival", "vrat", "transit", "muhurat"]:
            print(f"⛔ Skipped (invalid type): {e.type}")
            continue

        # 🔥 safe date handling
        event_date = e.date
        if isinstance(event_date, str):
            event_date = datetime.strptime(event_date, "%Y-%m-%d").date()

        is_today = (event_date == target_date)

        print(f"✅ Adding notification: {e.name} | type={event_type} | is_today={is_today}")

        notifications.append({
            "title": f"{e.name} {'Today 🪔' if is_today else 'Tomorrow 🔔'}",
            "body": f"{e.name} का {'आज विशेष महत्व है' if is_today else 'कल है, अभी तैयारी करें'}",
            "data": {
                "type": event_type,
                "event_id": str(e.id),
                "date": str(event_date)
            }
        })

    print(f"🧪 FINAL notifications built: {len(notifications)}\n")

    return notifications
# -------------------------------
# 🔹 DEDUPLICATION
# -------------------------------
def deduplicate_events(events):
    seen = set()
    unique = []

    for e in events:
        key = (e.name, e.date, e.type)

        if key not in seen:
            seen.add(key)
            unique.append(e)

    return unique


# -------------------------------
# 🔹 PRIORITY SORT
# -------------------------------
PRIORITY_ORDER = {
    "festival": 1,
    "vrat": 2,
    "transit": 3,
    "muhurat": 4,
}

def sort_by_priority(events):
    return sorted(
        events,
        key=lambda e: PRIORITY_ORDER.get(
            (e.type or "").lower().strip(), 
            99
        )
    )

# -------------------------------
# 🔹 SEND PUSH
# -------------------------------
def send_push_notification(token, title, body, data=None):
    try:
        if not token:
            return False

        # 🔥 FCM requires string values
        safe_data = {k: str(v) for k, v in (data or {}).items()}

        for attempt in range(2):  # retry 2 times
            try:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=title,
                        body=body
                    ),
                    data=safe_data,
                    token=token
                )

                response = messaging.send(message)
                print(f"✅ Sent → {response}")
                return True

            except Exception as e:
                print(f"⚠️ Retry {attempt + 1} failed: {str(e)}")

        return False

    except Exception as e:
        print(f"❌ Error sending notification: {str(e)}")
        return False
    
# -------------------------------
# 🔹 SEND TOPIC NOTIFICATION
# -------------------------------
def send_topic_notification(topic, title, body, data=None):
    try:
        safe_data = {k: str(v) for k, v in (data or {}).items()}
        
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            data=safe_data,
            topic=topic
        )

        response = messaging.send(message)
        print(f"✅ Topic Sent → {topic} | {response}")
        return True

    except Exception as e:
        print(f"❌ Topic send error: {str(e)}")
        return False