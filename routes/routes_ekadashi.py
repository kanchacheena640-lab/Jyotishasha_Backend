import os
import json
from flask import Blueprint, jsonify, request
from datetime import date, datetime

# Blueprint define kiya
ekadashi_bp = Blueprint('ekadashi_new', __name__)

# Base path setup (taaki hum 'data/ekadashi' folder tak pahunch sakein)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "ekadashi")

@ekadashi_bp.route('/api/ekadashi/find-by-slug/<slug>', methods=['GET'])
def get_ekadashi_by_slug(slug):
    """
    Ye route slug ke basis par data fetch karta hai.
    Supports year, exact observance date (YYYY-MM-DD), and optional
    include_occurrences=true. The default response still contains one data object.
    Flexible for slugs like 'amalaki' or 'amalaki-ekadashi'
    """
    
    date_arg = request.args.get("date")
    requested_date = None
    if date_arg is not None:
        try:
            requested_date = date.fromisoformat(date_arg)
            if requested_date.isoformat() != date_arg:
                raise ValueError
        except ValueError:
            return jsonify(status="error", message="date must be YYYY-MM-DD"), 400

    requested_year = request.args.get("year", type=int)
    if requested_date and "year" in request.args and requested_year != requested_date.year:
        return jsonify(status="error", message="year must match date"), 400
    requested_year = requested_year or (
        requested_date.year if requested_date else datetime.now().year
    )

    # 2. File path setup
    file_path = os.path.join(DATA_DIR, f"ekadashi_{requested_year}.json")
    
    # 3. Agar file nahi milti toh error return karein
    if not os.path.exists(file_path):
        return jsonify({
            "status": "error", 
            "message": f"Data file for year {requested_year} not found"
        }), 404

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        search_slug = slug.lower().strip().removesuffix("-ekadashi")
        matches = [
            item for item in data.get("ekadashi_list", [])
            if item["slug"].removesuffix("-ekadashi") == search_slug
        ]
        selected = matches[0] if matches else None
        if requested_date:
            wanted = requested_date.isoformat()
            selected = next((item for item in matches if item["vrat_date"] == wanted), None)
            if selected is None:
                for item in matches:
                    alternate = next(
                        (row for row in item.get("alternate_observances", [])
                         if row["vrat_date"] == wanted),
                        None,
                    )
                    if alternate:
                        selected = {**item, **alternate}
                        break

        if selected:
            response = {"status": "success", "year": requested_year, "data": selected}
            if request.args.get("include_occurrences", "").lower() == "true":
                response["occurrences"] = matches
            return jsonify(response)

        # 5. Agar slug nahi mila
        return jsonify({
            "status": "error", 
            "message": f"Ekadashi '{slug}' not found in {requested_year} list"
        }), 404

    except Exception as e:
        return jsonify({
            "status": "error", 
            "message": f"Internal server error: {str(e)}"
        }), 500
    
@ekadashi_bp.route('/api/ekadashi/all', methods=['GET'])
def get_all_ekadashi():
    """
    Ye naya route saari Ekadashis ki list bhejega.
    Example: /api/ekadashi/all?year=2026
    """
    
    # 1. Year determine karein
    requested_year = request.args.get('year', type=int) or datetime.now().year
    
    # 2. File path setup
    file_path = os.path.join(DATA_DIR, f"ekadashi_{requested_year}.json")
    
    # 3. Check if file exists
    if not os.path.exists(file_path):
        return jsonify({
            "status": "error", 
            "message": f"Data file for year {requested_year} not found"
        }), 404

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Hum 'ekadashi_list' key ke andar ka saara data bhej rahe hain
        ekadashi_data = data.get('ekadashi_list', [])
        
        return jsonify({
            "status": "success", 
            "year": requested_year, 
            "count": len(ekadashi_data),
            "data": ekadashi_data
        })

    except Exception as e:
        return jsonify({
            "status": "error", 
            "message": f"Internal server error: {str(e)}"
        }), 500