# summary_blocks.py

def build_summary_blocks_with_transit(kundali: dict, transit: dict) -> dict:
    planets = kundali.get("planets", [])
    lagna_sign = kundali.get("lagna_sign", "")

    # 1. Birth Chart Summary
    birth_lines = [f"You have a {lagna_sign} Ascendant."]
    for p in planets:
        if p['name'] != 'Ascendant (Lagna)':
            birth_lines.append(f"{p['name']} is placed in {p['house']}th house ({p['sign']}).")
    birth_chart_summary = " ".join(birth_lines)

    # 2. Aspect Summary
    aspect_lines = []
    for p in planets:
        aspects = p.get("aspecting", [])
        if aspects:
            aspect_lines.append(f"{p['name']} is aspecting {', '.join(aspects)}.")
    aspect_summary = " ".join(aspect_lines)

    # 3. Manglik Summary
    manglik_raw = kundali.get("manglik_dosh", {})
    manglik_summary = "You are Mangalik." if manglik_raw.get("is_manglik") else "You are not Mangalik."

    # 4. Mahadasha Summary
    maha = kundali.get("current_mahadasha", {})
    antar = kundali.get("current_antardasha", {})
    next_change = antar.get("end")
    mahadasha_summary = (
        f"You are currently in the Mahadasha of {maha.get('mahadasha')} and Antardasha of {antar.get('planet')}. "
        f"This phase will end on {next_change}."
    )

    # 5. Current Transit Summary
    current_positions = transit.get("positions", {})
    lagna_lord = None
    for p in planets:
        if p.get("house") == 1:
            lagna_lord = p.get("name")
            break

    transit_lines = []
    if lagna_lord and lagna_lord in current_positions:
        lagna_data = current_positions[lagna_lord]
        transit_lines.append(
            f"Your Lagna lord {lagna_lord} is transiting in {lagna_data['rashi']} ({lagna_data['degree']}°)."
        )

    for planet in ["Saturn", "Jupiter"]:
        if planet in current_positions:
            p = current_positions[planet]
            transit_lines.append(f"{planet} is currently in {p['rashi']} at {p['degree']}°, moving {p['motion']}.")

    current_transit_summary = " ".join(transit_lines) if transit_lines else "Transit data not available."

    return {
        "birth_chart_summary": birth_chart_summary,
        "aspect_summary": aspect_summary,
        "manglik_summary": manglik_summary,
        "mahadasha_summary": mahadasha_summary,
        "current_transit_summary": current_transit_summary
    }
