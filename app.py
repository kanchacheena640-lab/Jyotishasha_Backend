from flask import Flask, request, jsonify
from flask_cors import CORS
from factory import create_app
from extensions import db
from routes.routes_user import routes_user
from modules.auth.models import User
from full_kundali_api import calculate_full_kundali
from services.zodiac_service import get_zodiac_traits
from transit_engine import get_current_positions, get_all_planets_next_12
from life_tools_report import life_tools_bp
from routes.generate_report import generate_report_bp
from openai import OpenAI
import os
from dotenv import load_dotenv
load_dotenv()
from config.razorpay_config import razorpay_client
from config.pricing import PRODUCT_PRICES
from routes.admin_orders import admin_orders_bp
from summary_api import summary_api
from routes.daily_horoscope import daily_bp
from routes.monthly_horoscope import monthly_bp
from routes.routes_panchang import routes_panchang
from flask_migrate import Migrate
from extensions import db, jwt
from modules.auth import register_auth
from modules.subscription import register_subscription
from modules.auth.routes_profile import profile_bp
from flask import send_file
from models import Order
from routes.full_kundali_route import full_kundali_modern_bp
from routes.routes_free_consult import routes_free_consult
from routes.routes_subscription import routes_subscription
from routes.routes_asknow import routes_asknow
from routes.personalized_daily import personalized_daily
from routes.routes_profile_bootstrap import routes_profile_bootstrap
from routes.routes_chat import routes_chat
from routes.routes_smartchat import routes_smartchat
from routes.routes_auth import routes_auth
from routes.routes_admin_tokens import routes_admin_tokens








app = create_app()
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
migrate = Migrate(app, db)
app.register_blueprint(life_tools_bp)
app.register_blueprint(generate_report_bp)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app.register_blueprint(admin_orders_bp)
app.register_blueprint(summary_api)
app.register_blueprint(daily_bp)
app.register_blueprint(monthly_bp)
app.register_blueprint(routes_panchang)
jwt.init_app(app)
register_auth(app)
register_subscription(app)
app.register_blueprint(profile_bp, url_prefix="/api/profile")
app.register_blueprint(full_kundali_modern_bp)
app.register_blueprint(routes_free_consult)
app.register_blueprint(routes_user)
app.register_blueprint(routes_subscription)
app.register_blueprint(routes_asknow)
app.register_blueprint(personalized_daily)
app.register_blueprint(routes_profile_bootstrap)
app.register_blueprint(routes_chat)
app.register_blueprint(routes_smartchat)
app.register_blueprint(routes_auth)
app.register_blueprint(routes_admin_tokens)






# ------------------- ROOT ------------------- #
@app.route("/")
def home():
        return "Backend is connected with DB + Celery!"

@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({"ok": True})

# ------------------- USER APIs ------------------- #
@app.route("/add_user", methods=["POST"])
def add_user():
    data = request.get_json()
    name = data.get("name")
    email = data.get("email")
    if not name or not email:
        return jsonify({"error": "Name and Email are required"}), 400

    user = User(name=name, email=email)
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "User added successfully!", "user_id": user.id})

# ------------------- ZODIAC TRAITS ------------------- #
@app.route('/api/zodiac-traits')
def zodiac_traits():
    sign = request.args.get('sign', '')
    lang = request.args.get('lang', 'en')  # Default to English
    data = get_zodiac_traits(sign, lang)

    if not data:
        return jsonify({"error": f"No data found for '{sign}'"}), 404

    return jsonify(data)

# ------------------- WEBHOOK ------------------- #
@app.route("/webhook", methods=["POST"])
def webhook():
    from app_config import USE_CELERY  # 🔁 toggle flag
    from tasks import generate_and_send_report  # local import (avoid circular)

    data = request.get_json()

    # ✅ Case A: Razorpay webhook (event = payment.captured)
    if "event" in data and data.get("event") == "payment.captured":
        print("[Webhook] Razorpay payment.captured webhook received. Ignored for now.")
        return jsonify({"status": "Webhook received (ignored)"}), 200

    # ✅ Case B: Frontend-triggered report request
    name = data.get("name")
    email = data.get("email")
    phone = data.get("phone")
    product = data.get("product")
    dob = data.get("dob")
    tob = data.get("tob")
    pob = data.get("pob")
    language = data.get("language", "en")

    if not all([name, email, product]):
        return jsonify({"error": "Missing required fields"}), 400

    # Save order in DB
    order = Order(
        name=name,
        email=email,
        phone=phone,
        product=product,
        dob=dob,
        tob=tob,
        pob=pob,
        language=language,
        status="PAID",
        latitude=data.get("latitude"),
        longitude=data.get("longitude")
    )
    db.session.add(order)
    db.session.commit()

    # ----------------------------------------------------------
    # 🔁 DUAL MODE LOGIC — Decide based on USE_CELERY flag
    # ----------------------------------------------------------
    if USE_CELERY:
        # 🧵 ASYNC MODE (Celery + Redis)
        print(f"[Webhook] Queuing async task for Order {order.id}")
        task = generate_and_send_report.delay(order.id)
        return jsonify({
            "message": "Webhook received — report task queued",
            "order_id": order.id,
            "task_id": task.id
        }), 200
    else:
        # ⚡ SYNC MODE (Direct execution, no Celery)
        print(f"[Webhook] Running report directly for Order {order.id}")
        generate_and_send_report(order.id)
        return jsonify({
            "message": "Webhook received — report generated successfully",
            "order_id": order.id
        }), 200


# ------------------- FOR TRANSIT DATA ------------------- #

@app.route("/api/transit/current", methods=["GET"])
def transit_current_plus_12():
    """
    Clean, single payload:
    {
      "timestamp_ist": "...",
      "positions": { ...9 planets... },
      "future_transits": {
        "Sun":   [ {planet, from_rashi, to_rashi, entering_date, exit_date} x12 ],
        "Moon":  [ ... x12 ],
        ...
        "Ketu":  [ ... x12 ]
      }
    }
    """
    current = get_current_positions()
    future = get_all_planets_next_12()
    return jsonify({**current, "future_transits": future})

# ------------------- ADD MORE HEre ------------------- #

# ------------------- ADMIN REPORT DOWNLOAD ------------------- #

@app.route("/admin/download/<int:order_id>")
def admin_download_report(order_id):
    """
    Admin ke liye report download endpoint.
    Jab admin panel se link click hoga, ye PDF ko direct download karega.
    File system ka path expose nahi hoga.
    """
    order = Order.query.get(order_id)
    if not order or not order.pdf_url:
        return {"error": "Report not found"}, 404

    return send_file(
        order.pdf_url,
        as_attachment=True,   # ✅ force download karega
        download_name=f"{order.product}_{order.name}.pdf"
    )
    
# ------------------- KUNDALI API ------------------- #
@app.route("/api/full-kundali", methods=["POST", "OPTIONS"])
def full_kundali():
    # ✅ Handle CORS preflight (OPTIONS request)
    if request.method == "OPTIONS":
        response = jsonify({"message": "CORS preflight successful"})
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type")
        response.headers.add("Access-Control-Allow-Methods", "POST, OPTIONS")
        return response, 200

    try:
        data = request.get_json()
        language = data.get("language", "en")
        kundali = calculate_full_kundali(
            name=data.get("name", "User"),
            dob=data["dob"],
            tob=data["tob"],
            lat=float(data["latitude"]),
            lon=float(data["longitude"]),
            language=language
        )
        response = jsonify(kundali)
        response.headers.add("Access-Control-Allow-Origin", "*")  # ✅ Ensure CORS header on actual POST
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    
# ------------------- RAZORPAY ORDER CREATE ------------------- #
@app.route("/api/razorpay-order", methods=["POST"])
def create_razorpay_order():
    import time
    try:
        data = request.get_json() or {}
        product_id_raw = data.get("product", "")
        product_id = (product_id_raw or "").strip().lower()   # ✅ normalize

        # ✅ Lowercase mapping banado
        prices_lc = {str(k).lower(): v for k, v in PRODUCT_PRICES.items()}
        if product_id not in prices_lc:
            return jsonify({"error": f"Invalid product selected: {product_id_raw}"}), 400

        amount_rupees = prices_lc[product_id]

        # ✅ Always int paise
        try:
            amount_paise = int(round(float(amount_rupees) * 100))
        except Exception:
            return jsonify({"error": f"Invalid amount for {product_id_raw}: {amount_rupees}"}), 400

        receipt = f"order_{os.urandom(4).hex()}"

        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "payment_capture": 1,
            "notes": {"product": product_id},
        }

        # ✅ Retry safeguard
        try:
            rp_order = razorpay_client.order.create(payload)
        except Exception as e1:
            print("⚠️ Razorpay order first attempt failed:", str(e1))
            time.sleep(0.8)
            try:
                rp_order = razorpay_client.order.create(payload)
            except Exception as e2:
                print("❌ Razorpay order second attempt also failed:", str(e2))
                raise e2
            
        return jsonify({
            "order_id": rp_order.get("id"),
            "currency": rp_order.get("currency", "INR"),
            "amount": int(round(float(amount_rupees))),
            "product": product_id_raw
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400



# ------------------- MAIN ------------------- #
if __name__ == "__main__":
    app.run(debug=True)
