from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from services.panchang_engine import calculate_panchang
from services.adhik_maas_engine import detect_adhik_maas
from services.events_engine import (
    get_pradosh_details,
    find_next_pradosh,
    get_sankashti_details,       
    find_next_sankashti,    
    get_amavasya_details,
    find_next_amavasya,
    get_purnima_details,
    find_next_purnima,
    get_vinayaka_chaturthi_details,
    find_next_vinayaka_chaturthi,
    get_shivratri_details,
    find_next_shivratri,
)
from services.sankranti_engine import (
    get_sankranti_details,
    find_next_sankranti
)

routes_events = Blueprint("routes_events", __name__)


@routes_events.route("/pradosh", methods=["POST"])
def api_pradosh():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        # Today's Panchang
        panchang = calculate_panchang(current_date, lat, lon, "en")

        today_pradosh = get_pradosh_details(panchang)

        next_pradosh = find_next_pradosh(current_date, lat, lon, "en")

        return jsonify({
            "today": today_pradosh,
            "next": next_pradosh
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@routes_events.route("/sankashti", methods=["POST"])
def api_sankashti():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        panchang = calculate_panchang(current_date, lat, lon, "en")

        # ✅ FIX HERE
        today_sankashti = get_sankashti_details(panchang, lat, lon)

        next_sankashti = find_next_sankashti(current_date, lat, lon, "en")

        return jsonify({
            "today": today_sankashti,
            "next": next_sankashti
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@routes_events.route("/amavasya", methods=["POST"])
def api_amavasya():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        panchang = calculate_panchang(current_date, lat, lon, "en")

        today_amavasya = get_amavasya_details(panchang)

        next_amavasya = find_next_amavasya(current_date, lat, lon, "en")

        return jsonify({
            "today": today_amavasya,
            "next": next_amavasya
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@routes_events.route("/purnima", methods=["POST"])
def api_purnima():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        panchang = calculate_panchang(current_date, lat, lon, "en")

        today_purnima = get_purnima_details(panchang)

        next_purnima = find_next_purnima(current_date, lat, lon, "en")

        return jsonify({
            "today": today_purnima,
            "next": next_purnima
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@routes_events.route("/vinayaka", methods=["POST"])
def api_vinayaka_chaturthi():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        panchang = calculate_panchang(current_date, lat, lon, "en")

        today_vinayaka = get_vinayaka_chaturthi_details(panchang)

        next_vinayaka = find_next_vinayaka_chaturthi(
            current_date, lat, lon, "en"
        )

        return jsonify({
            "today": today_vinayaka,
            "next": next_vinayaka
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@routes_events.route("/shivratri", methods=["POST"])
def api_shivratri():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        panchang = calculate_panchang(current_date, lat, lon, "en")

        today_shivratri = get_shivratri_details(panchang, lat, lon, "en")
        next_shivratri = find_next_shivratri(current_date, lat, lon, "en")

        return jsonify({"today": today_shivratri, "next": next_shivratri})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@routes_events.route("/sankranti", methods=["POST"])
def api_sankranti():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        date_str = data.get("date")

        if date_str:
            current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            current_date = datetime.now().date()

        today_sankranti = get_sankranti_details(
            current_date, lat, lon, "en"
        )

        next_sankranti = find_next_sankranti(
            current_date, lat, lon, "en"
        )

        return jsonify({
            "today": today_sankranti,
            "next": next_sankranti
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    
@routes_events.route("/adhik-maas", methods=["POST"])
def api_adhik_maas():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))

        year = data.get("year")
        year = int(year) if year else datetime.now().year

        items = detect_adhik_maas(year, lat, lon)

        if items:
            return jsonify({
                "year": year,
                "has_adhik_maas": True,
                "items": items
            })

        return jsonify({
            "year": year,
            "has_adhik_maas": False,
            "message": f"No Adhik Maas in {year}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EKADASHI_DIR = os.path.join(BASE_DIR, "data", "ekadashi")


def find_next_ekadashi_from_json(today):
    year = today.year

    for y in [year, year + 1]:
        file_path = os.path.join(EKADASHI_DIR, f"ekadashi_{y}.json")

        if not os.path.exists(file_path):
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        ekadashi_list = data.get("ekadashi_list", [])

        future = [
            e for e in ekadashi_list
            if datetime.strptime(e["vrat_date"], "%Y-%m-%d").date() >= today
        ]

        if future:
            future.sort(
                key=lambda x: datetime.strptime(x["vrat_date"], "%Y-%m-%d")
            )

            next_item = future[0]

            return {
                "name": next_item.get("name") or next_item.get("ekadashi_name"),
                "date": next_item["vrat_date"],
                "slug": f"/ekadashi/{next_item['slug']}"
            }

    return None


@routes_events.route("/home-upcoming", methods=["POST"])
def api_home_upcoming():
    try:
        data = request.get_json() or {}

        lat = float(data.get("latitude", 28.61))
        lon = float(data.get("longitude", 77.23))
        today = datetime.now().date()

        events = []

        # 🔹 Helper: normalize engine response safely
        def extract_next(engine_response):
            if not engine_response:
                return None

            next_data = engine_response.get("next")
            if not next_data:
                return None

            name = next_data.get("name_en") or next_data.get("name")
            date_value = next_data.get("date")
            slug_value = next_data.get("slug")

            if not name or not date_value or not slug_value:
                return None

            return {
                "name": name,
                "date": date_value,
                "slug": f"/{slug_value}"
            }

        # 🔹 Engine-based events
        events.append(extract_next(find_next_pradosh(today, lat, lon, "en")))
        events.append(extract_next(find_next_sankashti(today, lat, lon, "en")))
        events.append(extract_next(find_next_amavasya(today, lat, lon, "en")))
        events.append(extract_next(find_next_purnima(today, lat, lon, "en")))
        events.append(extract_next(find_next_shivratri(today, lat, lon, "en")))
        events.append(extract_next(find_next_sankranti(today, lat, lon, "en")))

        # 🔹 Ekadashi (JSON-based)
        ekadashi_event = find_next_ekadashi_from_json(today)
        if ekadashi_event:
            events.append(ekadashi_event)

        # 🔹 Remove invalid
        events = [e for e in events if e and e.get("date")]

        # 🔹 Safe date sorting
        events.sort(
            key=lambda x: datetime.strptime(x["date"], "%Y-%m-%d")
        )

        return jsonify({
            "events": events[:5]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500