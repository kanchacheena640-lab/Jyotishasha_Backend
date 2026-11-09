def build_love_life(kundali: dict, language: str = "en") -> dict:
    """Free Love Life snapshot (/api/life-tool -> "love_life").

    Rules (unchanged): Venus or Moon in the 5th/7th house is read as supportive; Saturn or Ketu in the 5th/7th and
    Sun or Mars in the 7th are read as points to watch (whole-sign houses from the Lagna). A Venus or Moon that is
    debilitated is not given the supportive reading -- it is listed as needing care instead. When no rule applies the
    lists are empty: nothing is invented. Points stay {"en", "hi"} objects; every existing field is kept, and the
    already-computed 5th/7th-house facts are added (fifth_sign, seventh_sign, fifth_house_planets,
    seventh_house_planets).
    """
    planets = kundali.get("planets", [])
    lagna_sign = kundali.get("lagna_sign", "")

    SIGNS = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]
    PLANET_HI = {
        "Sun": "सूर्य", "Moon": "चंद्र", "Mars": "मंगल", "Mercury": "बुध",
        "Jupiter": "गुरु", "Venus": "शुक्र", "Saturn": "शनि",
        "Rahu": "राहु", "Ketu": "केतु"
    }
    HOUSE_HI = {
        1: "लग्न", 2: "द्वितीय", 3: "तृतीय", 4: "चतुर्थ", 5: "पंचम",
        6: "षष्ठ", 7: "सप्तम", 8: "अष्टम", 9: "नवम", 10: "दशम",
        11: "एकादश", 12: "द्वादश",
    }
    ORDINAL = {5: "5th", 7: "7th"}
    DEBILITATED = {"Venus": "Virgo", "Moon": "Scorpio"}

    POSITIVE = []
    NEGATIVE = []

    # Venus or Moon in 5th or 7th -> supportive, unless debilitated (then a point needing care).
    for p in planets:
        if p["name"] in ["Venus", "Moon"] and p["house"] in [5, 7]:
            name, house = p["name"], p["house"]
            if p.get("sign") == DEBILITATED[name]:
                NEGATIVE.append({
                    "en": f"{name} in the {ORDINAL[house]} house is debilitated, which is traditionally read as love and emotional bonding needing conscious care.",
                    "hi": f"{HOUSE_HI[house]} भाव में {PLANET_HI[name]} नीच का है, जिसे परंपरा में प्रेम और भावनात्मक जुड़ाव को सजग देखभाल की ज़रूरत के रूप में देखा जाता है।"
                })
            else:
                POSITIVE.append({
                    "en": f"{name} in the {ORDINAL[house]} house is traditionally read as supporting love and emotional bonding.",
                    "hi": f"{HOUSE_HI[house]} भाव में {PLANET_HI[name]} को परंपरा में प्रेम और भावनात्मक जुड़ाव के लिए सहायक माना जाता है।"
                })

    # Saturn or Ketu in 5th/7th -> point to watch
    for p in planets:
        if p["name"] in ["Saturn", "Ketu"] and p["house"] in [5, 7]:
            NEGATIVE.append({
                "en": f"{p['name']} in the {ORDINAL[p['house']]} house is traditionally read as reserve or delays in expressing feelings.",
                "hi": f"{HOUSE_HI[p['house']]} भाव में {PLANET_HI[p['name']]} को परंपरा में भावनाएँ व्यक्त करने में संकोच या देरी के रूप में देखा जाता है।"
            })

    # Sun or Mars in 7th -> point to watch
    for p in planets:
        if p["name"] in ["Sun", "Mars"] and p["house"] == 7:
            NEGATIVE.append({
                "en": f"{p['name']} in the 7th house is traditionally read as a tendency towards ego clashes or control in relationships.",
                "hi": f"सप्तम भाव में {PLANET_HI[p['name']]} को परंपरा में रिश्तों में अहंकार या वर्चस्व की प्रवृत्ति के रूप में देखा जाता है।"
            })

    # Already-computed 5th/7th-house facts (whole sign from the Lagna); backend values in English.
    fifth_sign = seventh_sign = None
    if lagna_sign in SIGNS:
        i = SIGNS.index(lagna_sign)
        fifth_sign, seventh_sign = SIGNS[(i + 4) % 12], SIGNS[(i + 6) % 12]
    occupants = lambda h: [p["name"] for p in planets if p.get("house") == h and "Ascendant" not in p.get("name", "")]

    heading = {
        "en": "Your 5th and 7th houses, read for love and relationships.",
        "hi": "प्रेम और रिश्तों के लिए आपके पंचम और सप्तम भाव का विश्लेषण।"
    }
    cta = {
        "en": "Get your detailed Love & Relationship Report based on your birth chart.",
        "hi": "अपनी जन्म कुंडली पर आधारित विस्तृत प्रेम और संबंध रिपोर्ट पाएं।"
    }
    lang = "hi" if language == "hi" else "en"

    return {
        "heading": heading[lang],
        "positive_points": POSITIVE,
        "negative_points": NEGATIVE,
        "cta": cta[lang],
        # Kept for compatibility; no universal verdict is given any more.
        "verdict": "",
        "fifth_sign": fifth_sign,
        "seventh_sign": seventh_sign,
        "fifth_house_planets": occupants(5),
        "seventh_house_planets": occupants(7),
    }
