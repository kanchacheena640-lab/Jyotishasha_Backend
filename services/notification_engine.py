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
        AstroEvent.date == str(today)
    ).all()


# -------------------------------
# 🔹 PRE-EVENT
# -------------------------------
def get_pre_notifications():
    today = get_today_date()

    events = AstroEvent.query.all()
    notify_list = []

    for event in events:
        if not event.notify_before_days:
            continue

        try:
            notify_date = event.date - timedelta(days=event.notify_before_days)

            if notify_date == today:
                notify_list.append(event)

        except Exception as e:
            print(f"❌ Pre-event calc error (event {event.id}): {str(e)}")

    return notify_list


# -------------------------------
# 🔹 BUILD NOTIFICATIONS
# -------------------------------
def build_notifications():
    notifications = []

    # 🔹 GET EVENTS
    today_events = get_today_notifications()
    pre_events = get_pre_notifications()

    # 🔹 MERGE + DEDUP
    all_events = today_events + pre_events
    all_events = deduplicate_events(all_events)

    # 🔹 SORT BY PRIORITY
    all_events = sort_by_priority(all_events)

    # 🔹 BUILD
    today = get_today_date()

    for e in all_events:

        if e.type not in ["festival", "transit", "vrat", "muhurat"]:
            continue

        # SAME DAY
        if e.date == today:
            notifications.append({
                "title": f"{e.name} Today 🪔",
                "body": f"{e.name} का आज विशेष महत्व है",
                "data": {
                    "type": e.type,
                    "event_id": str(e.id)
                }
            })

        # PRE EVENT
        else:
            notifications.append({
                "title": f"{e.name} Tomorrow 🔔",
                "body": f"{e.name} कल है, अभी तैयारी करें",
                "data": {
                    "type": e.type,
                    "event_id": str(e.id)
                }
            })

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
    return sorted(events, key=lambda e: PRIORITY_ORDER.get(e.type, 99))


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
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            data=data or {},
            topic=topic
        )

        response = messaging.send(message)
        print(f"✅ Topic Sent → {topic} | {response}")
        return True

    except Exception as e:
        print(f"❌ Topic send error: {str(e)}")
        return False