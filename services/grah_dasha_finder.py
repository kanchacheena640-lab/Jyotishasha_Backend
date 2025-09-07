import json
import os

def get_grah_dasha_block(lagna_sign, current_mahadasha, current_antardasha, planets, language="en"):
    """
    Generates a dynamic explanation of Mahadasha and Antardasha based on template rules and traits.
    """

    # Load templates
    with open(os.path.join("data", "lordship_template.json"), "r", encoding="utf-8") as f:
        templates = json.load(f)

    # Load house traits
    traits_file = f"house_traits_{language}.json"
    with open(os.path.join("data", traits_file), "r", encoding="utf-8") as f:
        house_traits = json.load(f)

    # Ordinal maps
    ordinal_map_en = {
        1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th",
        6: "6th", 7: "7th", 8: "8th", 9: "9th", 10: "10th",
        11: "11th", 12: "12th"
    }

    ordinal_map_hi = {
        1: "प्रथम", 2: "द्वितीय", 3: "तृतीय", 4: "चतुर्थ", 5: "पंचम",
        6: "षष्ठ", 7: "सप्तम", 8: "अष्टम", 9: "नवम", 10: "दशम",
        11: "एकादश", 12: "द्वादश"
    }

    ordinal_map = ordinal_map_en if language == "en" else ordinal_map_hi

    # Extract input
    maha_lord = current_mahadasha.get("mahadasha")
    antar_lord = current_antardasha.get("planet")
    maha_house = next((p["house"] for p in planets if p["name"] == maha_lord), None)
    antar_house = next((p["house"] for p in planets if p["name"] == antar_lord), None)

    # Templates
    planet_labels = templates["planet_labels"][language]
    units = templates["units"][language]
    lordship_rules = templates["lordship_rules"]
    special_planets = templates["special_planets"]
    sentence_template = templates["template"][language]
    block_template = templates["mahadasha_antardasha_template"][language]

    def generate_sentence(planet, house):
        traits = house_traits.get(str(house), "important areas of your life")
        house_str = ordinal_map.get(house, str(house))

        if planet in special_planets:
            return special_planets[planet][language].format(
                planet=planet_labels[planet],
                house=house_str,
                traits=traits
            )
        else:
            lordships = lordship_rules.get(planet, [])
            x = lordships[0] if len(lordships) > 0 else None
            y = lordships[1] if len(lordships) > 1 else None
            x_str = ordinal_map.get(x, str(x)) if x else ""
            y_str = ordinal_map.get(y, str(y)) if y else ""

            return sentence_template.format(
                planet=planet_labels[planet],
                x=x_str,
                y=y_str,
                x_unit=units["x_unit"],
                y_unit=units["y_unit"] if y else "",
                and_y=units["and_y"] if y else "",
                house=house_str,
                traits=traits
            )

    # Final grah text
    maha_sentence = generate_sentence(maha_lord, maha_house)
    antar_sentence = generate_sentence(antar_lord, antar_house)

    final_text = block_template.format(
        maha_planet=planet_labels[maha_lord],
        antar_planet=planet_labels[antar_lord],
        maha_sentence=maha_sentence,
        antar_sentence=antar_sentence
    )

    return {
        "mahadasha_planet": maha_lord,
        "mahadasha_house": maha_house,
        "antardasha_planet": antar_lord,
        "antardasha_house": antar_house,
        "grah_dasha_text": final_text,
        "language": language
    }
