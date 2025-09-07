import json

def load_json(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_dignity(planet_name, planet_sign):
    dignities = {
        "Sun": {"exalted": "Aries", "debilitated": "Libra", "own": ["Leo"]},
        "Moon": {"exalted": "Taurus", "debilitated": "Scorpio", "own": ["Cancer"]},
        "Mars": {"exalted": "Capricorn", "debilitated": "Cancer", "own": ["Aries", "Scorpio"]},
        "Mercury": {"exalted": "Virgo", "debilitated": "Pisces", "own": ["Gemini", "Virgo"]},
        "Jupiter": {"exalted": "Cancer", "debilitated": "Capricorn", "own": ["Sagittarius", "Pisces"]},
        "Venus": {"exalted": "Pisces", "debilitated": "Virgo", "own": ["Taurus", "Libra"]},
        "Saturn": {"exalted": "Libra", "debilitated": "Aries", "own": ["Capricorn", "Aquarius"]},
        "Rahu": {"exalted": "Taurus", "debilitated": "Scorpio"},
        "Ketu": {"exalted": "Scorpio", "debilitated": "Taurus"},
    }
    info = dignities.get(planet_name, {})
    if not info:
        return "Neutral"
    if planet_sign == info.get("exalted"):
        return "Exalted"
    elif planet_sign == info.get("debilitated"):
        return "Debilitated"
    elif planet_sign in info.get("own", []):
        return "Own Sign"
    else:
        return "Neutral"

def get_house_suffix(n):
    return "th" if 11 <= n <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")

def get_planet_overview(planets: list, language: str = "en"):
    house_traits = load_json(f"data/house_traits_{language}.json")
    aspect_effects = load_json(f"data/aspect_effects_{language}.json")
    dignity_effects = load_json(f"data/dignity_effects_{language}.json")
    lagna_traits = load_json(f"data/lagna_traits_{language}.json")
    nakshatra_names_hi = load_json("data/nakshatra_names_hi.json") if language == "hi" else {}
    name_map = load_json("data/name_mappings.json") if language == "hi" else {}
    planet_labels = name_map["planet_labels"] if language == "hi" else {}
    sign_labels = name_map["sign_labels"] if language == "hi" else {}

    overview = []

    for planet in planets:
        name = planet["name"]
        sign = planet["sign"]
        house = planet["house"]
        nakshatra = planet.get("nakshatra", "")
        pada = planet.get("pada", "")
        lord_of = planet.get("lord_of", [])
        aspected_by = planet.get("aspected_by", [])
        aspecting = planet.get("aspecting", [])
        dignity = planet.get("dignity") or get_dignity(name, sign)

        nakshatra_display = nakshatra_names_hi.get(nakshatra, nakshatra) if language == "hi" else nakshatra
        planet_display = planet_labels.get(name, name) if language == "hi" else planet_labels.get(name, name)
        sign_display = sign_labels.get(sign, sign) if language == "hi" else sign_labels.get(sign, sign)

        raw_dignity = dignity_effects.get(dignity, "")

        if isinstance(raw_dignity, dict):
            dignity_msg = raw_dignity.get("description", "").replace("{planet}", planet_display)
        elif isinstance(raw_dignity, str):
            dignity_msg = raw_dignity.replace("{planet}", planet_display)
        else:
            dignity_msg = ""

        house_suffix = get_house_suffix(house)
        house_trait = house_traits.get(str(house), "")
        unique_aspected_by = list(dict.fromkeys([a.split(" ")[0] for a in aspected_by]))
        aspect_text = ", ".join(unique_aspected_by)
        if language == "hi":
            aspect_effect_text = ", ".join([
                aspect_effects[a]["description"].replace("{planet}", planet_display)
                for a in unique_aspected_by
                if isinstance(aspect_effects.get(a), dict) and isinstance(aspect_effects[a].get("description"), str)
            ])
        else:
            aspect_effect_text = ", ".join([
                aspect_effects[a]["description"].replace("{planet}", planet_display)
                for a in unique_aspected_by
                if isinstance(aspect_effects.get(a), dict) and isinstance(aspect_effects[a].get("description"), str)
            ])

        # 🟠 Bullet block
        position = f"• Position: {sign}, {house}{house_suffix} House"
        nakshatra_line = f"• Nakshatra: {nakshatra_display} (Pada {pada})" if nakshatra else ""
        dignity_line = f"• Dignity: {dignity}"
        lord_house_list = [f"{h}th ({house_traits.get(str(h), '')})" for h in lord_of]
        lord_line = f"• Lord of: {', '.join(lord_house_list)}" if lord_of else ""
        aspected_by_line = f"• Aspected by: {aspect_text}" if aspect_text else ""
        aspecting_line = f"• Aspecting: {', '.join(aspecting)}" if aspecting else ""

        bullet_block = "\n".join(filter(None, [
            position,
            nakshatra_line,
            dignity_line,
            lord_line,
            aspected_by_line,
            aspecting_line
        ]))

        # 🟢 Paragraph
        text_lines = []

        if "ascendant" in name.lower() or "lagna" in name.lower():
            lagna_template = lagna_traits.get(sign, "")
            if lagna_template:
                text = (
                    lagna_template
                    .replace("{nakshatra}", nakshatra_display)
                    .replace("{pada}", str(pada))
                    .replace("{aspect_effects}", aspect_effect_text)
                )
            else:
                text = f"Ascendant in {sign} — traits unavailable."
        else:
            if language == "hi":
                text_lines.append(
                    f"{planet_display} {house}{house_suffix} भाव में {sign_display} राशि में स्थित है, यह आपके जीवन में {house_trait} क्षेत्रों को प्रभावित करेगा।"
                )
            else:
                text_lines.append(
                    f"{planet_display} is in the sign of {sign_display}, positioned in the {house}{house_suffix} house of {house_trait}."
                )

            if nakshatra:
                if language == "hi":
                    text_lines.append(
                        f"{planet_display} {nakshatra_display} नक्षत्र के पद {pada} में स्थित है, जो विशेष ऊर्जा प्रदान करता है।"
                    )
                else:
                    text_lines.append(
                        f"{planet_display} lies in the Nakshatra of {nakshatra_display}, Pada {pada}, which brings intuitive qualities."
                    )

            if unique_aspected_by:
                effect_texts = []
                if language == "hi":
                    aspect_text_hi = ", ".join([
                        f"{p} ({planet_labels.get(p, '')})" if planet_labels.get(p) else p for p in unique_aspected_by
                    ])
                    for asp in unique_aspected_by:
                        effect_info = aspect_effects.get(asp)
                        if effect_info and effect_info.get("description"):
                            effect_texts.append(effect_info["description"].replace("{planet}", planet_display))

                    if effect_texts:
                        text_lines.append(
                            f"इस स्थिति पर {aspect_text_hi} की दृष्टि है — " +
                            " ".join(effect_texts)
                        )
                else:
                    aspect_text = ", ".join(unique_aspected_by)
                    for asp in unique_aspected_by:
                        effect_info = aspect_effects.get(asp)
                        if effect_info and effect_info.get("description"):
                            effect_texts.append(effect_info["description"].replace("{planet}", planet_display))

                    if effect_texts:
                        text_lines.append(
                            f"This placement is influenced by {aspect_text} — " +
                            " ".join(effect_texts)
                        )

            if language == "hi":
                text_lines.append("समग्र रूप से, इस क्षेत्र में मिश्रित अनुभव, चुनौतियाँ और संभावनाएँ देखने को मिल सकती हैं।")
            else:
                text_lines.append("Overall, expect a mix of strengths and lessons in this area.")

            text = " ".join(text_lines)

        overview.append({
            "planet": planet_labels.get(name, name),
            "summary": bullet_block.strip(),
            "text": text.strip()
        })

    return overview
