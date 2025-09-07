from typing import Dict, List

def build_foreign_travel(kundali_data: Dict, lang: str = "en") -> Dict:
    SIGNS = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]
    SIGNS_HI = {
        "Aries": "मेष", "Taurus": "वृषभ", "Gemini": "मिथुन", "Cancer": "कर्क", "Leo": "सिंह", "Virgo": "कन्या",
        "Libra": "तुला", "Scorpio": "वृश्चिक", "Sagittarius": "धनु", "Capricorn": "मकर", "Aquarius": "कुंभ", "Pisces": "मीन"
    }
    PLANET_HI = {
        "Sun": "सूर्य", "Moon": "चंद्र", "Mars": "मंगल", "Mercury": "बुध",
        "Jupiter": "गुरु", "Venus": "शुक्र", "Saturn": "शनि", "Rahu": "राहु", "Ketu": "केतु"
    }
    SIGN_LORDS = {
        "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon", "Leo": "Sun",
        "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars", "Sagittarius": "Jupiter",
        "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
    }
    POSITIVE_PLANETS = ["Jupiter", "Moon", "Venus", "Mercury"]
    NEGATIVE_PLANETS = ["Mars", "Saturn", "Rahu", "Ketu", "Sun"]

    def get_hi(val): return PLANET_HI.get(val, val)
    def get_sign_hi(val): return SIGNS_HI.get(val, val)
    def wrap_point(en, hi): return {"en": en, "hi": hi}

    positive_points = []
    negative_points = []
    seen = set()

    planets = kundali_data.get("planets", [])
    house_map = {p["name"]: p["house"] for p in planets}

    # --------- STEP 1: House Lords from Lagna ----------
    lagna_sign = kundali_data.get("lagna_sign")
    if lagna_sign not in SIGNS:
        lagna_index = 0
    else:
        lagna_index = SIGNS.index(lagna_sign)

    for house_num in [9, 12]:
        rashi_index = (lagna_index + house_num - 1) % 12
        house_sign = SIGNS[rashi_index]
        house_sign_hi = get_sign_hi(house_sign)
        lord = SIGN_LORDS.get(house_sign)
        lord_house = house_map.get(lord)

        if not lord or not lord_house:
            continue

        if house_num == 12 and lord_house == 12:
            en = f"12th house lord {lord} is in its own house — supports foreign travel."
            hi = f"द्वादश भाव के स्वामी {get_hi(lord)} स्वयं के भाव ({get_sign_hi(house_sign)}) में स्थित हैं — विदेश यात्रा को समर्थन।"
            positive_points.append(wrap_point(en, hi))
        elif lord_house in [6, 8, 12]:
            en = f"{house_num}th house lord {lord} is in {lord_house}th house — may bring obstacles."
            hi = f"{house_num}वें भाव के स्वामी {get_hi(lord)} {lord_house}वें भाव में हैं — बाधाओं का संकेत।"
            negative_points.append(wrap_point(en, hi))
        else:
            en = f"{house_num}th house lord {lord} is placed in {lord_house}th house."
            hi = f"{house_num}वें भाव के स्वामी {get_hi(lord)} {lord_house}वें भाव में स्थित हैं।"
            positive_points.append(wrap_point(en, hi))

    # --------- STEP 2: Planets in 9th or 12th ----------
    for p in planets:
        name, house = p["name"], p["house"]
        if house in [9, 12] and name not in seen:
            seen.add(name)
            if name in POSITIVE_PLANETS:
                en = f"{name} is placed in {house}th house — favorable for foreign travel."
                hi = f"{get_hi(name)} {house}वें भाव में स्थित है — विदेश यात्रा के लिए अनुकूल।"
                positive_points.append(wrap_point(en, hi))
            elif name in NEGATIVE_PLANETS:
                en = f"{name} is placed in {house}th house — may cause delays or restrictions."
                hi = f"{get_hi(name)} {house}वें भाव में स्थित है — यात्रा में बाधा डाल सकता है।"
                negative_points.append(wrap_point(en, hi))

    # --------- STEP 3: Aspects (Traditional Drishti) ----------
    for p in planets:
        name, house = p["name"], p["house"]
        if name in seen:
            continue

        aspects = []
        if name == "Mars":
            aspects = [(house+4-1)%12, (house+7-1)%12, (house+8-1)%12]
        elif name == "Saturn":
            aspects = [(house+3-1)%12, (house+7-1)%12, (house+10-1)%12]
        elif name == "Jupiter":
            aspects = [(house+5-1)%12, (house+7-1)%12, (house+9-1)%12]
        else:
            aspects = [(house+7-1)%12]

        for asp in aspects:
            if asp in [9, 12]:
                seen.add(name)
                if name in POSITIVE_PLANETS:
                    en = f"{name} aspects {asp}th house — supportive influence."
                    hi = f"{get_hi(name)} की दृष्टि {asp}वें भाव पर है — सहयोगी प्रभाव।"
                    positive_points.append(wrap_point(en, hi))
                elif name in NEGATIVE_PLANETS:
                    en = f"{name} aspects {asp}th house — may obstruct foreign travel."
                    hi = f"{get_hi(name)} की दृष्टि {asp}वें भाव पर है — यात्रा में बाधा संभव।"
                    negative_points.append(wrap_point(en, hi))

    # --------- Fallback if all blank ----------
    if not positive_points:
        en = "Some yogas related to foreign travel are definitely visible in your chart. However, how strong these possibilities are depends on current Dasha and planetary transit."
        hi = "आपकी कुंडली में विदेश यात्रा से जुड़े कुछ योग अवश्य दिखाई दे रहे हैं, लेकिन ये संभावनाएं कितनी प्रबल हैं, यह वर्तमान ग्रह दशा और गोचर पर निर्भर करता है।"
        positive_points.append(wrap_point(en, hi))


    heading = "Foreign Travel Insight" if lang == "en" else "विदेश यात्रा दृष्टिकोण"
    cta = "🌍 Combinations are forming. Final result depends on Dasha & Transit." if lang == "en" else "🌍 कुछ योग बन रहे हैं। अंतिम परिणाम दशा और गोचर पर निर्भर करता है।"
    dominant = "Jupiter, Rahu, 9th & 12th Houses" if lang == "en" else "गुरु, राहु, नवम और द्वादश भाव"

    return {
        "tool_id": "foreign-travel",
        "language": lang,
        "heading": heading,
        "cta": cta,
        "dominant_influence": dominant,
        "positive_points": positive_points[:4],
        "negative_points": negative_points[:4]
    }
