import os
import sys
import json
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from services.ekadashi_engine import generate_year

# Path ko clean rakhte hain: data/ekadashi/ folder mein save hoga
DATA_DIR = os.path.join(BASE_DIR, "data", "ekadashi")

def generate_and_save(year: int, lat: float, lon: float, language: str = "en"):
    data = generate_year(year, lat, lon, language)

    if not data or not data.get("ekadashi_list"):
        print(f"Skipping {year}: No data generated.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    # File name ko simple rakhte hain taaki API se fetch karna aasaan ho
    file_path = os.path.join(DATA_DIR, f"ekadashi_{year}.json")

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Successfully Generated: {file_path}")


if __name__ == "__main__":
    # Default Coordinates (Lucknow) agar koi input na ho
    DEFAULT_LAT = 26.8467
    DEFAULT_LON = 80.9462
    DEFAULT_LANG = "en"

    # LOGIC: Agar command line args hain (Manual run)
    if len(sys.argv) >= 4:
        year = int(sys.argv[1])
        lat = float(sys.argv[2])
        lon = float(sys.argv[3])
        language = sys.argv[4] if len(sys.argv) >= 5 else DEFAULT_LANG
        generate_and_save(year, lat, lon, language)
    
    # LOGIC: Agar koi arg nahi hai (GitHub Action / Auto Run)
    else:
        print("No arguments provided. Running Auto-Year Generation...")
        current_year = datetime.datetime.now().year
        # Agle 2 saal ka data hamesha ready rakhenge
        for y in [current_year, current_year + 1]:
            generate_and_save(y, DEFAULT_LAT, DEFAULT_LON, DEFAULT_LANG)