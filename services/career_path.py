def build_career_report(kundali_data: dict, language: str = "en") -> dict:
    SIGNS = [
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
    ]
    SIGNS_HI = {
        "Aries": "मेष", "Taurus": "वृषभ", "Gemini": "मिथुन", "Cancer": "कर्क", "Leo": "सिंह", "Virgo": "कन्या",
        "Libra": "तुला", "Scorpio": "वृश्चिक", "Sagittarius": "धनु", "Capricorn": "मकर", "Aquarius": "कुंभ", "Pisces": "मीन"
    }
    SIGN_LORDS = {
        "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
        "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
        "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
    }
    PLANET_HI = {
        "Sun": "सूर्य", "Moon": "चंद्र", "Mars": "मंगल", "Mercury": "बुध",
        "Jupiter": "गुरु", "Venus": "शुक्र", "Saturn": "शनि", "Rahu": "राहु", "Ketu": "केतु"
    }
    TRAIT_HI = {
        "Sun": "नेतृत्व और दायित्‍वों से भरे कार्य",
        "Moon": "अपने काम से भावनात्मक जुड़ाव और दिल से",
        "Mars": "प्रेरणा, ऊर्जा और महत्वाकांक्षा",
        "Mercury": "संचार, विश्लेषण और व्यापार",
        "Jupiter": "मार्गदर्शन, शिक्षा और विकास",
        "Venus": "रचनात्मकता, आकर्षण और सामाजिक प्रभाव",
        "Saturn": "अनुशासन, संरचना और अधिकार",
        "Rahu": "अप्रत्याशित सफलता और विदेशी संबंध",
        "Ketu": "अनुसंधान, आध्यात्मिकता और विरक्ति"
    }

    POSITIVE_PLANETS = ["Jupiter", "Moon", "Venus", "Mercury"]
    NEGATIVE_PLANETS = ["Mars", "Saturn", "Rahu", "Ketu", "Sun"]

    def convert_to_hindi(points: list[str]) -> list[str]:
        converted = []
        for line in points:
            for eng, hi in PLANET_HI.items():
                line = line.replace(f"{eng} ", f"{hi} ")
            for eng, hi in SIGNS_HI.items():
                line = line.replace(f"({eng})", f"({hi})")
            line = (
                line.replace("10th house", "दशम भाव")
                    .replace("Lagna", "लग्न")
                    .replace("is placed", "स्थित है")
                    .replace("aspects", "दृष्टि डालता है")
                    .replace("conjoined", "संयुक्त है")
                    .replace("may cause issues", "चुनौतियाँ ला सकता है")
                    .replace("is in a dusthana", "दुष्ट भाव में स्थित है")
                    .replace("is placed in", "में स्थित है")
                    .replace("is", "है")
            )
            converted.append(line)
        return converted

    planets = kundali_data.get("planets", [])
    lagna_sign = kundali_data.get("lagna_sign")
    lagna_house = kundali_data.get("lagna_house", 1)

    lagna_index = SIGNS.index(lagna_sign)
    house_10_sign = SIGNS[(lagna_index + 9) % 12]
    house_10_number = ((lagna_house + 9 - 1) % 12) + 1
    house_10_lord = SIGN_LORDS.get(house_10_sign)

    lord_planet = next((p for p in planets if p["name"] == house_10_lord), None)
    lord_house = lord_planet["house"] if lord_planet else None
    lord_sign = lord_planet["sign"] if lord_planet else None

    positive_points = []
    negative_points = []
    seen_positive = set()
    seen_negative = set()
    dominant_planet = None

    if house_10_lord and lord_sign == house_10_sign:
        if language == "hi":
            pname_hi = PLANET_HI.get(house_10_lord, house_10_lord)
            sign_hi = SIGNS_HI.get(house_10_sign, house_10_sign)
            positive_points.append(f"दशम भाव का स्वामी {pname_hi} अपनी स्वराशि ({sign_hi}) में है।")
        else:
            positive_points.append(f"10th house lord {house_10_lord} is in its own sign ({house_10_sign}).")
        dominant_planet = house_10_lord
        seen_positive.add(house_10_lord)

    if lord_house == lagna_house and house_10_lord not in seen_positive:
        pname_hi = PLANET_HI.get(house_10_lord, house_10_lord)
        positive_points.append(
            f"दशम भाव का स्वामी {pname_hi} लग्न में स्थित है। करियर आपकी पहचान का एक प्रमुख हिस्सा है।"
            if language == "hi" else
            f"10th house lord {house_10_lord} is placed in Lagna."
        )
        if not dominant_planet:
            dominant_planet = house_10_lord
        seen_positive.add(house_10_lord)

    if lord_house in [6, 8, 12]:
        pname_hi = PLANET_HI.get(house_10_lord, house_10_lord)
        negative_points.append(
            f"दशम भाव का स्वामी {pname_hi} दुष्ट भाव ({lord_house}) में स्थित है, जिससे देरी या कर्मिक बाधाएँ आ सकती हैं।"
            if language == "hi" else
            f"10th house lord is in a dusthana ({lord_house})."
        )
        seen_negative.add(house_10_lord)

    aspected_by = []
    tenth_house_objs = [p for p in planets if p["house"] == house_10_number]
    for obj in tenth_house_objs:
        for asp in obj.get("aspected_by", []):
            pname = asp.split()[0]
            if pname not in aspected_by:
                aspected_by.append(pname)

    for planet in aspected_by:
        if planet in POSITIVE_PLANETS and planet not in seen_positive:
            pname_hi = PLANET_HI.get(planet, planet)
            positive_points.append(
                f"{pname_hi} दशम भाव पर दृष्टि डालता है।"
                if language == "hi" else
                f"{planet} aspects 10th house."
            )
            seen_positive.add(planet)
            if not dominant_planet:
                dominant_planet = planet
        elif planet in NEGATIVE_PLANETS and planet not in seen_negative:
            pname_hi = PLANET_HI.get(planet, planet)
            negative_points.append(
                f"{pname_hi} दशम भाव पर दृष्टि डालता है।"
                if language == "hi" else
                f"{planet} aspects 10th house."
            )
            seen_negative.add(planet)

    conjoined_planets = [p for p in planets if p["house"] == lord_house and p["name"] != house_10_lord]
    for p in conjoined_planets:
        pname = p["name"]
        pname_hi = PLANET_HI.get(pname, pname)
        lord_hi = PLANET_HI.get(house_10_lord, house_10_lord)
        if pname in POSITIVE_PLANETS and pname not in seen_positive:
            positive_points.append(
                f"{pname_hi} दशम भाव के स्वामी {lord_hi} के साथ संयुक्त है।"
                if language == "hi" else
                f"{pname} is conjoined with 10th house lord."
            )
            seen_positive.add(pname)
            if not dominant_planet:
                dominant_planet = pname
        elif pname in NEGATIVE_PLANETS and pname not in seen_negative:
            negative_points.append(
                f"{pname_hi} दशम भाव के स्वामी {lord_hi} के साथ संयुक्त है।"
                if language == "hi" else
                f"{pname} is conjoined with 10th house lord."
            )
            seen_negative.add(pname)

    for p in planets:
        if p["house"] != house_10_number or p["name"] == house_10_lord:
            continue
        pname = p["name"]
        bhav_lords = p.get("lord_of", [])
        is_dusthana_lord = any(b in [6, 8, 12] for b in bhav_lords)
        pname_hi = PLANET_HI.get(pname, pname)
        if pname in POSITIVE_PLANETS and not is_dusthana_lord and pname not in seen_positive:
            positive_points.append(
                f"{pname_hi} दशम भाव में स्थित है और करियर में सहयोग देता है।"
                if language == "hi" else
                f"{pname} is placed in 10th house and supports your career."
            )
            seen_positive.add(pname)
            if not dominant_planet:
                dominant_planet = pname
        elif (pname in NEGATIVE_PLANETS or is_dusthana_lord) and pname not in seen_negative:
            negative_points.append(
                f"{pname_hi} दशम भाव में स्थित है और बाधाएँ ला सकता है।"
                if language == "hi" else
                f"{pname} is in 10th house and may cause issues."
            )
            seen_negative.add(pname)

    dominant_line = ""
    if dominant_planet:
        if language == "hi":
            trait_hi = TRAIT_HI.get(dominant_planet, "करियर विकास")
            dominant_line = f"{PLANET_HI.get(dominant_planet, dominant_planet)} का आपके करियर पर गहरा प्रभाव है। इससे {trait_hi} जैसे गुण विकसित होते हैं।"
        else:
            trait = {
                "Sun": "leadership and recognition",
                "Moon": "emotional connection and public appeal",
                "Mars": "drive, ambition, and energy",
                "Mercury": "communication, commerce, and analytics",
                "Jupiter": "guidance, education, and growth",
                "Venus": "creativity, charm, and social influence",
                "Saturn": "discipline, structure, and authority",
                "Rahu": "unconventional success and foreign connections",
                "Ketu": "research, spirituality, and detached roles"
            }.get(dominant_planet, "career growth")
            dominant_line = f"{dominant_planet} has a dominant influence on your career. This brings traits like {trait}."

    return {
        "tool_id": "career-path",
        "language": language,
        "heading": "दशम भाव (कर्म भाव): यह आपका वैदिक करियर विश्लेषण है।" if language == "hi"
                   else "10th House (Karma Bhav): Here's your Vedic Career Insight.",
        "positive_points": convert_to_hindi(positive_points) if language == "hi" else positive_points,
        "negative_points": convert_to_hindi(negative_points) if language == "hi" else negative_points,
        "dominant_influence": dominant_line,
        "cta": "➡️ यह एक सामान्य करियर झलक है। आपकी दशा और गोचर के अनुसार अधिक विस्तृत करियर रिपोर्ट ₹98 में प्राप्त करें।" if language == "hi"
               else "➡️ This is a general career snapshot. Get a full detailed report based on Dasha & Transit for only ₹98."
    }
