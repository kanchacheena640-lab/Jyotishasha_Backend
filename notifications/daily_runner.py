from datetime import datetime
from extensions import db
from notifications.notification_models import NotificationJob

from services.daily_horoscope import get_daily_horoscope_summary
from services.panchang_service import get_today_panchang


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
    # 1️⃣ Daily Horoscope
    # =================================================
    horo_en, horo_hi = get_daily_horoscope_summary()

    job1 = NotificationJob(
        title="🌙 Today's Horoscope",
        body=horo_en,
        title_hi="🌙 आज का राशिफल",
        body_hi=horo_hi,
        audience={"mode": "all"},
        scheduled_at=now,
        status="pending"
    )
    db.session.add(job1)

    # =================================================
    # 2️⃣ Daily Panchang
    # =================================================
    p = get_today_panchang()

    job2 = NotificationJob(
        title="📿 Today's Panchang",
        body=f"Tithi: {p['tithi']} | Nakshatra: {p['nakshatra']}",
        title_hi="📿 आज का पंचांग",
        body_hi=f"तिथि: {p['tithi_hi']} | नक्षत्र: {p['nakshatra_hi']}",
        audience={"mode": "all"},
        scheduled_at=now,
        status="pending"
    )
    db.session.add(job2)

    # =================================================
    # 3️⃣ Daily Darshan
    # =================================================
    devta_hi, mantra = DAY_DEVTA[now.weekday()]

    job3 = NotificationJob(
        title="🕉️ Today's Darshan",
        body=f"{devta_hi} — {mantra}",
        title_hi="🕉️ आज के देवता का दर्शन",
        body_hi=f"{devta_hi} — {mantra}",
        audience={"mode": "all"},
        scheduled_at=now,
        status="pending"
    )
    db.session.add(job3)

    db.session.commit()
