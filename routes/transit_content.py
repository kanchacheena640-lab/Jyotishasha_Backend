# routes/transit_content.py

import os
import json
from flask import Blueprint, request, jsonify

transit_content_bp = Blueprint("transit_content", __name__)

BASE_DIR = os.getcwd()
CONTENT_DIR = os.path.join(BASE_DIR, "content", "transits")


@transit_content_bp.route("/api/transit", methods=["GET"])
def get_transit_content():
    ascendant = request.args.get("ascendant")
    planet = request.args.get("planet")
    house = request.args.get("house")
    lang = request.args.get("lang", "en")

    if not ascendant or not planet or not house:
        return jsonify({"error": "ascendant, planet, house required"}), 400

    try:
        house = int(house)
        if house < 1 or house > 12:
            raise ValueError
    except ValueError:
        return jsonify({"error": "house must be between 1 and 12"}), 400

    ascendant = ascendant.lower()
    planet = planet.lower()
    lang = lang.lower()

    file_path = os.path.join(
        CONTENT_DIR,
        ascendant,
        planet,
        f"house{house}_{lang}.json"
    )

    if not os.path.exists(file_path):
        return jsonify({"error": "Transit content not available"}), 404

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return jsonify(data)
