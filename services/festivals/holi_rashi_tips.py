from datetime import datetime
from services.festivals.holi_engine import detect_holi
import transit_engine

ZODIAC = [
    "Aries","Taurus","Gemini","Cancer",
    "Leo","Virgo","Libra","Scorpio",
    "Sagittarius","Capricorn","Aquarius","Pisces"
]


HOUSE_OFFERINGS = {
    1: ("clarity and self-control", "मन की स्थिरता और संयम", "turmeric (a pinch)", "हल्दी की चुटकी"),
    2: ("wealth stability and family harmony", "धन स्थिरता और पारिवारिक सौहार्द", "jaggery (small piece)", "थोड़ा सा गुड़"),
    3: ("courage and balanced communication", "साहस और संतुलित वाणी", "cloves (2)", "2 लौंग"),
    4: ("peace at home", "घर में शांति", "raw rice (a spoon)", "कच्चे चावल (एक चम्मच)"),
    5: ("joy and positive creativity", "आनंद और सकारात्मक ऊर्जा", "ghee (few drops)", "घी की कुछ बूंदें"),
    6: ("health protection and relief from conflicts", "स्वास्थ्य रक्षा और विवाद शांति", "jaggery + mustard seeds", "गुड़ और सरसों"),
    7: ("relationship harmony", "रिश्तों में सामंजस्य", "mishri (few pieces)", "थोड़ी मिश्री"),
    8: ("protection from sudden negativity", "अचानक नकारात्मकता से रक्षा", "black sesame", "काले तिल"),
    9: ("luck and blessings", "भाग्य और आशीर्वाद", "yellow chana", "पीला चना"),
    10: ("respect and career stability", "सम्मान और कार्य स्थिरता", "wheat grains", "गेहूं के दाने"),
    11: ("gains and social support", "लाभ और मित्र सहयोग", "dry coconut piece", "सूखा नारियल"),
    12: ("mental peace and emotional balance", "मानसिक शांति और भावनात्मक संतुलन", "camphor (small)", "थोड़ा कपूर"),
}


def _calculate_house(janma_sign, moon_sign):
    i = ZODIAC.index(janma_sign)
    j = ZODIAC.index(moon_sign)
    return (j - i) % 12 + 1


def _build_tip(house):
    en_intent, hi_intent, en_offer, hi_offer = HOUSE_OFFERINGS[house]

    return {
        "en": f"For better {en_intent}, offer {en_offer} into the Holi fire and pray sincerely.",
        "hi": f"{hi_intent} के लिए होलिका दहन में {hi_offer} अर्पित करें और सच्चे मन से प्रार्थना करें।"
    }


def generate_holi_rashi_tips(year, lat, lon, language="en"):
    holi_data = detect_holi(year, lat, lon, language)
    if not holi_data:
        return None

    date_str = holi_data["holika_dahan"]["date"]
    sunset_time = holi_data["holika_dahan"]["sunset"]

    holi_dt = datetime.strptime(
        f"{date_str} {sunset_time}",
        "%Y-%m-%d %H:%M"
    )

    # Moon sign from your transit engine
    moon_sign = transit_engine._planet_rashi_on_day("Moon", holi_dt)
    if moon_sign not in ZODIAC:
        return None


    tips = {}

    for sign in ZODIAC:
        house = _calculate_house(sign, moon_sign)
        tips[sign.lower()] = {
            "moon_transit_house": house,
            "tip": _build_tip(house)
        }

    return {
        "year": year,
        "holika_dahan_date": date_str,
        "moon_sign_on_holi": moon_sign,
        "tips": tips
    }
