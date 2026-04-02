from factory import create_app
from models import AstroEvent

app = create_app()

with app.app_context():
    events = AstroEvent.query.limit(2).all()

    notifications = []

    for e in events:
        notifications.append({
            "title": f"{e.name} Today 🪔",
            "body": f"{e.name} का आज विशेष महत्व है",
            "data": {
                "type": e.type,
                "event_id": str(e.id)
            }
        })

    if not notifications:
        print("⚠️ No notifications generated")
    else:
        print(f"🔔 Total Notifications: {len(notifications)}\n")

        for i, n in enumerate(notifications, 1):
            print(f"--- Notification {i} ---")
            print("Title:", n["title"])
            print("Body :", n["body"])
            print("Data :", n["data"])
            print()