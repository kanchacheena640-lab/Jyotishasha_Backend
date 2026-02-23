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
    # Hum check karenge ki kya query mein 'year' bheja gaya hai? 
    # Example: /api/ekadashi/find-by-slug/amalaki?year=2027
    from flask import request
    requested_year = request.args.get('year', type=int) or datetime.now().year
    
    file_path = os.path.join(DATA_DIR, f"ekadashi_{requested_year}.json")
    
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Slug check (flexible matching)
        matched = next((item for item in data.get('ekadashi_list', []) 
                        if item.get('slug') == slug or 
                        item.get('slug') == slug.replace("-ekadashi", "")), None)
        
        if matched:
            return jsonify({"status": "success", "year": requested_year, "data": matched})
            
    return jsonify({"status": "error", "message": f"Data not found for {requested_year}"}), 404