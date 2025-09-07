from flask import Blueprint, request, jsonify
from full_kundali_api import calculate_full_kundali
from transit_engine import get_current_positions
from summary_blocks import build_summary_blocks_with_transit
from pdf_generator import generate_pdf_report
from openai import OpenAI
import os
import re

summary_api = Blueprint('summary_api', __name__)

# Initialize OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@summary_api.route("/api/generate-summary-report", methods=["POST"])
def generate_full_summary_report():
    # Step 1: Get user input
    data = request.get_json()
    name = data["name"]
    dob = data["dob"]
    tob = data["tob"]
    lat = float(data["latitude"])
    lon = float(data["longitude"])
    pob = data.get("pob", "Unknown")
    full_product = data["product"]  # e.g., "marriage-report_en"

    product_slug = full_product.split("_")[0]  # "marriage-report"
    language = full_product.split("_")[-1]     # "en"

    # Step 2: Generate kundali and transit
    kundali = calculate_full_kundali(name, dob, tob, lat, lon, language)
    transit = get_current_positions()

    # Step 3: Build summaries
    summary_blocks = build_summary_blocks_with_transit(kundali, transit)

    # Step 4: Load prompt and extract placeholders used
    try:
        with open(f"prompts/{product_slug}_{language}.txt", encoding="utf-8") as f:
            template = f.read()
    except FileNotFoundError:
        return jsonify({"error": f"Prompt template not found for '{product_slug}_{language}'"}), 400

    used_placeholders = re.findall(r"{(.*?)}", template)
    try:
        prompt_final = template.format(**summary_blocks)
    except KeyError as e:
        return jsonify({"error": f"Missing placeholder in summary: {e}"}), 400

    # Step 5: Send to GPT
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt_final}]
        )
        gpt_content = response.choices[0].message.content
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Step 6: Generate PDF
    output_path = f"reports/{product_slug}_{name}.pdf"
    generate_pdf_report(
        output_path=output_path,
        user_info={
            "name": name,
            "dob": dob,
            "tob": tob,
            "pob": pob
        },
        summary_blocks=summary_blocks,
        gpt_response=gpt_content,
        kundali_image_path=f"reports/kundali_{name}.png",  # or dummy for now
        used_placeholders=used_placeholders
    )

    return jsonify({
        "summary": summary_blocks,
        "gpt_response": gpt_content,
        "pdf_path": output_path
    })
