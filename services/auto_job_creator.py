from datetime import datetime, timezone
from extensions import db
from notifications.notification_models import NotificationJob
from models import AstroEvent


def create_jobs_for_today():

    today = datetime.now(timezone.utc).date()

    events = AstroEvent.query.filter(
        AstroEvent.date == today
    ).all()

    created = 0

    for event in events:

        existing = NotificationJob.query.filter_by(
            payload={"event_id": event.id}
        ).first()

        if existing:
            continue

        job = NotificationJob(
            title=event.name,
            body=event.meta.get("description") if event.meta else "Important event today",
            type=event.type,
            audience={"mode": "all"},
            payload={
                "event_id": event.id,
                "type": event.type
            },
            scheduled_at=datetime.combine(
                event.date,
                event.notify_time or datetime.now(timezone.utc).time()
            )
        )

        db.session.add(job)
        created += 1

    db.session.commit()

    return created