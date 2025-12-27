# routes/yearly_horoscope.py
from flask import Blueprint, request, jsonify
import os, json

yearly_bp = Blueprint("yearly_horoscope_bp", __name__)

ZODIACS = [
    "aries","taurus","gemini","cancer","leo","virgo",
    "libra","scorpio","sagittarius","capricorn","aquarius","pisces"
]

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "yearly")


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@yearly_bp.route("/api/yearly-horoscope", methods=["GET"])
def yearly_horoscope():
    sign = (request.args.get("sign") or "").lower()
    year = (request.args.get("year") or "").strip()
    lang = (request.args.get("lang") or "en").lower()

    if sign not in ZODIACS:
        return jsonify({"error": "Invalid zodiac sign"}), 400

    if not year.isdigit():
        return jsonify({"error": "Invalid year"}), 400

    year_folder = f"horoscope{year}"
    folder_path = os.path.join(BASE_DIR, year_folder)

    if not os.path.isdir(folder_path):
        return jsonify({"error": f"{year_folder} not available"}), 404

    suffix = "_hi" if lang in ("hi", "hindi") else ""
    file_name = f"{sign}_{year}{suffix}.json"
    file_path = os.path.join(folder_path, file_name)

    # Hindi fallback → English
    if not os.path.exists(file_path) and suffix:
        fallback = os.path.join(folder_path, f"{sign}_{year}.json")
        if os.path.exists(fallback):
            data = read_json(fallback)
            data["_meta"] = {"year": year, "lang": "en", "fallback_from": "hi"}
            return jsonify(data)

    if not os.path.exists(file_path):
        return jsonify({"error": "Horoscope file not found"}), 404

    data = read_json(file_path)
    data["_meta"] = {"year": year, "lang": "hi" if suffix else "en"}
    return jsonify(data)
