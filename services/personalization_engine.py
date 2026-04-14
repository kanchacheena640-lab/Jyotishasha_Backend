from modules.models_user import AppUser
from datetime import datetime, timezone, timedelta, date
from modules.models_user import UserDashaTimeline
from services.notification_engine import IST

# 🔹 Rashi map
RASHI_MAP = {
    "aries": 1, "taurus": 2, "gemini": 3, "cancer": 4,
    "leo": 5, "virgo": 6, "libra": 7, "scorpio": 8,
    "sagittarius": 9, "capricorn": 10, "aquarius": 11, "pisces": 12
}


# -------------------------------
# 🔹 House Calculation
# -------------------------------
def calculate_house(lagna, planet_rashi):
    lagna_num = RASHI_MAP.get(str(lagna).strip().lower())
    rashi_num = RASHI_MAP.get(str(planet_rashi).strip().lower())

    if not lagna_num or not rashi_num:
        return None

    return (rashi_num - lagna_num + 12) % 12 + 1


# -------------------------------
# 🔹 Transit Users
# -------------------------------
def get_users_for_transit(event):
    if not event.meta:
        return []

    planet = event.meta.get("planet")
    rashi = event.meta.get("rashi")

    if not planet or not rashi:
        return []

    target_users = []

    users = AppUser.query.filter(AppUser.lagna.isnot(None)).all()

    for user in users:
        if not user.lagna:
            continue

        house = calculate_house(user.lagna, rashi)

        if house in [1, 4, 7, 8, 10, 12]:
            target_users.append({
                "user": user,
                "house": house,
                "planet": planet
            })

    return target_users


# -------------------------------
# 🔹 Dasha (placeholder)
# -------------------------------
def get_users_for_dasha_change():
    today = datetime.now(IST).date()

    start_window = today - timedelta(days=5)
    end_window = today + timedelta(days=5)

    rows = UserDashaTimeline.query.filter(
        UserDashaTimeline.start_date >= start_window,
        UserDashaTimeline.start_date <= end_window
    ).all()

    result = []

    for r in rows:
        if not r.user:
            continue

        result.append({
            "user": r.user,
            "mahadasha": r.mahadasha,
            "antardasha": r.antardasha,
            "type": "start_window"
        })

    return result


def get_current_dasha_users():
    today = datetime.now(IST).date()

    rows = UserDashaTimeline.query.filter(
        UserDashaTimeline.start_date <= today,
        UserDashaTimeline.end_date >= today
    ).all()

    result = []

    for r in rows:
        if not r.user:
            continue

        result.append({
            "user": r.user,
            "mahadasha": r.mahadasha,
            "antardasha": r.antardasha,
            "type": "running"
        })

    return result

