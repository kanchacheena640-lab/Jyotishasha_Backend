def build_marriage_path(kundali_data: dict, language: str = "en") -> dict:
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

    TRAITS_EN = {
        "Sun": "May cause delay in marriage; partner comes after maturity. Brings ego issues, but spouse is dignified and authoritative.",
        "Moon": "Can bring early marriage if emotions dominate decisions. Creates emotional bonding, but mood swings affect stability.",
        "Mars": "Can lead to early marriage due to impulsive decisions. Passionate bond, but anger and aggression must be controlled.",
        "Mercury": "Marriage timing may fluctuate, sometimes early due to quick choices. Brings a witty, communicative spouse, but indecision can cause issues.",
        "Jupiter": "Favors timely or early marriage with divine grace. Gives a wise, supportive spouse and stable, prosperous married life.",
        "Venus": "Often leads to early or love marriage. Brings charm, romance, and harmony in married life.",
        "Saturn": "Causes delay in marriage, often after struggles. Relationship grows stronger with time, but feels heavy in the beginning.",
        "Rahu": "Marriage may happen suddenly or in unusual circumstances. Gives unconventional, modern, or foreign spouse; may bring illusions too.",
        "Ketu": "Creates delay or detachment in marriage matters. Spouse may be spiritual or reserved; bond feels karmic, not material."
    }

    TRAITS_HI = {
        "Sun": "विवाह में विलंब संभव है, पर जीवनसाथी गरिमामय होता है। अहंकार के टकराव संभव हैं।",
        "Moon": "भावनात्मक जुड़ाव से शीघ्र विवाह संभव है, लेकिन मनोदशा में उतार-चढ़ाव से अस्थिरता आ सकती है।",
        "Mars": "उत्साही निर्णयों से शीघ्र विवाह संभव है, लेकिन गुस्सा और अधिकार नियंत्रित करना ज़रूरी है।",
        "Mercury": "तेज़ फैसलों से विवाह में उतार-चढ़ाव हो सकता है। जीवनसाथी बुद्धिमान और हास्यप्रिय होता है।",
        "Jupiter": "समय पर विवाह और स्थायित्व प्रदान करता है। जीवनसाथी ज्ञानी और सहायक होता है।",
        "Venus": "प्रेम विवाह या आकर्षणयुक्त रिश्ता बनता है। जीवन में रोमांस और तालमेल लाता है।",
        "Saturn": "संघर्षों के बाद विलंब से विवाह होता है, लेकिन समय के साथ रिश्ता मजबूत होता है।",
        "Rahu": "अचानक या असामान्य परिस्थितियों में विवाह संभव। भ्रम या विदेशी जीवनसाथी का संकेत।",
        "Ketu": "विवाह में विलंब या दूरी की भावना। जीवनसाथी आध्यात्मिक या गूढ़ स्वभाव का हो सकता है।"
    }

    def get_trait(p): return TRAITS_HI[p] if language == "hi" else TRAITS_EN[p]
    def get_hi(p): return {
        "Sun": "सूर्य", "Moon": "चंद्र", "Mars": "मंगल", "Mercury": "बुध",
        "Jupiter": "गुरु", "Venus": "शुक्र", "Saturn": "शनि", "Rahu": "राहु", "Ketu": "केतु"
    }.get(p, p)

    planets = kundali_data.get("planets", [])
    lagna_sign = kundali_data.get("lagna_sign")
    lagna_house = kundali_data.get("lagna_house", 1)

    lagna_index = SIGNS.index(lagna_sign)
    house_7_sign = SIGNS[(lagna_index + 6) % 12]
    house_7_number = ((lagna_house + 6 - 1) % 12) + 1
    house_7_lord = SIGN_LORDS.get(house_7_sign)

    positive_points, negative_points = [], []
    dominant_planet = None

    for p in planets:
        name, house, sign = p["name"], p["house"], p["sign"]

        # Venus/Jupiter dignity
        if name in ["Venus", "Jupiter"]:
            if sign == EXALTED.get(name):
                if name == "Venus":
                    positive_points.append("Venus is well placed — brings charm and high-class romance in marriage.")
                else:
                    positive_points.append("Jupiter is well placed — gives mutual respect and admiration in marriage.")
                dominant_planet = dominant_planet or name
            elif sign == DEBILITATED.get(name):
                if name == "Venus":
                    negative_points.append("Venus is debilitated — causes lack of love or attraction in marriage.")
                else:
                    negative_points.append("Jupiter is debilitated — respect and trust may be missing in marriage.")
                dominant_planet = dominant_planet or name

        # Planet in 7th house
        if house == house_7_number:
            if name in POSITIVE_PLANETS:
                positive_points.append(f"{name} is placed in 7th house.")
            elif name in NEGATIVE_PLANETS:
                negative_points.append(f"{name} is placed in 7th house.")
            if name != "Ascendant (Lagna)":
                dominant_planet = dominant_planet or name

    # Check conjunction: is Rahu in same house as 7th lord?
    lord_house = next((p["house"] for p in planets if p["name"] == house_7_lord), None)
    for p in planets:
        if p["name"] == "Rahu" and p["house"] == lord_house:
            negative_points.append("Rahu is conjoined with Mars (7th house lord).")
            dominant_planet = dominant_planet or "Rahu"

    # Dominant trait
    if dominant_planet:
        trait = get_trait(dominant_planet)
        if language == "hi":
            dominant_line = f"{get_hi(dominant_planet)} का विवाह पर प्रमुख प्रभाव है। {trait}"
        else:
            dominant_line = f"{dominant_planet} has a dominant influence on your marriage. {trait}"
    else:
        dominant_line = ""

    return {
        "tool_id": "marriage_path",
        "language": language,
        "heading": "सप्तम भाव (विवाह भाव): यह आपका वैवाहिक विश्लेषण है।" if language == "hi" else "7th House (Marriage Bhav): Here's your Marriage Insight.",
        "positive_points": positive_points,
        "negative_points": negative_points,
        "dominant_influence": dominant_line,
        "cta": "➡️ यह एक सामान्य वैवाहिक झलक है। विस्तृत रिपोर्ट ₹98 में प्राप्त करें।" if language == "hi"
        else "➡️ This is a general marriage snapshot. Get a full detailed report based on Dasha & Transit for only ₹98."
    }
