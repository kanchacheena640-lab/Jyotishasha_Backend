"""
routes/routes_profile_bootstrap.py
----------------------------------
Personalized profile bootstrap route for Jyotishasha App.

This route:
1. Receives DOB, TOB, POB from app
2. Runs calculate_full_kundali() from full_kundali_api.py
3. Extracts Lagna, Moon, Nakshatra
4. Saves to UserProfile
5. Returns personalized profile JSON
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
from models import db, UserProfile

# ✅ Correct import (root file)
from full_kundali_api import calculate_full_kundali


routes_profile_bootstrap = Blueprint("routes_profile_bootstrap", __name__)


@routes_profile_bootstrap.post("/api/user/bootstrap")
def bootstrap_user_profile():
    try:
        data = request.get_json() or {}

        uid = data.get("uid")
        name = data.get("name")
        dob = data.get("dob")
        tob = data.get("tob")
        pob = data.get("pob")
        email = data.get("email")
        photo = data.get("photo")
        lang = data.get("lang", "en")

        if not uid or not dob:
            return jsonify({"ok": False, "error": "uid and dob required"}), 400

        # --------------------------------------------------------
        # 1️⃣ Calculate Full Kundali
        # --------------------------------------------------------
        kundali = calculate_full_kundali(
            name=name,
            dob=dob,
            tob=tob,
            lat=data.get("lat"),
            lon=data.get("lng"),
            language=lang,
        )

        lagna = kundali.get("lagna_sign")
        moon_sign = kundali.get("rashi")
        nakshatra = None

        # fetch Moon/Nakshatra from planet list
        for p in kundali.get("planets", []):
            if p["name"] == "Moon":
                nakshatra = p["nakshatra"]
                break

        # --------------------------------------------------------
        # 2️⃣ Save / Update Database
        # --------------------------------------------------------
        profile = UserProfile.query.filter_by(uid=uid).first()

        if not profile:
            profile = UserProfile(uid=uid)

        profile.name = name
        profile.email = email
        profile.photo = photo
        profile.dob = dob
        profile.tob = tob
        profile.pob = pob
        profile.lang = lang
        profile.lagna = lagna
        profile.moon_sign = moon_sign
        profile.nakshatra = nakshatra
        profile.updated_at = datetime.utcnow()

        db.session.add(profile)
        db.session.commit()

        # --------------------------------------------------------
        # 3️⃣ Response to Flutter
        # --------------------------------------------------------
        return jsonify({
            "ok": True,
            "profileId": "default",
            "name": name,
            "dob": dob,
            "tob": tob,
            "pob": pob,
            "lagna": lagna,
            "moon_sign": moon_sign,
            "nakshatra": nakshatra,
            "lang": lang,
        }), 200

    except Exception as e:
        print("❌ Error in bootstrap_user_profile:", e)
        return jsonify({"ok": False, "error": "Internal Server Error"}), 500
