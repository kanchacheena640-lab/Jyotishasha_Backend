from datetime import datetime, timezone, timedelta
from factory import create_app
from extensions import db

# Models
from modules.models_user import AppUser
from models import AstroEvent

# Services
from services.event_master import generate_events_for_date, save_events_to_db
from services.notification_engine import build_notifications, send_push_notification
from services.notification_builder import get_user_notifications, build_event_content
from services.notification_engine import send_topic_notification
from notifications.notification_models import UserNotification, NotificationLog
from services.event_adapters.festival_adapter import normalize_events

IST = timezone(timedelta(hours=5, minutes=30))


# -------------------------------
# 🔹 TIME SLOT (IST)
# -------------------------------
def get_time_slot():
    return "morning"


# -------------------------------
# 🔹 MAIN JOB
# -------------------------------
def run_daily_event_job():
    slot = get_time_slot()
    print("🚀 Running daily event job...")

    if slot == "skip":
        print("⏭️ Skipping run (outside time slot)")
        return

    print(f"🕒 Time Slot: {slot}")

    app = create_app()

    with app.app_context():

        # ---------------------------
        # 🔹 STEP 1: DATE LOGIC
        # ---------------------------
        today = datetime.now(IST).date()

        if slot == "morning":
            target_date = today
        else:
            target_date = today + timedelta(days=1)

        DEFAULT_LAT = 26.8467
        DEFAULT_LON = 80.9462

        # ---------------------------
        # 🔹 STEP 2: GENERATE + SAVE EVENTS (FIXED)
        # ---------------------------
        try:
            raw_events = []

            for d in [target_date, target_date + timedelta(days=1)]:
                events = generate_events_for_date(d, DEFAULT_LAT, DEFAULT_LON)

                if events:
                    raw_events.extend(events)

                    # 🔥 CRITICAL: save to DB
                    save_events_to_db(events)

            if not raw_events:
                print("⚠️ No raw events generated")

            # 🔥 ALWAYS fetch from DB (no condition)
            normalized_events = AstroEvent.query.filter(
                AstroEvent.date.in_([target_date, target_date + timedelta(days=1)])
            ).all()

            print(f"🔥 DEBUG: DB events count = {len(normalized_events)}")

        except Exception as e:
            print(f"❌ Event generation failed: {str(e)}")
            return

        # ---------------------------
        # 🔹 STEP 3: BUILD NOTIFICATIONS
        # ---------------------------
        # build_notifications() is only used for EVENT SELECTION now
        # (which AstroEvents are relevant today, incl. notify_before_days
        # pre-events) -- its own title/body are superseded below, in
        # STEP 5A, by notification_builder.build_event_content(), the
        # single owner of AstroEvent notification wording.
        try:
            global_notifications = build_notifications(target_date=target_date)
        except Exception as e:
            print(f"❌ Notification build failed: {str(e)}")
            return

        # ---------------------------
        # 🔹 STEP 4: SLOT FILTER
        # ---------------------------
        filtered_global = []

        for n in global_notifications:
            data = n.get("data", {})
            event_date = data.get("date")

            if not event_date:
                continue

            try:
                event_date = datetime.strptime(event_date, "%Y-%m-%d").date()
            except:
                continue

            if slot == "morning":
                if event_date == target_date:
                    filtered_global.append(n)

            elif slot == "evening":
                if event_date == target_date + timedelta(days=1):
                    filtered_global.append(n)

        # 🔥 FALLBACK (IMPORTANT)
        if not filtered_global:
            print("⚠️ No events → sending fallback")

            fallback = {
                "title": "📿 Aaj ka Din Mahatvapurn Hai",
                "body": "Shubh kaam karne jaa rahe hain to shubh muhurat zarur dekhiye. Aaj ka rashifal bhi check karein.",
                "data": {
                    "type": "general",
                    "event_id": "0",
                    "date": str(target_date)
                }
            }

            filtered_global = [fallback]

        # ---------------------------
        # 🔹 PRIORITY SORT
        # ---------------------------
        PRIORITY = {
            "festival": 1,
            "vrat": 2,
            "transit": 3,
            "muhurat": 4
        }

        filtered_global = sorted(
            filtered_global,
            key=lambda x: PRIORITY.get(x.get("data", {}).get("type"), 99)
        )[:3]

        # ---------------------------
        # 🔹 STEP 5A: GLOBAL SEND
        # ---------------------------
        print("🚀 Sending GLOBAL via TOPICS...")

        # AstroEvent-backed topics get their title/body from
        # notification_builder.build_event_content() -- the same function
        # STEP 5B uses for the personal/Bell send -- so a topic broadcast
        # can never disagree with the Bell about the same event again.
        events_by_id = {e.id: e for e in normalized_events}

        sent_topics = set()

        for n in filtered_global:
            data = n.get("data", {}) or {}
            event_type = data.get("type")
            event_id = data.get("event_id")

            if not event_type or not event_id:
                continue

            topic = f"{event_type}_{event_id}"

            if topic in sent_topics:
                continue

            if event_type == "general":
                # No backing AstroEvent -- the application-wide generic
                # fallback isn't notification_builder's to own.
                title, body, payload = n.get("title"), n.get("body"), data
            else:
                astro_event = events_by_id.get(int(event_id)) if str(event_id).isdigit() else None
                content = build_event_content(astro_event) if astro_event else None

                if not content:
                    continue

                title, body, payload = content["title"], content["body"], content["data"]

            success = send_topic_notification(
                topic=topic,
                title=title,
                body=body,
                data=payload
            )

            if success:
                sent_topics.add(topic)

       # ---------------------------
        # 🔹 STEP 5B: PERSONALIZED
        # ---------------------------
        total_sent = 0
        BATCH_SIZE = 500
        offset = 0

        print("📡 Sending personalized notifications...")

        while True:
            users = db.session.query(AppUser).limit(BATCH_SIZE).offset(offset).all()
            if not users:
                break

            for user in users:
                try:
                    user_notifications = get_user_notifications(
                        user,
                        normalized_events,   # ✔ DB events
                        filtered_global      # ✔ notifications with data
                    )

                    seen_events = set()
                    user_sent = 0

                    for n in user_notifications:
                        data = n.get("data", {}) or {}

                        ntype = data.get("type", "general")
                        raw_event_id = data.get("event_id", "0")

                        # 🔥 SINGLE NOTIFICATION IDENTITY
                        # AstroEvent-based notifications ("event" type) are
                        # produced by exactly one code path now (see
                        # notification_builder.py's EVENT section), so the
                        # AstroEvent's own id is the whole identity -- no
                        # type prefix needed, and none of the type-prefixed
                        # schemes below can ever collide with it since
                        # AstroEvent.id is a single unique primary key.
                        if ntype == "event":
                            event_id = raw_event_id
                        else:
                            event_id = f"{ntype}_{raw_event_id}"

                        unique_key = f"{event_id}_{slot}"

                        # 🔥 LOCAL DEDUP (same loop)
                        if unique_key in seen_events:
                            continue
                        seen_events.add(unique_key)

                        # 🔥 DB DEDUP (retry / cron safe)
                        existing_log = NotificationLog.query.filter_by(
                            user_id=user.id,
                            event_id=event_id,
                            slot=slot
                        ).first()

                        if existing_log:
                            continue

                        success = False
                        token = getattr(user, "fcm_token", None)

                        if token:
                            success = send_push_notification(
                                token=token,
                                title=n.get("title"),
                                body=n.get("body"),
                                data=data
                            )

                        if success:
                            total_sent += 1
                            user_sent += 1

                            # 🔹 SAVE LOG
                            db.session.add(NotificationLog(
                                user_id=user.id,
                                event_id=event_id,
                                slot=slot
                            ))

                            # 🔹 SAVE USER NOTIFICATION (Bell UI)
                            db.session.add(UserNotification(
                                user_id=user.id,
                                title=n.get("title"),
                                body=n.get("body"),
                                data=data,
                                is_read=False
                            ))

                    # 🔥 Commit ALL of this user's notifications first --
                    # retention must never run against uncommitted/in-flight
                    # rows from this same loop (that race is what silently
                    # deleted a just-sent notification before the Bell
                    # could ever read it).
                    if user_sent:
                        db.session.commit()

                        # 🔥 KEEP ONLY LAST 10 NOTIFICATIONS PER USER
                        # Runs ONCE per user, after their inserts are
                        # durable, ordered by a tiebreaker (id) so ties on
                        # created_at (same-transaction timestamps are
                        # identical under Postgres) can't make the trim
                        # non-deterministic.
                        old_notifications = db.session.query(UserNotification)\
                            .filter_by(user_id=user.id)\
                            .order_by(
                                UserNotification.created_at.desc(),
                                UserNotification.id.desc()
                            )\
                            .offset(10)\
                            .all()

                        for old in old_notifications:
                            db.session.delete(old)

                        db.session.commit()

                except Exception as e:
                    db.session.rollback()
                    print(f"❌ Failed for user {user.id}: {str(e)}")

            offset += BATCH_SIZE

        if total_sent == 0:
            print("⚠️ ALERT: No notifications sent")

        print(f"✅ Personalized sent: {total_sent}")