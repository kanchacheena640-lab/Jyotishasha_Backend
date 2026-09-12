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
def send_push_notification(token, title, body, data=None, android_tag=None, *, app_user_id=None):
    """
    N-FIX-2B -- `app_user_id` is a new, OPTIONAL, keyword-only parameter
    (default None): the public contract (positional token/title/body/
    data/android_tag, boolean return) is completely unchanged for any
    existing caller that doesn't pass it. When supplied, it enables safe
    invalid-token cleanup on a definitively-dead token (see below) --
    when omitted, this function behaves byte-for-byte as before (still
    retries twice, still returns True/False, just never clears a token,
    exactly like today). Every real production caller (services/
    event_scheduler.py, modules/alerts/alert_delivery_service.py,
    notifications/notification_routes.py) already has the AppUser id in
    scope at its own call site and has been updated to pass it.

    Token invalidation reuses notifications/firebase_transport.py's own
    already-proven classification/clearing (Campaign C) rather than a
    second, potentially-drifting copy -- see is_invalid_token_error()/
    clear_invalid_fcm_token() there. Race-safe: the clear only applies
    when AppUser.id == app_user_id AND AppUser.fcm_token == token BOTH
    still match at UPDATE time, so a token this recipient has since
    refreshed is never wrongly cleared -- never looked up by token alone.

    The existing two-attempt retry loop is completely unchanged: this
    only adds a side effect (clearing a proven-dead token) AFTER both
    attempts are exhausted, classified from whichever exception the
    last attempt raised -- it does not skip/shorten a retry for a token
    already known to be dead, exactly preserving today's behavior.
    """
    try:
        if not token:
            return False

        # 🔥 FCM requires string values
        safe_data = {k: str(v) for k, v in (data or {}).items()}

        # android_tag is opt-in (None by default -- every existing caller
        # is unaffected). Only the Morning Panchang send passes it, so it
        # can carry an Android notification tag without touching title,
        # body, data, or any other notification type.
        android_config = (
            messaging.AndroidConfig(
                notification=messaging.AndroidNotification(tag=android_tag)
            )
            if android_tag else None
        )

        last_exception = None
        for attempt in range(2):  # retry 2 times
            try:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=title,
                        body=body
                    ),
                    data=safe_data,
                    token=token,
                    android=android_config
                )

                response = messaging.send(message)
                print(f"✅ Sent → {response}")
                return True

            except Exception as e:
                last_exception = e
                print(f"⚠️ Retry {attempt + 1} failed: {str(e)}")

        # N-FIX-2B -- both attempts exhausted. If the caller identified
        # who this was for AND the failure is one of the two definitively
        # invalid-token types (never a transient/unknown one), clear the
        # dead token so future runs stop retrying it forever. A cleared
        # token is self-healing on the client (FcmTokenManager re-uploads
        # the current token on every authenticated app start), so this
        # never has an identity/account side effect.
        if app_user_id is not None and last_exception is not None:
            from notifications.firebase_transport import is_invalid_token_error, clear_invalid_fcm_token
            if is_invalid_token_error(last_exception):
                clear_invalid_fcm_token(app_user_id, token)

        return False

    except Exception as e:
        print(f"❌ Error sending notification: {str(e)}")
        return False

# -------------------------------
# 🔹 SEND DATA-ONLY (silent) NOTIFICATION
# -------------------------------
def send_data_only_notification(token, data=None):
    """
    Sends a data-only FCM message -- no `notification` block, no title,
    no body. Used for silent device-side signals (e.g. the 5 PM Panchang
    dismiss). Deliberately a separate function from send_push_notification()
    so no visible-notification send path can accidentally lose its
    notification block.
    """
    try:
        if not token:
            return False

        safe_data = {k: str(v) for k, v in (data or {}).items()}

        message = messaging.Message(
            data=safe_data,
            token=token
        )

        response = messaging.send(message)
        print(f"✅ Data-only sent → {response}")
        return True

    except Exception as e:
        print(f"❌ Error sending data-only notification: {str(e)}")
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