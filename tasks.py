import os
import re
import sys
import traceback
from dotenv import load_dotenv
from celery_app import celery
from extensions import db
from models import Order
#from pdf_generator import generate_pdf_report
from email_utils import send_email
from summary_blocks import build_summary_blocks_with_transit
from full_kundali_api import calculate_full_kundali
from transit_engine import get_current_positions
from openai import OpenAI
from kundali_chart_generator import generate_kundali_drawing
from pdf_generator_weasy import generate_pdf_report_weasy as generate_pdf_report

# 🔧 Fix for app context
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app import app

# Load env
load_dotenv()

# OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@celery.task(name='tasks.generate_and_send_report')
def generate_and_send_report(order_id):
    print(f"[Task] Starting report generation for Order ID: {order_id}")

    try:
        with app.app_context():
            # Step 1: Order fetch
            print("[Step 1] Fetching order details")
            order = get_order_details(order_id)
            if not order:
                print(f"[ERROR] Order {order_id} not found!")
                return
            
            # ✅ Language set here
            language = order.get("language", "en")
            print("[DEBUG] Language for this order:", language)

            # Step 2: Kundali calculation

            print("[Step 2] Calculating kundali")
            kundali = calculate_full_kundali(
                name=order["name"],
                dob=order["dob"],
                tob=order["tob"],
                lat=float(order.get("latitude", 28.6139)),
                lon=float(order.get("longitude", 77.2090)),
                language=language  # ✅ now dynamic (hi/en)
            )
            print("[DEBUG] Kundali keys:", kundali.keys())

            transit = get_current_positions()
            kundali["transit_summary"] = transit

            # Step 3: Summary blocks
            print("[Step 3] Building summary blocks")
            summary_blocks = build_summary_blocks_with_transit(kundali, transit)

            # Step 4: Prompt load
            print("[Step 4] Loading prompt template")
            product_slug = order["product"]
            template_path = f"prompts/{product_slug}_{language}.txt"

            try:
                with open(template_path, encoding="utf-8") as f:
                    template = f.read()
            except FileNotFoundError:
                # Optional safe fallback if Hindi template missing
                print(f"[WARN] Template not found: {template_path}. Falling back to EN.")
                with open(f"prompts/{product_slug}_en.txt", encoding="utf-8") as f:
                    template = f.read()

            used_placeholders = re.findall(r"{(.*?)}", template)
            prompt_final = template.format(**summary_blocks)

            # ✅ Save prompt for debugging
            with open(f"debug_prompts/{product_slug}_{order_id}_prompt.txt", "w", encoding="utf-8") as debug_file:
                debug_file.write(prompt_final)
            print(f"[DEBUG] Prompt written to debug_prompts/{product_slug}_{order_id}_prompt.txt")

            # Step 5: GPT call
            print("[Step 5] Calling OpenAI GPT")
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt_final}]
            )
            gpt_content = response.choices[0].message.content.strip()
            print("[DEBUG] GPT response length:", len(gpt_content))

            # ✅ Save GPT response for debugging
            with open(f"debug_prompts/{product_slug}_{order_id}_gpt_response.txt", "w", encoding="utf-8") as f:
                f.write(gpt_content)
            print(f"[DEBUG] GPT response saved to debug_prompts/{product_slug}_{order_id}_gpt_response.txt")

            # Step 6: Image + PDF
            print("[Step 6] Generating image and PDF")
            safe_name = order["name"].replace(" ", "_")
            kundali_image_path = f"/home/Jyotishasha/reports/kundali_{safe_name}.png"

            # ---- Lagna Rashi Handling ----
            lagna_rashi = kundali.get("lagna_rashi") or kundali.get("lagna_sign")
            if not lagna_rashi:
                raise ValueError("Missing lagna_rashi (or lagna_sign) in kundali result")
            print("[DEBUG] lagna_rashi (raw):", lagna_rashi)

            # Convert string → number
            RASHI_MAP = {
                "Aries": 1, "Taurus": 2, "Gemini": 3, "Cancer": 4,
                "Leo": 5, "Virgo": 6, "Libra": 7, "Scorpio": 8,
                "Sagittarius": 9, "Capricorn": 10, "Aquarius": 11, "Pisces": 12
            }

            if isinstance(lagna_rashi, str):
                rashi_number = RASHI_MAP.get(lagna_rashi)
            else:
                rashi_number = lagna_rashi

            if not rashi_number:
                raise ValueError(f"Unknown lagna_rashi: {lagna_rashi}")

            print("[DEBUG] lagna_rashi (number):", rashi_number)

            # Generate Kundali Drawing (no PNG now)
            kundali_drawing = generate_kundali_drawing(
                planets=kundali["planets"],
                lagna_rashi=rashi_number
            )

            # Generate PDF
            output_path = f"/home/Jyotishasha/reports/{product_slug}_{safe_name}.pdf"
            print("[DEBUG] PDF output path:", output_path)

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
                kundali_drawing=kundali_drawing,   # 🔑 new arg
                used_placeholders=used_placeholders,
                product=order["product"]
            )

            # Save PDF URL to database
            order_model = Order.query.get(order_id)
            if order_model:
                order_model.pdf_url = output_path
                order_model.report_stage = "Ready"
                db.session.commit()
                print(f"[DEBUG] PDF URL saved to DB: {output_path}")

            # Step 7: Email send
            print("[Step 7] Sending email")
            subject = f"Your {product_slug.replace('-', ' ').title()} Report"
            body = (
                f"Hello {order['name']},\n\n"
                f"Please find attached your personalized astrology report.\n\n"
                f"Regards,\nTeam Jyotishasha"
            )
            send_email(order['email'], subject, body, output_path)
            print(f"[Task] ✅ Email sent to {order['email']}")

    except Exception as e:
        print(f"[Task] ❌ Error generating report: {e}")
        traceback.print_exc()


def get_order_details(order_id):
    """Fetch order details safely with app context"""
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
            "language": getattr(order, "language", "en")
        }

# ✅ Windows-only safety
if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()
