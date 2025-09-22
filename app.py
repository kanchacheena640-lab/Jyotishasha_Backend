from flask import Flask, request, jsonify
from flask_cors import CORS
from factory import create_app
from extensions import db
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
from flask_migrate import Migrate
from extensions import db, jwt
from modules.auth import register_auth
from modules.subscription import register_subscription
from modules.auth.routes_profile import profile_bp
from flask import send_file
from models import Order






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
jwt.init_app(app)
register_auth(app)
register_subscription(app)
app.register_blueprint(profile_bp, url_prefix="/api/profile")

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

    # 🔁 Local import to avoid circular import error
    from tasks import generate_and_send_report
    task = generate_and_send_report.delay(order.id)

    return jsonify({
        "message": "Webhook received and report task started",
        "order_id": order.id,
        "task_id": task.id
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
    try:
        data = request.get_json()
        product_id = data.get("product")

        # ✅ Product validate karo
        if product_id not in PRODUCT_PRICES:
            return jsonify({"error": "Invalid product selected"}), 400

        # ✅ Apni pricing table se hi amount lo
        amount_rupees = PRODUCT_PRICES[product_id]
        amount_paise = amount_rupees * 100

        receipt = f"order_rcptid_{os.urandom(4).hex()}"

        razorpay_order = razorpay_client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "payment_capture": 1,
            "notes": {
                "product": product_id
            }
        })

        return jsonify({
            "order_id": razorpay_order["id"],
            "currency": razorpay_order["currency"],
            "amount": amount_rupees,   # ✅ user ko clean amount dikhao
            "product": product_id
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ------------------- MAIN ------------------- #
if __name__ == "__main__":
    app.run(debug=True)
