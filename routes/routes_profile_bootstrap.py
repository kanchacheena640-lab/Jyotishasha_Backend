"""
routes/routes_profile_bootstrap.py
----------------------------------
Personalized profile bootstrap route for Jyotishasha App.

This route:
1. Receives DOB, TOB, POB from the app
2. Runs calculate_full_kundali() from full_kundali_api.py
3. Extracts Lagna, Moon Sign, Nakshatra
4. Updates the AppUser resolved by modules.user_service.get_or_create_app_user()
5. Returns personalized profile JSON

This route never constructs AppUser() itself -- identity resolution is
owned exclusively by modules/user_service.py (ESR-001A/B), so this
route can never produce a second, disconnected AppUser row for a
person who already has one.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime

from extensions import db
from modules.user_service import get_or_create_app_user

# 🟢 Correct kundali calculator (confirmed by you)
from full_kundali_api import calculate_full_kundali


routes_profile_bootstrap = Blueprint("routes_profile_bootstrap", __name__)


@routes_profile_bootstrap.post("/api/user/bootstrap")
def bootstrap_user_profile():
    try:
        data = request.get_json() or {}

        firebase_uid = data.get("firebase_uid")
        name = data.get("name")
        email = data.get("email")
        dob = data.get("dob")
        tob = data.get("tob")
        pob = data.get("pob")
        lat = data.get("lat")
        lng = data.get("lng")
        lang = data.get("lang", "en")

        if not dob:
            return jsonify({"ok": False, "error": "DOB is required"}), 400

        # ----------------------------------------------------------
        # 1) Calculate Kundali
        # ----------------------------------------------------------
        kundali = calculate_full_kundali(
            name=name,
            dob=dob,
            tob=tob,
            lat=lat,
            lon=lng,
            language=lang,
        )

        lagna = kundali.get("lagna_sign")
        moon_sign = kundali.get("rashi")
        nakshatra = None

        for p in kundali.get("planets", []):
            if p["name"] == "Moon":
                nakshatra = p["nakshatra"]
                break

        # ----------------------------------------------------------
        # 2) Resolve (never create directly) the AppUser via the
        # single identity-resolution service from modules/user_service.py
        # ----------------------------------------------------------
        user = get_or_create_app_user(firebase_uid)

        user.name = name
        user.email = email
        user.dob = dob
        user.tob = tob
        user.pob = pob
        user.lat = lat
        user.lng = lng

        # STORE personalized fields
        # (Your AppUser table MUST add these 3 columns)
        user.lagna = lagna
        user.moon_sign = moon_sign
        user.nakshatra = nakshatra

        db.session.commit()

        # ----------------------------------------------------------
        # 3) Response to App
        # ----------------------------------------------------------
        return jsonify({
            "ok": True,
            "profileId": user.id,
            "name": name,
            "dob": dob,
            "tob": tob,
            "pob": pob,
            "lagna": lagna,
            "moon_sign": moon_sign,
            "nakshatra": nakshatra,
        }), 200

    except Exception as e:
        print("❌ Bootstrap Error:", e)
        return jsonify({"ok": False, "error": "Internal Server Error"}), 500
