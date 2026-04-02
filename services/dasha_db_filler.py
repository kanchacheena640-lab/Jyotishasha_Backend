from modules.models_user import AppUser, UserDashaTimeline
from full_kundali_api import calculate_vimshottari_dasha, get_moon_longitude_lahiri
from datetime import datetime
from extensions import db


def fill_dasha_for_all_users():
    users = AppUser.query.all()

    for user in users:
        if not user.dob or not user.tob or not user.lat or not user.lng:
            continue

        # skip if already exists
        exists = UserDashaTimeline.query.filter_by(user_id=user.id).first()
        if exists:
            continue

        try:
            moon_deg = get_moon_longitude_lahiri(
                user.dob, user.tob, user.lat, user.lng
            )

            birth_date = datetime.strptime(
                f"{user.dob} {user.tob}", "%Y-%m-%d %H:%M"
            )

            mahadashas = calculate_vimshottari_dasha(moon_deg, birth_date)

            # 🔥 store ALL mahadasha + antardasha
            for md in mahadashas:
                for ad in md["antardashas"]:
                    row = UserDashaTimeline(
                        user_id=user.id,
                        mahadasha=md["mahadasha"],
                        antardasha=ad["planet"],
                        start_date=datetime.strptime(ad["start"], "%Y-%m-%d").date(),
                        end_date=datetime.strptime(ad["end"], "%Y-%m-%d").date(),
                    )
                    db.session.add(row)

        except Exception as e:
            print(f"❌ Error for user {user.id}: {e}")

    db.session.commit()
    print("✅ All users dasha stored")