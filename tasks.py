import os
import re
import sys
import traceback
from dotenv import load_dotenv
from extensions import db
from models import Order
from email_utils import send_email
from summary_blocks import build_summary_blocks_with_transit
from full_kundali_api import calculate_full_kundali
from transit_engine import get_current_positions
from openai import OpenAI
from kundali_chart_generator import generate_kundali_drawing
from pdf_generator_weasy import generate_pdf_report_weasy as generate_pdf_report

# ------------------------------------------------------------
# 🧩 Optional Celery/Redis setup — enabled only if USE_CELERY=True
# ------------------------------------------------------------
from app_config import USE_CELERY
if USE_CELERY:
    from celery_app import celery
else:
    celery = None  # dummy placeholder for compatibility

# 🔧 Fix for app context
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app import app

# Load environment variables
load_dotenv()

# OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ------------------------------------------------------------
# 🚀 Dual-Mode Task Definition
# ------------------------------------------------------------
def _generate_and_send_report_core(order_id):
    """Shared report generation logic for both Celery and direct modes."""
    print(f"[Task] Starting report generation for Order ID: {order_id}")

    try:
        with app.app_context():
            # Step 1: Order fetch
            order = get_order_details(order_id)
            if not order:
                print(f"[ERROR] Order {order_id} not found!")
                return

            language = order.get("language", "en")
            print(f"[DEBUG] Language for this order: {language}")

            # Step 2: Kundali calculation
            kundali = calculate_full_kundali(
                name=order["name"],
                dob=order["dob"],
                tob=order["tob"],
                lat=float(order.get("latitude", 28.6139)),
                lon=float(order.get("longitude", 77.2090)),
                language=language
            )

            transit = get_current_positions()
            kundali["transit_summary"] = transit

            # Step 3: Summary blocks
            summary_blocks = build_summary_blocks_with_transit(kundali, transit)

            # Step 4: Prompt load
            product_slug = order["product"]
            template_path = f"prompts/{product_slug}_{language}.txt"
            try:
                with open(template_path, encoding="utf-8") as f:
                    template = f.read()
            except FileNotFoundError:
                print(f"[WARN] Template not found: {template_path}. Falling back to EN.")
                with open(f"prompts/{product_slug}_en.txt", encoding="utf-8") as f:
                    template = f.read()

            used_placeholders = re.findall(r"{(.*?)}", template)
            prompt_final = template.format(**summary_blocks)

            # Save prompt for debugging
            os.makedirs("debug_prompts", exist_ok=True)
            with open(f"debug_prompts/{product_slug}_{order_id}_prompt.txt", "w", encoding="utf-8") as f:
                f.write(prompt_final)

            # Step 5: GPT call
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt_final}]
            )
            gpt_content = response.choices[0].message.content.strip()

            with open(f"debug_prompts/{product_slug}_{order_id}_gpt_response.txt", "w", encoding="utf-8") as f:
                f.write(gpt_content)

            # Step 6: Image + PDF
            safe_name = order["name"].replace(" ", "_")
            lagna_rashi = kundali.get("lagna_rashi") or kundali.get("lagna_sign")
            if not lagna_rashi:
                raise ValueError("Missing lagna_rashi in kundali result")

            RASHI_MAP = {
                "Aries": 1, "Taurus": 2, "Gemini": 3, "Cancer": 4,
                "Leo": 5, "Virgo": 6, "Libra": 7, "Scorpio": 8,
                "Sagittarius": 9, "Capricorn": 10, "Aquarius": 11, "Pisces": 12
            }
            rashi_number = RASHI_MAP.get(lagna_rashi) if isinstance(lagna_rashi, str) else lagna_rashi

            kundali_drawing = generate_kundali_drawing(
                planets=kundali["planets"],
                lagna_rashi=rashi_number
            )

            output_path = f"/home/Jyotishasha/reports/{product_slug}_{safe_name}.pdf"
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            generate_pdf_report(
                output_path=output_path,
                user_info={
                    "name": order["name"],
                    "dob": order["dob"],
                    "tob": order["tob"],
                    "pob": order["pob"]
                },
                summary_blocks=summary_blocks,
                gpt_response=gpt_content,
                kundali_drawing=kundali_drawing,
                used_placeholders=used_placeholders,
                product=order["product"]
            )

            # Step 7: Save + Email
            order_model = Order.query.get(order_id)
            if order_model:
                order_model.pdf_url = output_path
                order_model.report_stage = "Ready"
                db.session.commit()

            subject = f"Your {product_slug.replace('-', ' ').title()} Report"
            body = (
                f"Hello {order['name']},\n\n"
                f"Please find attached your personalized astrology report.\n\n"
                f"Regards,\nTeam Jyotishasha"
            )
            send_email(order["email"], subject, body, output_path)
            print(f"[Task] ✅ Email sent to {order['email']}")

    except Exception as e:
        print(f"[Task] ❌ Error generating report: {e}")
        traceback.print_exc()


# ------------------------------------------------------------
# 🧩 Mode Bridge — Choose Celery or Direct based on USE_CELERY
# ------------------------------------------------------------
if USE_CELERY:
    @celery.task(name="tasks.generate_and_send_report")
    def generate_and_send_report(order_id):
        """Celery asynchronous mode"""
        _generate_and_send_report_core(order_id)
else:
    def generate_and_send_report(order_id):
        """Direct synchronous mode"""
        _generate_and_send_report_core(order_id)


# ------------------------------------------------------------
# 🧾 Helper: fetch order details
# ------------------------------------------------------------
def get_order_details(order_id):
    from app import app
    with app.app_context():
        order = Order.query.get(order_id)
        if not order:
            return None
        return {
            "name": order.name,
            "email": order.email,
            "product": order.product,
            "dob": order.dob,
            "tob": order.tob,
            "pob": order.pob,
            "phone": order.phone,
            "status": order.status,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "latitude": getattr(order, "latitude", 28.6139),
            "longitude": getattr(order, "longitude", 77.2090),
            "language": getattr(order, "language", "en"),
        }


# ✅ Windows-only safety
if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
