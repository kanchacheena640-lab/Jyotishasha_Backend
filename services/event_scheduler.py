import os
from datetime import datetime, timezone, timedelta, time
from factory import create_app
from extensions import db

# Models
from modules.models_user import AppUser
from models import AstroEvent

# Services
from services.event_master import generate_events_for_date, save_events_to_db
from services.notification_engine import build_notifications, send_push_notification, send_data_only_notification
from services.notification_builder import get_user_notifications, build_event_content
from services.notification_engine import send_topic_notification
from notifications.notification_models import UserNotification, NotificationLog
from services.event_adapters.festival_adapter import normalize_events
from services.relative_day import get_relative_day, TOMORROW
from services.notification_lifecycle import (
    expiry_for_astro_event_notification,
    expiry_for_same_day_notification,
    expiry_for_dasha_pre_notification,
)

IST = timezone(timedelta(hours=5, minutes=30))

# The morning Panchang notification auto-dismisses (Bell + tray) at this
# IST hour on the same day it was sent, even if the user never taps it.
PANCHANG_AUTO_DISMISS_HOUR_IST = 17  # 5:00 PM


# -------------------------------
# 🔹 TIME SLOT (explicit, from GitHub Actions)
# -------------------------------
# The scheduler never guesses morning/evening from the clock. GitHub
# Actions is the single source of truth for which slot is running -- it
# knows which of its two schedule entries fired (or which slot a manual
# workflow_dispatch requested) and passes that through the
# NOTIFICATION_SLOT environment variable (see .github/workflows/notifications.yml).
# Anything other than an explicit "morning"/"evening" is treated as "skip".
def get_time_slot():
    slot = os.getenv("NOTIFICATION_SLOT", "").strip().lower()

    if slot in ("morning", "evening"):
        return slot

    return "skip"


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
                if event_date == target_date:
                    filtered_global.append(n)

        # 🔥 NO FALLBACK: the generic "Aaj ka Din Mahatvapurn Hai" notice
        # is removed (v1.1 freeze). If nothing eligible was selected,
        # filtered_global simply stays empty -- Step 5A and Step 5B below
        # both no-op gracefully on an empty list, so this run correctly
        # sends nothing rather than a placeholder notification.

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
                        normalized_events   # ✔ DB events
                    )

                    seen_events = set()
                    user_sent = 0

                    for n in user_notifications:
                        data = n.get("data", {}) or {}

                        ntype = data.get("type", "general")
                        raw_event_id = data.get("event_id", "0")

                        # 🔥 N2 -- LIFECYCLE / VISIBILITY EXPIRY. Every
                        # branch below only ever WRITES expires_at; the
                        # Bell query that reads it
                        # (notifications/user_notification_routes.py,
                        # `expires_at IS NULL OR expires_at > now`) is
                        # unchanged -- it already correctly consumes
                        # whatever value lands here. See
                        # services/notification_lifecycle.py for the
                        # actual policy/reasoning per type.
                        expires_at = None
                        android_tag = None

                        if ntype == "panchang":
                            # Unchanged (pre-N2): same-day utility,
                            # expires at PANCHANG_AUTO_DISMISS_HOUR_IST,
                            # also carries the cutoff in the payload so
                            # the app can clear the tray even if never
                            # tapped (see PanchangDismissBridge).
                            expires_at = datetime.combine(
                                target_date,
                                time(hour=PANCHANG_AUTO_DISMISS_HOUR_IST),
                                tzinfo=IST
                            ).astimezone(timezone.utc).replace(tzinfo=None)
                            data["auto_dismiss_at"] = expires_at.isoformat() + "Z"
                            android_tag = "panchang_morning"

                        elif ntype in ("event", "transit", "panchak"):
                            # All three are backed by a real AstroEvent
                            # row -- raw_event_id IS that AstroEvent's own
                            # id for all three (see
                            # services/notification_builder.py's EVENT/
                            # TRANSIT/PANCHAK sections), so its actual
                            # .date is available via the SAME events_by_id
                            # map STEP 5A already built -- never guessed,
                            # never re-derived from target_date (which
                            # would be wrong for a late-running job).
                            astro_event = (
                                events_by_id.get(int(raw_event_id))
                                if str(raw_event_id).isdigit() else None
                            )
                            if astro_event is not None:
                                # `event`'s own content says "Tomorrow" only
                                # for its evening-slot reminder
                                # (build_event_content()); `panchak` carries
                                # no today/tomorrow wording, so it always
                                # uses the "valid through end of its own day"
                                # rule. `transit` (N3) is now ALWAYS a T-1
                                # "tomorrow" framed notice (see
                                # notification_builder.py's TRANSIT section --
                                # it only ever selects a transit dated
                                # TOMORROW), so it must always expire the
                                # instant that transit day begins, same as
                                # event's forward-looking case.
                                is_forward_looking = (
                                    ntype == "transit"
                                    or (
                                        ntype == "event"
                                        and get_relative_day(astro_event.date) == TOMORROW
                                    )
                                )
                                expires_at = expiry_for_astro_event_notification(
                                    event_date=astro_event.date,
                                    is_forward_looking=is_forward_looking,
                                )
                            # else: astro_event lookup failed (should not
                            # happen -- defensive only) -- expires_at
                            # stays None, matching this notification's
                            # pre-N2 behavior rather than guessing.

                        elif ntype == "dasha":
                            # Same-day "phase started today" announcement
                            # -- no AstroEvent backing; anchored to the
                            # REAL calendar day this specific notification
                            # was built on (services/personalization_engine.py
                            # ::get_users_for_dasha_change() reads
                            # datetime.now(IST).date() internally, NOT
                            # target_date -- recomputed the same way here
                            # so an evening-slot run still expires this
                            # correctly rather than one day too late).
                            expires_at = expiry_for_same_day_notification(
                                generated_on=datetime.now(IST).date(),
                            )

                        elif ntype == "dasha_pre":
                            # N2.1 -- resolves the N2 STOP case. The
                            # authoritative transition date
                            # (UserDashaTimeline.start_date) is now
                            # surfaced through
                            # get_users_for_dasha_change()'s own return
                            # dict and threaded into this notification's
                            # data["start_date"]
                            # (services/notification_builder.py) --
                            # never recomputed or guessed here, only
                            # parsed back out.
                            raw_start_date = data.get("start_date")
                            if raw_start_date:
                                try:
                                    transition_date = datetime.strptime(
                                        raw_start_date, "%Y-%m-%d",
                                    ).date()
                                    expires_at = expiry_for_dasha_pre_notification(
                                        transition_date=transition_date,
                                    )
                                except ValueError:
                                    pass  # malformed date string -- defensive
                                          # only; stays None rather than guessing
                            # else: no start_date in payload (should not
                            # happen post-N2.1) -- expires_at stays None
                            # rather than guessing.

                        # Every other type (admin/marketing broadcasts --
                        # a different code path, notifications/
                        # notification_service.py, not this loop at all --
                        # and any future/unrecognized type reaching this
                        # loop) is intentionally left at expires_at = None:
                        # per N2 Step 2's own instruction, transactional/
                        # unclassified notifications must not be given a
                        # short astrology-style expiry.

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
                                data=data,
                                android_tag=android_tag
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
                                is_read=False,
                                expires_at=expires_at
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


# -------------------------------
# 🔹 PANCHANG DISMISS JOB (5 PM IST)
# -------------------------------
def run_panchang_dismiss_job():
    """
    Sends a silent, data-only FCM message telling each recipient's device
    to dismiss today's Morning Panchang notification (tray + Bell), even
    if it was never tapped. Recipients are read directly off
    NotificationLog -- the same ledger run_daily_event_job() writes to
    only after a successful morning Panchang send -- so this can only
    ever reach users who actually received that notification today.
    Entirely separate code path from run_daily_event_job(): touches no
    other notification type (Festival/Vrat/Transit/Muhurat), no scheduler
    state, no slot detection.
    """
    print("🚀 Running Panchang dismiss job...")

    app = create_app()

    with app.app_context():
        today = datetime.now(IST).date()

        panchang_event = AstroEvent.query.filter_by(
            type="panchang",
            date=today
        ).first()

        if not panchang_event:
            print("⚠️ No Panchang event for today -- nothing to dismiss")
            return

        event_id = f"panchang_{panchang_event.id}"

        # 🔹 Only users with a logged, successful Morning Panchang send today
        logs = NotificationLog.query.filter_by(
            event_id=event_id,
            slot="morning"
        ).all()

        if not logs:
            print("⚠️ No Morning Panchang recipients today -- nothing to dismiss")
            return

        recipient_ids = {log.user_id for log in logs}

        users = AppUser.query.filter(AppUser.id.in_(recipient_ids)).all()

        dismiss_data = {
            "action": "dismiss_panchang",
            "tag": "panchang_morning"
        }

        sent = 0

        for user in users:
            token = getattr(user, "fcm_token", None)
            if not token:
                continue

            success = send_data_only_notification(
                token=token,
                data=dismiss_data
            )

            if success:
                sent += 1

        print(f"✅ Panchang dismiss sent: {sent}/{len(users)}")