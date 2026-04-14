from datetime import datetime, timedelta, timezone
from factory import create_app
from services.event_master import generate_events_for_date, save_events_to_db
from models import AstroEvent
from extensions import db

IST = timezone(timedelta(hours=5, minutes=30))


# 🔥 APP INIT ONCE (IMPORTANT)
app = create_app()


def run_event_generation():
    print("🚀 Running event generation job...")

    with app.app_context():

        today = datetime.now(IST).date()
        all_events = []

        # 🔥 next 30 days generate
        for i in range(0, 30):
            date = today + timedelta(days=i)

            # 🔹 check if already exists
            exists = db.session.query(AstroEvent).filter_by(date=str(date)).first()

            if exists:
                print(f"⏭️ Skipping {date} (already exists)")
                continue

            print(f"⚙️ Generating for {date}")

            events = generate_events_for_date(date, 26.8467, 80.9462)

            if events:
                all_events.extend(events)

        if not all_events:
            print("⚠️ No events generated")
            return

        # 🔥 IMPORTANT: NO normalize here
        save_events_to_db(all_events)

        print(f"🎯 Total raw events processed: {len(all_events)}")


# 🔥 ENTRY POINT
if __name__ == "__main__":
    run_event_generation()