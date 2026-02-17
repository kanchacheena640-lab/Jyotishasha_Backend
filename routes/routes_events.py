from flask import Blueprint, request, jsonify
from datetime import datetime
from services.panchang_engine import calculate_panchang
from services.events_engine import (
    get_ekadashi_details,
    find_next_ekadashi,
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

routes_events = Blueprint("routes_events", __name__)

@routes_events.route("/ekadashi", methods=["POST"])
def api_ekadashi():
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

        today_ekadashi = get_ekadashi_details(panchang)

        next_ekadashi = find_next_ekadashi(current_date, lat, lon, "en")

        return jsonify({
            "today": today_ekadashi,
            "next": next_ekadashi
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

        today_shivratri = get_shivratri_details(panchang, lat, lon)

        next_shivratri = find_next_shivratri(current_date, lat, lon, "en")

        return jsonify({
            "today": today_shivratri,
            "next": next_shivratri
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500