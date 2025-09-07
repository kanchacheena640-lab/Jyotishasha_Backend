from flask import Flask, request, jsonify
import swisseph as swe
from datetime import datetime, timedelta
from services.zodiac_service import get_zodiac_traits  # already imported
from services.grah_dasha_finder import get_grah_dasha_block
from services.planet_overview_logic import get_planet_overview
from services.mangalik_dosh_logic import build_manglik_dosh
from services.kaalsarp_dosh_logic import generate_kaalsarp_dosh_report
from services.sadhesati_report_generator import generate_sadhesati_report
from services.budh_aditya import evaluate_budh_aditya_from_planets
from services.chandra_mangal import evaluate_chandra_mangal_from_planets
from services.adhi_rajyog import evaluate_adhi_rajyog_from_planets
from services.dhan_yog import evaluate_dhan_yog_from_planets
from services.dharma_karmadhipati import evaluate_dharma_karmadhipati
from services.gajakesari import evaluate_gajakesari
from services.kuber_rajyog import evaluate_kuber_rajyog_from_planets
from services.lakshmi_yog import evaluate_lakshmi_yog
from services.neechbhang_rajyog import evaluate_neechbhang
from services.panch_mahapurush import evaluate_panch_mahapurush_yog
from services.parashari_rajyog import evaluate_parashari_rajyog
from services.rajya_sambandh_rajyog import evaluate_rajya_sambandh_rajyog
from services.shubh_kartari_yog import evaluate_shubh_kartari_yog
from services.vipreet_rajyog import evaluate_vipreet_rajyog
from services.gemstone_recommender import recommend_gemstone_from_lagna_9th




import json
import os

app = Flask(__name__)

# ----------------- CONSTANTS -----------------
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"
]

DASHA_SEQUENCE = ['Ketu', 'Venus', 'Sun', 'Moon', 'Mars', 'Rahu', 'Jupiter', 'Saturn', 'Mercury']
DASHA_YEARS = {
    'Ketu': 7, 'Venus': 20, 'Sun': 6, 'Moon': 10,
    'Mars': 7, 'Rahu': 18, 'Jupiter': 16, 'Saturn': 19, 'Mercury': 17
}

# ----------------- HELPER FUNCTIONS -----------------
def get_nakshatra_pada(degree):
    nak_size = 13 + 1/3  # 13°20' = 13.3333 degrees
    total = degree % 360
    nak_index = int(total // nak_size)
    pada = int(((total % nak_size) / (nak_size / 4)) + 1)
    return NAKSHATRAS[nak_index], pada

def calculate_planet_positions(dob, tob, lat, lon):
    year, month, day = map(int, dob.split('-'))
    hour, minute = map(int, tob.split(':'))
    local_time = datetime(year, month, day, hour, minute)
    utc_time = local_time - timedelta(hours=5, minutes=30)

    jd_ut = swe.julday(utc_time.year, utc_time.month, utc_time.day,
                       utc_time.hour + utc_time.minute / 60.0)

    swe.set_sid_mode(swe.SIDM_LAHIRI)
    FLAGS = swe.FLG_SIDEREAL | swe.FLG_SWIEPH

    cusps, ascmc = swe.houses(jd_ut, float(lat), float(lon), b'P')
    tropical_lagna = ascmc[0]
    ayanamsa = swe.get_ayanamsa(jd_ut)
    asc_deg = (tropical_lagna - ayanamsa) % 360
    asc_sign_index = int(asc_deg // 30)
    asc_sign = SIGNS[asc_sign_index]
    asc_nak, asc_pada = get_nakshatra_pada(asc_deg)

    house_map = {(asc_sign_index + i) % 12: i + 1 for i in range(12)}

    planets = {
        'Sun': swe.SUN,
        'Moon': swe.MOON,
        'Mercury': swe.MERCURY,
        'Venus': swe.VENUS,
        'Mars': swe.MARS,
        'Jupiter': swe.JUPITER,
        'Saturn': swe.SATURN,
        'Rahu': swe.MEAN_NODE,
        'Ketu': 'South_Node'
    }

    planet_data = []
    for name, planet in planets.items():
        if planet == 'South_Node':
            rahu = swe.calc(jd_ut, swe.MEAN_NODE, FLAGS)[0][0]
            degree = (rahu + 180) % 360
        else:
            degree = swe.calc(jd_ut, planet, FLAGS)[0][0]
        sign_index = int(degree // 30)
        nakshatra, pada = get_nakshatra_pada(degree)

        planet_data.append({
            'name': name,
            'degree': round(degree % 30, 2),
            'sign': SIGNS[sign_index],
            'house': house_map[sign_index],
            'nakshatra': nakshatra,
            'pada': pada
        })

    planet_data.append({
        'name': 'Ascendant (Lagna)',
        'degree': round(asc_deg % 30, 2),
        'sign': asc_sign,
        'house': 1,
        'nakshatra': asc_nak,
        'pada': asc_pada
    })

    return sorted(planet_data, key=lambda x: (x['house'], x['name']))

def calculate_drishti_for_planets(planets):
    drishti_rules = {
        "Saturn": [3, 7, 10],
        "Mars": [4, 7, 8],
        "Jupiter": [5, 7, 9],
        "Rahu": [5, 7, 9],
        "Ketu": [5, 7, 9]
    }

    house_planet_map = {i: [] for i in range(1, 13)}
    for p in planets:
        house_planet_map[p['house']].append(p['name'])

    aspect_data = {p['name']: {"aspecting": [], "aspected_by": []} for p in planets}

    for p in planets:
        rules = drishti_rules.get(p['name'], [7])
        for drishti_count in rules:
            target_house = (p['house'] + drishti_count - 1) % 12 or 12
            if house_planet_map.get(target_house):
                aspect_data[p['name']]["aspecting"].append(
                    f"{', '.join(house_planet_map[target_house])} ({drishti_count}th drishti)"
            )

    for p in planets:
        for other in planets:
            if other['name'] == p['name']:
                continue
            rules = drishti_rules.get(other['name'], [7])
            for drishti_count in rules:
                target_house = (other['house'] + drishti_count - 1) % 12 or 12
                if target_house == p['house']:
                    aspect_data[p['name']]["aspected_by"].append(
                        f"{other['name']} ({drishti_count}th drishti)"
                    )

    return aspect_data

def calculate_shadbala_for_planets(planets):
    shadbala_data = {}
    for p in planets:
        base = p['house'] * 10
        bonus = (SIGNS.index(p['sign']) % 6) * 5
        shadbala_data[p['name']] = base + bonus
    return shadbala_data

def get_moon_longitude_lahiri(dob, tob, lat, lon):
    year, month, day = map(int, dob.split('-'))
    hour, minute = map(int, tob.split(':'))
    local_dt = datetime(year, month, day, hour, minute)
    utc_dt = local_dt - timedelta(hours=5, minutes=30)
    jd_ut = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day,
                       utc_dt.hour + utc_dt.minute / 60.0)
    moon_long = swe.calc_ut(jd_ut, swe.MOON)[0][0]
    ayanamsa = swe.get_ayanamsa_ut(jd_ut)
    return (moon_long - ayanamsa) % 360

def calculate_antardashas(maha_lord, maha_start, maha_years):
    antardashas = []
    maha_index = DASHA_SEQUENCE.index(maha_lord)
    ant_start = maha_start
    for i in range(9):
        antar_lord = DASHA_SEQUENCE[(maha_index + i) % 9]
        antar_days = (maha_years * DASHA_YEARS[antar_lord] * 365.25) / 120
        antar_end = ant_start + timedelta(days=antar_days)
        antardashas.append({
            'planet': antar_lord,
            'start': ant_start.strftime('%Y-%m-%d'),
            'end': antar_end.strftime('%Y-%m-%d')
        })
        ant_start = antar_end
    return antardashas

def calculate_vimshottari_dasha(moon_deg, birth_date):
    nakshatra_size = 13 + 1/3
    nakshatra_index = int(moon_deg // nakshatra_size)
    dasha_lord = DASHA_SEQUENCE[nakshatra_index % 9]
    fraction_passed = (moon_deg % nakshatra_size) / nakshatra_size
    total_years = DASHA_YEARS[dasha_lord]
    elapsed_days = fraction_passed * total_years * 365.25
    start_date = birth_date - timedelta(days=elapsed_days)

    mahadashas = []
    current_index = DASHA_SEQUENCE.index(dasha_lord)
    md_start = start_date
    for i in range(9):
        lord = DASHA_SEQUENCE[(current_index + i) % 9]
        years = DASHA_YEARS[lord]
        md_end = md_start + timedelta(days=years * 365.25)
        antardashas = calculate_antardashas(lord, md_start, DASHA_YEARS[lord])
        mahadashas.append({
            'mahadasha': lord,
            'start': md_start.strftime('%Y-%m-%d'),
            'end': md_end.strftime('%Y-%m-%d'),
            'antardashas': antardashas
        })
        md_start = md_end
    return mahadashas

def get_current_dasha(mahadashas):
    today = datetime.now().date()
    current_maha = None
    for md in mahadashas:
        start = datetime.strptime(md["start"], "%Y-%m-%d").date()
        end = datetime.strptime(md["end"], "%Y-%m-%d").date()
        if start <= today <= end:
            current_maha = md
            break
    if not current_maha:
        current_maha = mahadashas[0]

    current_antar = None
    for ad in current_maha["antardashas"]:
        start = datetime.strptime(ad["start"], "%Y-%m-%d").date()
        end = datetime.strptime(ad["end"], "%Y-%m-%d").date()
        if start <= today <= end:
            current_antar = ad
            break
    if not current_antar:
        current_antar = current_maha["antardashas"][0]

    return current_maha, current_antar

# ----------------- MAIN KUNDALI FUNCTION -----------------
def calculate_full_kundali(name, dob, tob, lat, lon, language='en'):
    planets = calculate_planet_positions(dob, tob, lat, lon)

    drishti_info = calculate_drishti_for_planets(planets)
    shadbala_info = calculate_shadbala_for_planets(planets)

    for p in planets:
        p['aspecting'] = drishti_info[p['name']]['aspecting']
        p['aspected_by'] = drishti_info[p['name']]['aspected_by']
        p['shadbala'] = shadbala_info[p['name']]

    moon_deg = get_moon_longitude_lahiri(dob, tob, lat, lon)
    birth_date = datetime.strptime(f"{dob} {tob}", "%Y-%m-%d %H:%M")
    mahadashas = calculate_vimshottari_dasha(moon_deg, birth_date)
    current_maha, current_antar = get_current_dasha(mahadashas)

    moon_sign = next((p['sign'] for p in planets if p["name"] == "Moon"), None)
    lagna_sign = next((p['sign'] for p in planets if "Ascendant" in p["name"]), None)
    moon_traits = get_zodiac_traits(moon_sign, language)

    grah_dasha = get_grah_dasha_block(
        lagna_sign, current_maha, current_antar, planets, language
    )

    planet_overview = get_planet_overview(planets, language)


    # ✅ Load Lagna Trait from JSON
    try:
        with open("data/lagna_traits.json", encoding="utf-8") as f:
            lagna_traits_data = json.load(f)
            lagna_trait_text = lagna_traits_data.get(lagna_sign, {}).get(language, "Trait not found")
    except Exception as e:
        lagna_trait_text = "Error loading lagna traits"

      # ✅ Inject Manglik Dosh Analysis
    manglik_result = build_manglik_dosh({
        "planets": planets,
        "lagna_sign": lagna_sign,
        "language": language
    })

    kaalsarp_result = generate_kaalsarp_dosh_report(planets, language)

    # ✅ Inject Sadhesati Report
    sadhesati_result = generate_sadhesati_report({
        "planets": planets,
        "moon_sign": moon_sign,
        "language": language
    })
    # ✅ Inject Rajyoga
    budh_aditya_result = evaluate_budh_aditya_from_planets(planets, language)
    chandra_mangal_result = evaluate_chandra_mangal_from_planets(planets, language)
    adhi_rajyog_result = evaluate_adhi_rajyog_from_planets(planets, language)
    lagna_house = 1  # Ascendant is always treated as 1st house
    dhan_yog_result = evaluate_dhan_yog_from_planets(planets, language, lagna_sign)
    dharma_karmadhipati_result = evaluate_dharma_karmadhipati(planets, language, lagna_sign)
    gajakesari_result = evaluate_gajakesari(planets, language)
    kuber_rajyog_result = evaluate_kuber_rajyog_from_planets(planets, language)
    lakshmi_yog_result = evaluate_lakshmi_yog(planets, language, lagna_sign)
    neechbhang_rajyog_result = evaluate_neechbhang(planets, language)
    panch_mahapurush_result = evaluate_panch_mahapurush_yog(planets, language)
    parashari_rajyog_result = evaluate_parashari_rajyog(planets, language, lagna_sign)
    rajya_sambandh_result = evaluate_rajya_sambandh_rajyog(planets, language, lagna_sign)
    shubh_kartari_result = evaluate_shubh_kartari_yog(planets, language)
    vipreet_rajyog_result = evaluate_vipreet_rajyog(planets, lagna_sign, language)
    gemstone_suggestion = recommend_gemstone_from_lagna_9th(lagna_sign, planets,language)
    moon_sign = next((p['sign'] for p in planets if p["name"] == "Moon"), None)
    lagna_sign = next((p['sign'] for p in planets if "Ascendant" in p["name"]), None)



 

    return {
        "name": name,
        "dob": dob,
        "tob": tob,
        "latitude": lat,
        "longitude": lon,
        "lagna_sign": lagna_sign,
        "rashi": moon_sign,
        "Planets": planets,
        "planets": planets,
        "Mahadasha": mahadashas,
        "current_mahadasha": current_maha,
        "current_antardasha": current_antar,
        "moon_traits": moon_traits,
        "lagna_trait": lagna_trait_text,  
        "grah_dasha_block": grah_dasha,
        "planet_overview" : planet_overview,
        "manglik_dosh": manglik_result,
        "kaalsarp_dosh": kaalsarp_result,
        "sadhesati": sadhesati_result,
        "budh_aditya_yog": budh_aditya_result,
        "chandra_mangal_yog": chandra_mangal_result,
        "adhi_rajyog": adhi_rajyog_result,
        "dhan_yog": dhan_yog_result,
        "dharma_karmadhipati_rajyog": dharma_karmadhipati_result,
        "gajakesari_yog": gajakesari_result,
        "kuber_rajyog": kuber_rajyog_result,
        "lakshmi_yog": lakshmi_yog_result,
        "neechbhang_rajyog": neechbhang_rajyog_result,  
        "panch_mahapurush_yog": panch_mahapurush_result,
        "parashari_rajyog": parashari_rajyog_result,
        "rajya_sambandh_rajyog": rajya_sambandh_result,
        "shubh_kartari_yog": shubh_kartari_result,
        "vipreet_rajyog": vipreet_rajyog_result,
        "gemstone_suggestion": gemstone_suggestion,
    }


