import os

TEMPLATE_DIR = "prompt_templates"

def load_template(product):
    safe_name = product.lower().replace(" ", "_") + ".txt"
    path = os.path.join(TEMPLATE_DIR, safe_name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Prompt template not found for: {product}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_prompt_from_product(product, kundali, transit_data, language="en"):
    template = load_template(product)

    # Extract basic info
    name = kundali.get("name", "User")
    dob = kundali.get("dob", "NA")
    tob = kundali.get("tob", "NA")
    pob = kundali.get("pob", "NA")
    moon_sign = kundali.get("moon_traits", {}).get("title", "NA")
    lagna_sign = kundali.get("lagna_sign", "NA")

    # Birth chart summary
    birth_chart_summary = kundali.get("birth_chart_summary", "Not Available")

    # Dasha summary
    dasha_summary = kundali.get("grah_dasha_block", {}).get("grah_dasha_text", "Not Available")

    # Transit summary
    transit_summary = build_transit_summary_text(transit_data)

    # Sade Sati summary (optional)
    sadhesati_summary = kundali.get("3rd_phase", {}).get("summary", "Not Available")

    # Placeholder mapping
    filled_prompt = template.format(
        name=name,
        dob=dob,
        tob=tob,
        pob=pob,
        moon_sign=moon_sign,
        lagna_sign=lagna_sign,
        birth_chart_summary=birth_chart_summary,
        dasha_summary=dasha_summary,
        transit_summary=transit_summary,
        sadhesati_summary=sadhesati_summary
    )

    return filled_prompt


def build_transit_summary_text(transit_data: dict) -> str:
    positions = transit_data.get("positions", {})
    summary_lines = []

    for planet, details in positions.items():
        sign = details.get("sign", "")
        house = details.get("house", "")
        aspects = details.get("aspected_by", [])
        
        line = f"{planet} is currently in {sign} (House {house})"
        if aspects:
            line += f", aspected by: {', '.join(aspects)}"
        
        summary_lines.append(line)

    return "\n".join(summary_lines)

