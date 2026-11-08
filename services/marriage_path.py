def build_marriage_path(kundali_data: dict, language: str = "en") -> dict:
    """Free Marriage Path snapshot (/api/life-tool -> "marriage_path").

    Rules (unchanged): planets in the 7th house (whole sign), Venus/Jupiter exalted or debilitated, and Rahu in
    the same house as the 7th lord. The "key influence" is the first planet a rule matches, in the chart's planet
    order -- it is not a strength ranking. Every point is returned in the requested language (EN/HI). The response
    keeps every existing field and adds the already-computed 7th-house facts (seventh_sign, seventh_lord,
    seventh_lord_house, seventh_house_planets) so a chart that matches no rule still has something factual to show.
    """
    SIGNS = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]
    SIGN_LORDS = {
        "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
        "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
        "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
    }
    EXALTED = {
        "Sun": "Aries", "Moon": "Taurus", "Mars": "Capricorn", "Mercury": "Virgo",
        "Jupiter": "Cancer", "Venus": "Pisces", "Saturn": "Libra"
    }
    DEBILITATED = {
        "Sun": "Libra", "Moon": "Scorpio", "Mars": "Cancer", "Mercury": "Pisces",
        "Jupiter": "Capricorn", "Venus": "Virgo", "Saturn": "Aries"
    }
    POSITIVE_PLANETS = ["Jupiter", "Moon", "Venus", "Mercury"]
    NEGATIVE_PLANETS = ["Mars", "Saturn", "Rahu", "Ketu", "Sun"]

    hi = language == "hi"

    # Traditional significations, worded as tendencies (no fixed outcomes).
    TRAITS_EN = {
        "Sun": "Traditionally linked with a later marriage and a dignified, self-respecting partner; ego clashes are worth watching.",
        "Moon": "Traditionally linked with strong emotional bonding in marriage; changing moods can affect stability.",
        "Mars": "Traditionally linked with passion and quick decisions in relationships; patience with anger helps.",
        "Mercury": "Traditionally linked with a communicative, witty partner; indecision can be a theme.",
        "Jupiter": "Traditionally linked with wisdom, respect and support in married life.",
        "Venus": "Traditionally linked with romance, charm and harmony in married life.",
        "Saturn": "Traditionally linked with a later or slower-to-settle marriage that tends to strengthen with time.",
        "Rahu": "Traditionally linked with unconventional circumstances or a partner from a different background; clear expectations help.",
        "Ketu": "Traditionally linked with a reserved or spiritual note in marriage and a sense of detachment.",
    }
    TRAITS_HI = {
        "Sun": "परंपरा में इसे देर से विवाह और स्वाभिमानी, गरिमामय जीवनसाथी से जोड़ा जाता है; अहंकार के टकराव पर ध्यान देना उपयोगी है।",
        "Moon": "परंपरा में इसे विवाह में गहरे भावनात्मक जुड़ाव से जोड़ा जाता है; मनोदशा के उतार-चढ़ाव स्थिरता को प्रभावित कर सकते हैं।",
        "Mars": "परंपरा में इसे रिश्तों में जोश और जल्दी निर्णयों से जोड़ा जाता है; गुस्से पर धैर्य रखना सहायक है।",
        "Mercury": "परंपरा में इसे बातचीत में कुशल, हाज़िरजवाब जीवनसाथी से जोड़ा जाता है; अनिर्णय एक विषय हो सकता है।",
        "Jupiter": "परंपरा में इसे वैवाहिक जीवन में समझदारी, सम्मान और सहयोग से जोड़ा जाता है।",
        "Venus": "परंपरा में इसे वैवाहिक जीवन में प्रेम, आकर्षण और तालमेल से जोड़ा जाता है।",
        "Saturn": "परंपरा में इसे देर से या धीरे-धीरे स्थिर होने वाले विवाह से जोड़ा जाता है, जो समय के साथ मजबूत होता है।",
        "Rahu": "परंपरा में इसे असामान्य परिस्थितियों या अलग पृष्ठभूमि वाले जीवनसाथी से जोड़ा जाता है; स्पष्ट अपेक्षाएँ सहायक होती हैं।",
        "Ketu": "परंपरा में इसे विवाह में संयम, आध्यात्मिकता और कुछ विरक्ति के भाव से जोड़ा जाता है।",
    }
    # A debilitated Venus/Jupiter never gets the favourable trait above.
    TRAITS_DEBILITATED_EN = {
        "Venus": "Venus is debilitated here, which is traditionally read as love and attraction needing conscious care in marriage.",
        "Jupiter": "Jupiter is debilitated here, which is traditionally read as respect and trust needing conscious care in marriage.",
    }
    TRAITS_DEBILITATED_HI = {
        "Venus": "यहाँ शुक्र नीच का है, जिसे परंपरा में विवाह में प्रेम और आकर्षण को सजग देखभाल की ज़रूरत के रूप में देखा जाता है।",
        "Jupiter": "यहाँ गुरु नीच का है, जिसे परंपरा में विवाह में सम्मान और भरोसे को सजग देखभाल की ज़रूरत के रूप में देखा जाता है।",
    }

    PLANET_HI = {
        "Sun": "सूर्य", "Moon": "चंद्र", "Mars": "मंगल", "Mercury": "बुध",
        "Jupiter": "गुरु", "Venus": "शुक्र", "Saturn": "शनि", "Rahu": "राहु", "Ketu": "केतु"
    }

    def get_hi(p):
        return PLANET_HI.get(p, p)

    def text(en, hi_text):
        return hi_text if hi else en

    planets = kundali_data.get("planets", [])
    lagna_sign = kundali_data.get("lagna_sign")
    lagna_house = kundali_data.get("lagna_house", 1)

    lagna_index = SIGNS.index(lagna_sign)
    house_7_sign = SIGNS[(lagna_index + 6) % 12]
    house_7_number = ((lagna_house + 6 - 1) % 12) + 1
    house_7_lord = SIGN_LORDS.get(house_7_sign)

    positive_points, negative_points = [], []
    seventh_house_planets = []
    dominant_planet = None

    for p in planets:
        name, house, sign = p["name"], p["house"], p["sign"]

        # Venus/Jupiter dignity
        if name in ["Venus", "Jupiter"]:
            if sign == EXALTED.get(name):
                if name == "Venus":
                    positive_points.append(text("Venus is exalted — traditionally linked with charm and romance in marriage.",
                                                "शुक्र उच्च का है — परंपरा में इसे विवाह में आकर्षण और रोमांस से जोड़ा जाता है।"))
                else:
                    positive_points.append(text("Jupiter is exalted — traditionally linked with mutual respect and admiration in marriage.",
                                                "गुरु उच्च का है — परंपरा में इसे विवाह में परस्पर सम्मान और प्रशंसा से जोड़ा जाता है।"))
                dominant_planet = dominant_planet or name
            elif sign == DEBILITATED.get(name):
                if name == "Venus":
                    negative_points.append(text("Venus is debilitated — traditionally read as love and attraction needing extra care in marriage.",
                                                "शुक्र नीच का है — परंपरा में इसे विवाह में प्रेम और आकर्षण को अधिक देखभाल की ज़रूरत के रूप में देखा जाता है।"))
                else:
                    negative_points.append(text("Jupiter is debilitated — traditionally read as respect and trust needing extra care in marriage.",
                                                "गुरु नीच का है — परंपरा में इसे विवाह में सम्मान और भरोसे को अधिक देखभाल की ज़रूरत के रूप में देखा जाता है।"))
                dominant_planet = dominant_planet or name

        # Planet in 7th house
        if house == house_7_number:
            if name in POSITIVE_PLANETS:
                positive_points.append(text(f"{name} is placed in 7th house.", f"{get_hi(name)} सप्तम भाव में स्थित है।"))
            elif name in NEGATIVE_PLANETS:
                negative_points.append(text(f"{name} is placed in 7th house.", f"{get_hi(name)} सप्तम भाव में स्थित है।"))
            if name != "Ascendant (Lagna)":
                dominant_planet = dominant_planet or name
                seventh_house_planets.append(name)

    # Check conjunction: is Rahu in same house as 7th lord?
    lord_house = next((p["house"] for p in planets if p["name"] == house_7_lord), None)
    for p in planets:
        if p["name"] == "Rahu" and p["house"] == lord_house:
            negative_points.append(text(f"Rahu is conjoined with {house_7_lord} (7th house lord).",
                                        f"राहु सप्तमेश {get_hi(house_7_lord)} के साथ स्थित है।"))
            dominant_planet = dominant_planet or "Rahu"

    # Key influence: the first matched planet (not a strength ranking).
    if dominant_planet:
        dominant_sign = next((p["sign"] for p in planets if p["name"] == dominant_planet), None)
        debilitated = dominant_planet in TRAITS_DEBILITATED_EN and dominant_sign == DEBILITATED.get(dominant_planet)
        if hi:
            trait = TRAITS_DEBILITATED_HI[dominant_planet] if debilitated else TRAITS_HI[dominant_planet]
            dominant_line = f"{get_hi(dominant_planet)} आपके सप्तम भाव पर एक प्रमुख प्रभाव है। {trait}"
        else:
            trait = TRAITS_DEBILITATED_EN[dominant_planet] if debilitated else TRAITS_EN[dominant_planet]
            dominant_line = f"{dominant_planet} is a key influence on your 7th house. {trait}"
    else:
        dominant_line = ""

    return {
        "tool_id": "marriage_path",
        "language": language,
        "heading": "सप्तम भाव (विवाह भाव): यह आपका वैवाहिक विश्लेषण है।" if hi else "7th House (Marriage Bhav): Here's your Marriage Insight.",
        "positive_points": positive_points,
        "negative_points": negative_points,
        "dominant_influence": dominant_line,
        "cta": "➡️ यह एक सामान्य वैवाहिक झलक है। विवाह रिपोर्ट आपके विवाह की संभावनाओं और वर्तमान दशा का अलग, विस्तृत विश्लेषण है।" if hi
        else "➡️ This is a general marriage snapshot. The Marriage Report is a separate, detailed reading of your marriage outlook and current Dasha period.",
        # Additive 7th-house facts (backend values, English names; the frontend localizes them).
        "seventh_sign": house_7_sign,
        "seventh_lord": house_7_lord,
        "seventh_lord_house": lord_house,
        "seventh_house_planets": seventh_house_planets,
    }
