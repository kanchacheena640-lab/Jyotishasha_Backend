# Path: modules/love/love_premium_task.py
# Jyotishasha — Love Premium Report Task
#
# This plugs Love Premium into the EXISTING report pipeline.
# No change to old reports.

import os
import traceback
from dotenv import load_dotenv

from openai import OpenAI

from full_kundali_api import calculate_full_kundali
from transit_engine import get_current_positions
from kundali_chart_generator import generate_kundali_drawing
from pdf_generator_weasy import generate_pdf_report_weasy as generate_pdf_report
from email_utils import send_email
from models import Order
from extensions import db
from app import app

# Love-specific modules
from modules.love.love_data_collector import collect_love_report_data
from modules.love.love_prompt_builder import build_love_premium_prompt

load_dotenv()

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def generate_love_premium_report(order_id: int):
    """
    END-TO-END Love Premium Report Generator
    (₹299 / ₹399 product)
    """
    try:
        with app.app_context():

            # ---------------- 1) Fetch Order ----------------
            order = Order.query.get(order_id)
            if not order:
                raise RuntimeError(f"Order {order_id} not found")

            language = getattr(order, "language", "en")

            # ---------------- 2) User Kundali ----------------
            kundali = calculate_full_kundali(
                name=order.name,
                dob=order.dob,
                tob=order.tob,
                lat=float(order.latitude),
                lon=float(order.longitude),
                language=language,
            )

            transit = get_current_positions()
            kundali["transit_summary"] = transit

            # ---------------- 3) Partner safety check ----------------
            partner_payload = getattr(order, "partner_payload", None)
            if not partner_payload:
                raise RuntimeError("Partner details missing for love premium report")

            # ---------------- 4) Love Data Collection ----------------
            love_payload = collect_love_report_data(
                order={
                    "name": order.name,
                    "dob": order.dob,
                    "tob": order.tob,
                    "pob": order.pob,
                    "latitude": order.latitude,
                    "longitude": order.longitude,
                    "language": language,
                    "partner": partner_payload,
                },
                user_kundali=kundali,
                language=language,
                boy_is_user=True,
            )

            # ---------------- 5) Prompt Build ----------------
            final_prompt = build_love_premium_prompt(love_payload)

            # Debug save (recommended)
            os.makedirs("debug_prompts", exist_ok=True)
            with open(f"debug_prompts/love_{order_id}.txt", "w", encoding="utf-8") as f:
                f.write(final_prompt)

            # ---------------- 6) OpenAI Call ----------------
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": final_prompt}],
            )

            report_text = response.choices[0].message.content.strip()

            report_text = report_text[:18000]

            # ---------------- 7) Kundali Drawing ----------------
            RASHI_MAP = {
                "Aries": 1, "Taurus": 2, "Gemini": 3, "Cancer": 4,
                "Leo": 5, "Virgo": 6, "Libra": 7, "Scorpio": 8,
                "Sagittarius": 9, "Capricorn": 10, "Aquarius": 11, "Pisces": 12
            }

            lagna = kundali.get("lagna_rashi") or kundali.get("lagna_sign")
            lagna_number = RASHI_MAP.get(lagna, lagna)

            kundali_drawing = generate_kundali_drawing(
                planets=kundali["planets"],
                lagna_rashi=lagna_number,   # ✅ ab numeric (1–12)
            )

            # ---------------- 8) PDF ----------------
            safe_name = order.name.replace(" ", "_")
            output_path = f"/home/Jyotishasha/reports/love_{safe_name}_{order_id}.pdf"
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            generate_pdf_report(
                output_path=output_path,
                user_info={
                    "name": order.name,
                    "dob": order.dob,
                    "tob": order.tob,
                    "pob": order.pob,
                },
                summary_blocks={},  # Love report uses GPT narrative
                gpt_response=report_text,
                kundali_drawing=kundali_drawing,
                used_placeholders=[],
                product="relationship_future_report",
            )

            del kundali_drawing

            # ---------------- 9) Save + Email ----------------
            order.pdf_url = output_path
            order.report_stage = "Ready"
            db.session.commit()

            send_email(
                order.email,
                "Your Love & Marriage Life Report",
                f"Hello {order.name},\n\nYour Love & Relationship report is ready.",
                output_path,
            )

            import gc
            gc.collect()

    except Exception as e:
        print("[LOVE PREMIUM TASK ERROR]", e)
        traceback.print_exc()
