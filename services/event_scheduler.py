from datetime import datetime, timezone
from factory import create_app
from extensions import db
from datetime import timedelta

# Models
from modules.models_user import AppUser
from models import AstroEvent

# Services
from services.event_master import generate_events_for_date, save_events_to_db
from services.notification_engine import build_notifications, send_push_notification
from services.notification_builder import get_user_notifications   # 🔥 NEW
from models_notification_log import NotificationLog
from services.notification_engine import send_topic_notification
from modules.models_notification import UserNotification

IST = timezone(timedelta(hours=5, minutes=30))



# -------------------------------
# 🔹 TIME SLOT (IST)
# -------------------------------
def get_time_slot():
    now = datetime.now(IST)
    hour = now.hour

    if 6 <= hour < 12:
        return "morning"
    elif 17 <= hour < 22:
        return "evening"
    else:
        return "skip"


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
        # 🔹 STEP 1: Generate Events
        # ---------------------------
        today = datetime.now(IST).date()
        # 🔥 NEW
        if slot == "morning":
            target_date = today
        elif slot == "evening":
            target_date = today + timedelta(days=1)

        DEFAULT_LAT = 26.8467
        DEFAULT_LON = 80.9462

        try:
            # 🔥 STEP 1: Check DB first
            events = AstroEvent.query.filter_by(date=target_date).all()

            if events:
                print(f"✅ Events already in DB: {len(events)}")

            else:
                print("⚠️ No events in DB, generating...")

                new_events = generate_events_for_date(target_date, DEFAULT_LAT, DEFAULT_LON)

                if new_events:
                    save_events_to_db(new_events)
                    print(f"✅ {len(new_events)} events saved")

        except Exception as e:
            print(f"❌ Event generation failed: {str(e)}")
            return

        # ---------------------------
        # 🔹 STEP 2: Build Notifications
        # ---------------------------
        try:
            global_notifications = build_notifications(target_date=target_date)

            if not global_notifications:
                print("⚠️ No global notifications, checking personalized...")
                global_notifications = []

        except Exception as e:
            print(f"❌ Notification build failed: {str(e)}")
            return

        # ---------------------------
        # 🔹 SLOT FILTER
        # ---------------------------
        filtered_global = []

        for n in global_notifications:
            title = n.get("title", "").lower()

            if slot == "morning" and "today" in title:
                filtered_global.append(n)

            elif slot == "evening" and "tomorrow" in title:
                filtered_global.append(n)

        PRIORITY = {
            "festival": 1,
            "vrat": 2,
            "transit": 3,
            "muhurat": 4
        }

        filtered_global = sorted(
            filtered_global,
            key=lambda x: PRIORITY.get(x.get("data", {}).get("type"), 99)
        )

        filtered_global = filtered_global[:3]

        if not filtered_global:
            print("⚠️ No global notifications for this slot, continuing personalized...")

        # ---------------------------
        # 🔹 STEP 3A: GLOBAL (TOPIC)
        # ---------------------------
        print("🚀 Sending GLOBAL via TOPICS...")

        sent_topics = set()

        for n in filtered_global:
            event_type = n.get("data", {}).get("type")
            event_id = n.get("data", {}).get("event_id")

            if not event_type or not event_id:
                continue

            topic = f"{event_type}_{event_id}"

            if topic in sent_topics:
                continue

            success = send_topic_notification(
                topic=topic,
                title=n.get("title"),
                body=n.get("body"),
                data=n.get("data", {})
            )

            if success:
                sent_topics.add(topic)

        # ---------------------------
        # 🔹 STEP 3B: PERSONALIZED
        # ---------------------------
        BATCH_SIZE = 500
        offset = 0
        total_sent = 0

        print("📡 Sending personalized notifications...")

        while True:
            users = (
                db.session.query(AppUser)
                .limit(BATCH_SIZE)
                .offset(offset)
                .all()
            )

            if not users:
                break

            for user in users:

                # 🔥 preload logs (performance + safety)
                existing_logs = db.session.query(NotificationLog)\
                    .filter_by(user_id=user.id, slot=slot)\
                    .all()

                sent_event_ids = set(r.event_id for r in existing_logs)

                try:
                    user_notifications = get_user_notifications(
                        user,
                        global_notifications,
                        filtered_global
                    )

                    if not user_notifications:
                        continue

                    for n in user_notifications:

                        data = n.get("data", {})

                        # 🔥 SAFE EVENT ID (FINAL)
                        raw_event_id = data.get("event_id")

                        try:
                            event_id = int(raw_event_id)
                        except (TypeError, ValueError):
                            event_id = abs(hash(
                                f"{raw_event_id}_{user.id}_{data.get('mahadasha')}_{data.get('antardasha')}"
                            )) % (10**9)

                        if event_id in sent_event_ids:
                            continue

                        title = n.get("title")
                        body = n.get("body")

                        # 🔥 DEBUG
                        #print(f"🔥 NOTIF → {title} | {body}")

                        # ---------------------------
                        # 🔥 REAL SEND (FINAL)
                        # ---------------------------
                        success = False

                        token = getattr(user, "fcm_token", None)

                        if token:
                            success = send_push_notification(
                                token=token,
                                title=title,
                                body=body,
                                data=data
                            )

                        if success:
                            total_sent += 1

                            try:
                                # 🔹 LOG (existing)
                                log = NotificationLog(
                                    user_id=user.id,
                                    event_id=event_id,
                                    slot=slot
                                )
                                db.session.add(log)

                                # 🔥 SAVE USER NOTIFICATION

                                notif = UserNotification(
                                    user_id=user.id,
                                    title=title,
                                    body=body,
                                    data=data
                                )
                                db.session.add(notif)

                                sent_event_ids.add(event_id)

                            except Exception as e:
                                print(f"❌ Log/Save failed: {str(e)}")
                except Exception as e:
                    print(f"❌ Failed for user {user.id}: {str(e)}")

            offset += BATCH_SIZE

        # ---------------------------
        # 🔹 FINAL COMMIT
        # ---------------------------
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"❌ Final commit failed: {str(e)}")

        print(f"✅ Personalized sent: {total_sent}")