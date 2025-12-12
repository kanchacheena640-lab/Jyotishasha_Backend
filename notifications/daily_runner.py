import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from extensions import db
from notifications.notification_models import NotificationJob

# ✅ Correct imports (existing project structure)
from services.personalized.personalized_daily_engine import generate_personalized_daily
from services.personalized.personalized_daily_text_builder import build_daily_notification_text
from services.panchang_engine import get_today_panchang


DAY_DEVTA = {
    0: ("शिव जी", "Om Namah Shivaya"),        # Monday
    1: ("हनुमान जी", "Om Hanumate Namah"),    # Tuesday
    2: ("गणेश जी", "Om Gan Ganapataye Namah"),
    3: ("विष्णु जी", "Om Namo Narayanaya"),
    4: ("लक्ष्मी जी", "Om Shreem Mahalakshmyai Namah"),
    5: ("शनि देव", "Om Sham Shanicharaya Namah"),
    6: ("सूर्य देव", "Om Suryaya Namah"),
}


def run_daily_notifications():
    now = datetime.utcnow()

    # =================================================
    # 1️⃣ Daily Horoscope (Personalized Engine)
    # =================================================
    daily_data = generate_personalized_daily()
    horo_en, horo_hi = build_daily_notification_text(daily_data)

    db.session.add(NotificationJob(
        title="🌙 Today's Horoscope",
        body=horo_en,
        title_hi="🌙 आज का राशिफल",
        body_hi=horo_hi,
        audience={"mode": "all"},
        scheduled_at=now,
        status="pending"
    ))

    # =================================================
    # 2️⃣ Daily Panchang
    # =================================================
    p = get_today_panchang()

    db.session.add(NotificationJob(
        title="📿 Today's Panchang",
        body=f"Tithi: {p['tithi']} | Nakshatra: {p['nakshatra']}",
        title_hi="📿 आज का पंचांग",
        body_hi=f"तिथि: {p['tithi_hi']} | नक्षत्र: {p['nakshatra_hi']}",
        audience={"mode": "all"},
        scheduled_at=now,
        status="pending"
    ))

    # =================================================
    # 3️⃣ Daily Darshan
    # =================================================
    devta_hi, mantra = DAY_DEVTA[now.weekday()]

    db.session.add(NotificationJob(
        title="🕉️ Today's Darshan",
        body=f"{devta_hi} — {mantra}",
        title_hi="🕉️ आज के देवता का दर्शन",
        body_hi=f"{devta_hi} — {mantra}",
        audience={"mode": "all"},
        scheduled_at=now,
        status="pending"
    ))

    db.session.commit()
