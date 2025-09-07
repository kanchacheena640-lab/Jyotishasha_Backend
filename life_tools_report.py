# life_tools_report.py

from flask import Blueprint, request, jsonify
from full_kundali_api import calculate_full_kundali
from services.career_path import build_career_report
from services.marriage_path import build_marriage_path
from services.foreign_travel import build_foreign_travel 
from services.business_path import build_business_path
from services.government_job import build_government_job
from services.love_life import build_love_life



life_tools_bp = Blueprint("life_tools", __name__)

@life_tools_bp.route("/api/life-tool", methods=["POST"])
def life_tool_report():
    data = request.get_json()
    language = data.get("language", "en")

    kundali = calculate_full_kundali(
        name=data.get("name", "User"),
        dob=data["dob"],
        tob=data["tob"],
        lat=float(data["latitude"]),
        lon=float(data["longitude"]),
        language=language
    )

    results = {
        "career_path": build_career_report(kundali, language),
        "marriage_path": build_marriage_path(kundali, language),
        "foreign_travel": build_foreign_travel(kundali, language),
        "business_path": build_business_path(kundali, language),
        "government_job": build_government_job(kundali, language),
        "love_life": build_love_life(kundali, language)

        # Add more tools here step-by-step
    }

    return jsonify(results)
