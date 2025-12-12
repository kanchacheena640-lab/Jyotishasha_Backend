from datetime import datetime
from extensions import db
from notifications.notification_models import NotificationJob
import random

# =================================================
# GENERIC NOTIFICATION VARIATIONS
# =================================================

HOROSCOPE_VARIATIONS = [
    (
        "🌙 Today’s Planetary Signal",
        "Look which planet is aspecting you today — read world’s 1st horoscope based on real NASA planetary data.",
        "🌙 आज का प्रभावी ग्रह",
        "आज कौन सा ग्रह आपको प्रभावित कर रहा है — NASA ग्रह डेटा पर आधारित दुनिया का पहला राशिफल पढ़ें।"
    ),
    (
        "🔭 Cosmic Influence Today",
        "A planet is directly influencing your chart today. Tap to see its exact effect.1st personalized horoscope.",
        "🔭 आज का ब्रह्मांडीय प्रभाव",
        "आज एक ग्रह आपकी कुंडली को प्रभावित कर रहा है। इसका सटीक असर जानने के लिए देखें ग्रहों की वर्तमान चाल पर आधारित राशिफल"
    ),
    (
        "🪐 Planetary Watch",
        "Today’s planetary aspect may shape your decisions. Check before you act.",
        "🪐 ग्रह दृष्टि संकेत",
        "आज की ग्रह दृष्टि आपके फैसलों को प्रभावित कर सकती है। आगे बढ़ने से पहले देखें।"
    ),
]

PANCHANG_VARIATIONS = [
    (
        "⚠️ Panchang Alert",
        "Know which time today is prohibited for important tasks. Avoid wrong timing.",
        "⚠️ आज का पंचांग ",
        "आज कौन सा समय महत्वपूर्ण कार्यों के लिए वर्जित है — जानना ज़रूरी है।"
    ),
    (
        "⏳ Muhurtha Warning",
        "Certain hours today are not suitable for new beginnings. Check Panchang now.",
        "⏳ मुहूर्त चेतावनी",
        "आज कुछ समय नए काम के लिए उपयुक्त नहीं है। पंचांग अवश्य देखें।"
    ),
    (
        "📿 Time Caution Today",
        "Wrong timing can delay success. See today’s Panchang before acting.",
        "📿 समय सावधानी",
        "गलत समय सफलता में देरी कर सकता है। आज का पंचांग देखें।"
    ),
]

DARSHAN_VARIATIONS = [
    (
        "🕉️ Today’s Darshan",
        "Seek blessings of today’s ruling deity. One mantra can change your mindset.",
        "🕉️ आज का दर्शन",
        "आज के देवता का स्मरण करें। एक मंत्र मनःस्थिति बदल सकता है।"
    ),
    (
        "🙏 Divine Reminder",
        "A moment of devotion today can bring inner stability.",
        "🙏 दिव्य स्मरण",
        "आज थोड़ी सी भक्ति मानसिक स्थिरता ला सकती है।"
    ),
]

# =================================================
# DAILY RUNNER
# =================================================

def run_daily_notifications():
    now = datetime.utcnow()

    # rotate category by weekday
    weekday = now.weekday() % 3

    if weekday == 0:
        title, body, title_hi, body_hi = random.choice(HOROSCOPE_VARIATIONS)
    elif weekday == 1:
        title, body, title_hi, body_hi = random.choice(PANCHANG_VARIATIONS)
    else:
        title, body, title_hi, body_hi = random.choice(DARSHAN_VARIATIONS)

    db.session.add(NotificationJob(
        title=title,
        body=body,
        title_hi=title_hi,
        body_hi=body_hi,
        audience={"mode": "all"},
        scheduled_at=now,
        status="pending"
    ))

    db.session.commit()
