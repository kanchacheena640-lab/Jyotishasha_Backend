import json
import os

ZODIAC_FILE = os.path.join("data", "zodiac_traits", "moon_sign_traits.json")

def get_zodiac_traits(sign, lang='en'):
    filename = f"moon_sign_traits_{lang}.json"
    filepath = os.path.join("data", "zodiac_traits", filename)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            traits = json.load(f)
        return traits.get(sign.capitalize())
    except Exception as e:
        print(f"[Zodiac Load Error]: {e}")
        return None