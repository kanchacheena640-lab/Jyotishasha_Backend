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
    Ye route slug ke basis par JSON files scan karta hai aur accurate data deta hai.
    """
    current_year = datetime.now().year
    
    # Hum 2026 aur 2027 dono years ki files check karenge
    for year in [current_year, current_year + 1]:
        file_path = os.path.join(DATA_DIR, f"ekadashi_{year}.json")
        
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 'ekadashi_list' mein se wo item dhundo jiska slug match kare
                matched_event = next(
                    (item for item in data.get('ekadashi_list', []) 
                     if item.get('slug') == slug), 
                    None
                )
                
                if matched_event:
                    # Success: Data mil gaya!
                    return jsonify({
                        "status": "success",
                        "year": year,
                        "data": matched_event
                    })
            except Exception as e:
                # Agar kisi file mein error ho, toh use skip karke agli check karo
                continue 

    # Agar poori files scan karne ke baad bhi slug nahi mila
    return jsonify({
        "status": "error", 
        "message": f"Ekadashi with slug '{slug}' not found in {current_year} or {current_year+1}"
    }), 404