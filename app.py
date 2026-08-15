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
from routes.routes_reconciliation import routes_reconciliation
from routes.routes_metrics import routes_metrics
from summary_api import summary_api
from routes.daily_horoscope import daily_bp
from routes.monthly_horoscope import monthly_bp
from routes.routes_panchang import routes_panchang
from flask_migrate import Migrate
from extensions import db, jwt
from modules.auth import register_auth
from modules.subscription import register_subscription
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
from notifications.notification_routes import notification_bp, admin_notification_bp
from modules.love.routes_love import love_bp
from routes.yearly_horoscope import yearly_bp
from routes.relationship_premium import relationship_premium_bp
from routes.transit_content import transit_content_bp
from routes.routes_events import routes_events
from routes.routes_festivals import routes_festivals
from routes.routes_ekadashi import ekadashi_bp
from notifications.user_notification_routes import user_notification_bp
from routes.routes_cards import cards_bp
from routes.routes_event_resource import event_resource_bp
from routes.routes_premium_report import premium_report_bp
from routes.routes_rtdn import routes_rtdn
from routes.routes_google_purchase_confirm import routes_google_purchase_confirm
from routes.routes_google_report_confirm import routes_google_report_confirm
from routes.routes_alerts_dashboard import routes_alerts_dashboard







app = create_app()
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
migrate = Migrate(app, db)
app.register_blueprint(life_tools_bp)
app.register_blueprint(generate_report_bp)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app.register_blueprint(admin_orders_bp)
app.register_blueprint(routes_reconciliation)
app.register_blueprint(routes_metrics)
app.register_blueprint(summary_api)
app.register_blueprint(daily_bp)
app.register_blueprint(monthly_bp)
app.register_blueprint(routes_panchang)
jwt.init_app(app)
register_auth(app)
register_subscription(app)
# S4.0 -- removed a duplicate `app.register_blueprint(profile_bp,
# url_prefix="/api/profile")` that was here. profile_bp is already
# registered above via register_auth(app) -> modules/auth/__init__.py
# (bp.register_blueprint(profile_bp), no prefix), which is what makes
# routes like /api/profile/subscription-info live -- that route's own
# decorator already includes the "/api/profile" prefix literally. The
# second registration removed here only added a redundant, unintended
# second prefix, producing broken duplicate paths (e.g.
# /api/profile/api/profile/subscription-info) that nothing depends on.
# Every real, documented endpoint (S3 audit) is unaffected.
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
app.register_blueprint(notification_bp)
app.register_blueprint(admin_notification_bp)
app.register_blueprint(user_notification_bp)
app.register_blueprint(love_bp)
app.register_blueprint(yearly_bp)
app.register_blueprint(relationship_premium_bp)
app.register_blueprint(transit_content_bp)
app.register_blueprint(routes_events, url_prefix="/api/events")
app.register_blueprint(routes_festivals, url_prefix="/api/festivals")
app.register_blueprint(ekadashi_bp)
app.register_blueprint(cards_bp)
app.register_blueprint(event_resource_bp)
app.register_blueprint(premium_report_bp)
app.register_blueprint(routes_rtdn)
app.register_blueprint(routes_google_purchase_confirm)
app.register_blueprint(routes_google_report_confirm)
app.register_blueprint(routes_alerts_dashboard)

# ------------------- ROOT ------------------- #
@app.route("/")
def home():
        return "Backend is connected with DB + Celery!"

@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({"ok": True})

# ------------------- DEBUG DAILY HOROSCOPE ------------------- #
@app.route("/_debug/run-daily", methods=["GET"])
def debug_run_daily():
    from scripts.daily_rotation_engine import run_daily_rotation
    run_daily_rotation()
    return jsonify({"status": "ok"})

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
    import json

    from modules.payments import (
        PaymentProviderType,
        PaymentPurpose,
        PaymentRequest,
        PaymentService,
        PaymentStatus,
    )
    from modules.payments.razorpay_provider import RazorpayProvider

    # Raw text captured BEFORE parsing -- Razorpay's server webhook
    # signature (verified below, Case A) is an HMAC over the exact raw
    # body bytes it sent; re-serializing the parsed JSON could change
    # key order/whitespace and silently break that check. Flask caches
    # this, so get_json() right after still works normally.
    raw_body = request.get_data(as_text=True)
    data = request.get_json(silent=True) or {}

    # 🔍 DEBUG — ADD HERE
    print("WEBHOOK PAYLOAD =>", data)

    payment_service = PaymentService()

    def _run_payment_service(payment_request):
        """
        The ONE place a PaymentRequest is handed to PaymentService and
        its result translated into this route's response shape --
        shared by both entry points below (the browser callback, Case
        B, and the payment.captured server-webhook recovery path, Case
        A) so there remains exactly one payment-processing pipeline,
        not two independent copies of this logic.
        """
        try:
            result = payment_service.process_payment(payment_request)
        except Exception:
            # Payment Hardening Phase 4: never leak an unhandled exception
            # as Flask's default 500 page. PaymentService has already
            # logged the full, correlated failure (with stack trace)
            # before this exception reached us -- this is only about
            # giving the caller a safe, consistent JSON response.
            print("[Webhook] Unexpected error while processing payment -- see payments logger for detail.")
            return jsonify({"error": "Internal error processing payment"}), 500

        # Payment Hardening Phase 3: DUPLICATE means this exact
        # razorpay_payment_id already succeeded before (browser refresh,
        # double-click, network retry, duplicate webhook, the OTHER
        # entry point having already handled it, ...) -- no new Order
        # was created and no report was re-dispatched. It is a success
        # outcome for the caller, carrying the ORIGINAL order_id, not
        # an error.
        if result.status not in (PaymentStatus.VERIFIED, PaymentStatus.DUPLICATE):
            print(f"[Webhook] Payment verification failed: {result.message}")
            return jsonify({"error": "Payment verification failed"}), 400

        if not result.raw_payload:
            # Extremely narrow race window: a concurrent request for the
            # same payment_id is still finishing its own processing right
            # now. Acknowledge without creating a second Order rather than
            # error out -- the winning request's Order is (or will
            # momentarily be) the single result for this payment_id.
            print(f"[Webhook] {result.message}")
            return jsonify({"message": "Payment already being processed"}), 200

        order_id = result.raw_payload.get("order_id")
        task_id = result.raw_payload.get("task_id")

        if task_id is not None:
            # 🧵 ASYNC MODE (Celery + Redis)
            print(f"[Webhook] Queuing async task for Order {order_id}")
            return jsonify({
                "message": "Webhook received — report task queued",
                "order_id": order_id,
                "task_id": task_id
            }), 200
        else:
            # ⚡ SYNC MODE (Direct execution, no Celery)
            print(f"[Webhook] Running report directly for Order {order_id}")
            return jsonify({
                "message": "Webhook received — report generated successfully",
                "order_id": order_id
            }), 200

    # ✅ Case A: Razorpay's own server-to-server webhook. Distinguished
    # from the browser callback (Case B) below by the "event" key,
    # which the browser's own POST body never contains.
    if isinstance(data, dict) and "event" in data:
        signature = request.headers.get("X-Razorpay-Signature", "")
        if not RazorpayProvider.verify_webhook_signature(raw_body, signature):
            print("[Webhook] Razorpay server webhook signature missing/invalid -- rejecting.")
            return jsonify({"error": "Invalid webhook signature"}), 400

        event = data.get("event")
        if event != "payment.captured":
            # Authenticity is now confirmed (unlike before this phase,
            # which trusted the shape blindly) -- there is just no
            # recovery action defined for any OTHER event type yet.
            print(f"[Webhook] Razorpay event '{event}' received and verified. No action defined for it.")
            return jsonify({"status": "Webhook received (ignored)"}), 200

        # Payment Hardening -- Blocker 01 (Server-to-Server Payment
        # Recovery): this is the complete recovery path for a captured
        # payment whose browser never called back. Signature already
        # confirmed above; everything past this point reuses the exact
        # same PaymentService / OrderService / idempotency / dispatch
        # as Case B, via the shared _run_payment_service() above.
        payment_entity = (
            (data.get("payload") or {}).get("payment", {}).get("entity", {}) or {}
        )
        razorpay_payment_id = payment_entity.get("id")
        razorpay_order_id = payment_entity.get("order_id")
        notes = payment_entity.get("notes") or {}

        if not razorpay_payment_id or not razorpay_order_id:
            print("[Webhook] payment.captured event missing payment/order id -- cannot recover.")
            return jsonify({"error": "Malformed payment.captured event"}), 400

        # notes is populated by /api/razorpay-order at order-creation
        # time (see that route) -- it is the only place this data can
        # come from, since Razorpay itself never learns a customer's
        # dob/tob/pob. email also falls back to the payment entity's
        # own captured email if notes lacks one.
        order_payload = {
            "name": notes.get("name"),
            "email": notes.get("email") or payment_entity.get("email"),
            "product": notes.get("product"),
            "dob": notes.get("dob"),
            "tob": notes.get("tob"),
            "pob": notes.get("pob"),
            "language": notes.get("language", "en"),
        }
        partner_json = notes.get("partner_json")
        if partner_json:
            try:
                order_payload["partner"] = json.loads(partner_json)
            except (TypeError, ValueError):
                pass

        payment_request = PaymentRequest(
            provider=PaymentProviderType.RAZORPAY,
            purpose=PaymentPurpose.REPORT_PURCHASE,
            reference=razorpay_order_id,
            payment_id=razorpay_payment_id,
            signature=None,
            order_payload=order_payload,
            metadata={"source": "webhook"},
        )
        return _run_payment_service(payment_request)

    # ✅ Case B: Frontend-triggered report request (browser callback).
    name = data.get("name")
    email = data.get("email")
    product = data.get("product")

    # 🔍 DEBUG — ADD HERE
    print("name:", name, "email:", email, "product:", product)

    if not all([name, email, product]):
        return jsonify({"error": "Missing required fields"}), 400

    # Payment Architecture Integration Phase 2: the legacy, unverified
    # fallback has been removed. PaymentService is now the ONLY path a
    # report purchase can go through -- every request must carry real
    # Razorpay verification fields; there is no trust-the-payload path
    # left. Order creation + report-generation dispatch inside
    # OrderService are completely unchanged (same table, same
    # status="PAID", same dispatch mechanism) -- only reachable now via
    # a verified payment.
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_signature = data.get("razorpay_signature")

    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        print("[Webhook] Missing Razorpay verification fields -- rejecting.")
        return jsonify({"error": "Missing Razorpay verification fields"}), 400

    payment_request = PaymentRequest(
        provider=PaymentProviderType.RAZORPAY,
        purpose=PaymentPurpose.REPORT_PURCHASE,
        reference=razorpay_order_id,
        payment_id=razorpay_payment_id,
        signature=razorpay_signature,
        order_payload=data,
    )
    return _run_payment_service(payment_request)


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
    import json
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

        # Payment Hardening -- Blocker 01 (Server-to-Server Payment
        # Recovery): forward the report-purchase details already known
        # at this point into Razorpay's own notes, so that IF the
        # browser never calls /webhook back, Razorpay's own
        # payment.captured webhook still carries enough to create the
        # exact same Order. Purely additive -- a caller that only sends
        # "product" (the previous contract) still works exactly as
        # before, it just forgoes webhook-based recovery for that order.
        notes = {"product": product_id}
        for key in ("name", "email", "dob", "tob", "pob", "language"):
            value = data.get(key)
            if value:
                notes[key] = str(value)[:256]
        partner_payload = data.get("partner")
        if partner_payload:
            try:
                notes["partner_json"] = json.dumps(partner_payload)[:512]
            except (TypeError, ValueError):
                pass

        payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "payment_capture": 1,
            "notes": notes,
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
