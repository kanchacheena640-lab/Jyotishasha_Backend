import os
import json
from flask import Blueprint, jsonify
from datetime import datetime

# Blueprint define kiya
ekadashi_bp = Blueprint('ekadashi_new', __name__)

# Base path setup (taaki hum 'data/ekadashi' folder tak pahunch sakein)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "ekadashi")

@ekadashi_bp.route('/api/ekadashi/find-by-slug/<slug>', methods=['GET'])
def get_ekadashi_by_slug(slug):
    """
    Ye route slug ke basis par data fetch karta hai.
    Supports: ?year=2026 or ?year=2027 (Default: Current Year)
    Flexible for slugs like 'amalaki' or 'amalaki-ekadashi'
    """
    from flask import request
    
    # 1. Year determine karein (URL parameter se ya current system year)
    requested_year = request.args.get('year', type=int) or datetime.now().year
    
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
            
        # 4. SMART SLUG MATCHING
        # Frontend se kuch bhi aaye (amalaki ya amalaki-ekadashi), hum dono check karenge
        search_slug = slug.lower().strip()
        base_slug = search_slug.replace("-ekadashi", "") # e.g. 'amalaki'
        
        matched = next((
            item for item in data.get('ekadashi_list', []) 
            if item.get('slug') == search_slug or 
               item.get('slug') == base_slug or
               item.get('slug').replace("-ekadashi", "") == base_slug
        ), None)
        
        if matched:
            return jsonify({
                "status": "success", 
                "year": requested_year, 
                "data": matched
            })
        
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