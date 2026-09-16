from flask import Flask, request, jsonify
from flask_cors import CORS
from factory import create_app
from extensions import db
from routes.routes_user import routes_user
from modules.auth.models import User
from full_kundali_api import calculate_full_kundali
from services.zodiac_service import get_zodiac_traits
from transit_engine import get_current_positions, get_all_planets_next_12, get_current_sign_residency
from life_tools_report import life_tools_bp
import os
from dotenv import load_dotenv
load_dotenv()
from config.razorpay_config import razorpay_client
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
from routes.routes_app_version import routes_app_version
from routes.routes_app_version import admin_or_bridge_required
from routes.routes_admin_users import routes_admin_users
from routes.routes_admin_audiences import routes_admin_audiences
from routes.routes_admin_notifications import routes_admin_notifications
from routes.routes_activity_events import routes_activity_events
from routes.routes_activity_events_anonymous import routes_activity_events_anonymous
from routes.routes_analytics import routes_analytics
from routes.routes_website_analytics import routes_website_analytics







app = create_app()
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
migrate = Migrate(app, db)
app.register_blueprint(life_tools_bp)
# Legacy /api/generate-report bypasses payment verification; keep it unregistered.
# Paid website reports enter through /api/razorpay-order and /webhook.
# (Removed: an eagerly-constructed, module-level `openai_client = OpenAI(...)`
# used to live here. Confirmed dead code -- grep found zero readers of
# it anywhere in the codebase, not even elsewhere in this file -- and
# its eager construction was the last of several landmines that forced
# every script merely importing `app` (e.g.
# scripts/campaign_worker_runner.py, which never touches OpenAI) to
# also have a real-shaped OPENAI_API_KEY just to boot. See
# report_writer.py / summary_api.py / routes/routes_free_consult.py /
# modules/services/chat_engine.py / modules/smartchat/smartchat_engine.py
# / services/ai_prediction_lab/openai_client.py for the ACTUALLY-used
# clients, which were converted to lazy singletons instead of removed.)
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
app.register_blueprint(routes_app_version)
app.register_blueprint(routes_admin_users)
app.register_blueprint(routes_admin_audiences)
app.register_blueprint(routes_admin_notifications)
app.register_blueprint(routes_activity_events)
app.register_blueprint(routes_activity_events_anonymous)
app.register_blueprint(routes_analytics)
app.register_blueprint(routes_website_analytics)

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
# Paid Report Platform v1.0 -- R6 (Backend Route Integration). This
# route's ENTIRE payment-processing body is now the NEW
# PaymentFinalizationService + ReportGenerationDispatcher orchestration
# (R4/R5) instead of PaymentService.process_payment(). Confirmed safe
# to do unconditionally (Section A/I -- no purpose-based branching
# needed here): every PaymentRequest this route has ever constructed,
# in both Case A and Case B, hard-codes purpose=PaymentPurpose.
# REPORT_PURCHASE -- this route has never handled SUBSCRIPTION/Google
# Play/chat-pack payments. Google Play subscriptions have their own,
# completely separate route (routes/routes_google_purchase_confirm.py,
# routes/routes_rtdn.py) that calls PaymentService.process_payment()
# directly and is untouched by this change. Ask Now's ChatPack flow
# (modules/services/chat_pack_service.py) calls RazorpayProvider.
# verify() directly and NEVER goes through PaymentService or this
# route at all (confirmed by re-reading that file fresh for this
# phase) -- also entirely unaffected.
@app.route("/webhook", methods=["POST"])
def webhook():
    from models import Order
    from modules.payments.payment_models import PaymentProviderType, PaymentPurpose, PaymentRequest
    from modules.payments.razorpay_provider import RazorpayProvider
    from modules.payments.campaign_attribution import extract_campaign_context_from_notes
    from modules.payments.payment_finalization_service import (
        PaymentFinalizationService, ReportPaymentFinalizationStatus,
    )
    from modules.payments.report_generation_dispatcher import (
        ReportGenerationDispatcher, ReportGenerationDispatchStatus,
    )

    # Raw text captured BEFORE parsing -- Razorpay's server webhook
    # signature (verified below, Case A) is an HMAC over the exact raw
    # body bytes it sent; re-serializing the parsed JSON could change
    # key order/whitespace and silently break that check. Flask caches
    # this, so get_json() right after still works normally.
    raw_body = request.get_data(as_text=True)
    data = request.get_json(silent=True) or {}

    finalization_service = PaymentFinalizationService()
    dispatcher = ReportGenerationDispatcher()

    # ---------------------------------------------------------
    # Section G -- the ONE place a finalization result (plus an optional
    # dispatch attempt) becomes this route's HTTP response. Replaces the
    # OLD _run_payment_service()'s dangerous "no raw_payload -> 200"
    # fallback (the exact class of response that let Suresh's browser be
    # silently redirected to a thank-you page despite no Order/report).
    # ---------------------------------------------------------
    def _respond(result, dispatch_result=None):
        status = result.status

        if status == ReportPaymentFinalizationStatus.FINALIZED:
            if dispatch_result is not None and dispatch_result.status == ReportGenerationDispatchStatus.DISPATCH_FAILED:
                # Section G -- payment remains PAID; never imply payment
                # failed or invite a second payment. Report processing
                # is delayed pending the existing, separate manual/
                # automatic recovery mechanisms (report_stage="Failed",
                # unchanged from R5).
                return jsonify({
                    "status": "payment_confirmed_processing_delayed",
                    "message": "Your payment was received. Report generation could not start immediately and will be retried.",
                    "order_id": result.order_id,
                }), 200
            return jsonify({
                "status": "success", "message": "Payment confirmed; report generation started.",
                "order_id": result.order_id,
            }), 200

        if status == ReportPaymentFinalizationStatus.ALREADY_FINALIZED:
            if dispatch_result is not None:
                if dispatch_result.status == ReportGenerationDispatchStatus.DISPATCHED:
                    return jsonify({
                        "status": "recovered_success",
                        "message": "Payment already confirmed; report generation has now been started.",
                        "order_id": result.order_id,
                    }), 200
                if dispatch_result.status == ReportGenerationDispatchStatus.DISPATCH_FAILED:
                    return jsonify({
                        "status": "payment_confirmed_processing_delayed",
                        "message": "Your payment was received. Report generation could not start immediately and will be retried.",
                        "order_id": result.order_id,
                    }), 200
                # Any other dispatch outcome here (ALREADY_QUEUED/
                # PROCESSING/READY/FAILED_REQUIRES_MANUAL_RETRY/etc.)
                # means the report is already in a known, tracked state
                # -- still an idempotent success from the payment's
                # point of view.
            return jsonify({
                "status": "already_processing",
                "message": "This payment was already confirmed.",
                "order_id": result.order_id,
            }), 200

        # Every remaining status is a genuine, non-2xx rejection --
        # never a fake success, and never implying the CUSTOMER should
        # pay again (Section H/D of R4 already prevents any of these
        # from mutating Order/ProcessedPayment state).
        manual_review_statuses = (
            ReportPaymentFinalizationStatus.LEGACY_STUCK,
            ReportPaymentFinalizationStatus.DIFFERENT_PAYMENT_FOR_PAID_ORDER,
            ReportPaymentFinalizationStatus.PAYMENT_ALREADY_CLAIMED_DIFFERENT_ORDER,
        )
        if status in manual_review_statuses:
            return jsonify({
                "error": "manual_review_required", "status": status, "message": result.message,
            }), 409
        if status == ReportPaymentFinalizationStatus.PAYMENT_LOOKUP_FAILED:
            return jsonify({"error": "payment_lookup_failed", "message": result.message}), 502
        return jsonify({"error": status.lower(), "message": result.message}), 400

    def _orchestrate(payment_request):
        """Section F -- the ONE place a finalization result decides
        whether ReportGenerationDispatcher is ever called. Never called
        for anything other than FINALIZED (first success) or
        ALREADY_FINALIZED-with-Order.report_stage=='Pending' (the
        crash-recovery repair window: payment finalized, process died
        before dispatch could run) -- every other duplicate/conflict/
        rejection path dispatches nothing."""
        result = finalization_service.finalize_report_payment(payment_request)

        if result.status == ReportPaymentFinalizationStatus.FINALIZED:
            dispatch_result = dispatcher.dispatch_if_pending(result.order_id)
            return _respond(result, dispatch_result)

        if result.status == ReportPaymentFinalizationStatus.ALREADY_FINALIZED and result.order_id is not None:
            order = Order.query.get(result.order_id)
            if order is not None and order.report_stage == "Pending":
                dispatch_result = dispatcher.dispatch_if_pending(result.order_id)
                return _respond(result, dispatch_result)

        return _respond(result)

    # ✅ Case A: Razorpay's own server-to-server webhook. Distinguished
    # from the browser callback (Case B) below by the "event" key,
    # which the browser's own POST body never contains. Signature
    # verification is completely UNCHANGED from before this phase.
    if isinstance(data, dict) and "event" in data:
        signature = request.headers.get("X-Razorpay-Signature", "")
        if not RazorpayProvider.verify_webhook_signature(raw_body, signature):
            print("[Webhook] Razorpay server webhook signature missing/invalid -- rejecting.")
            return jsonify({"error": "Invalid webhook signature"}), 400

        event = data.get("event")
        if event != "payment.captured":
            print(f"[Webhook] Razorpay event '{event}' received and verified. No action defined for it.")
            return jsonify({"status": "Webhook received (ignored)"}), 200

        payment_entity = (
            (data.get("payload") or {}).get("payment", {}).get("entity", {}) or {}
        )
        razorpay_payment_id = payment_entity.get("id")
        razorpay_order_id = payment_entity.get("order_id")
        if not razorpay_payment_id or not razorpay_order_id:
            print("[Webhook] payment.captured event missing payment/order id -- cannot recover.")
            return jsonify({"error": "Malformed payment.captured event"}), 400

        # Section E -- notes is read ONLY for the non-PII campaign
        # attribution snapshot (Task 10A, unchanged) -- NEVER as a
        # source of name/email/dob/tob/pob/partner. The Order, resolved
        # entirely by razorpay_order_id inside PaymentFinalizationService,
        # is the sole source of report data from this point on.
        notes = payment_entity.get("notes") or {}
        campaign_context = extract_campaign_context_from_notes(notes)

        payment_request = PaymentRequest(
            provider=PaymentProviderType.RAZORPAY,
            purpose=PaymentPurpose.REPORT_PURCHASE,
            reference=razorpay_order_id,
            payment_id=razorpay_payment_id,
            signature=None,
            metadata={"source": "webhook"},
            campaign_context=campaign_context,
        )
        return _orchestrate(payment_request)

    # ✅ Case B: Frontend-triggered report request (browser callback).
    # Section E/H -- no name/email/product/dob/tob/pob/partner field is
    # read from `data` at all anymore; only the three Razorpay
    # verification fields matter. The OLD `if not all([name, email,
    # product])` pre-check is gone -- there is no order_payload left to
    # validate here, and an old-frontend caller that still sends those
    # fields has them silently ignored, never trusted.
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_signature = data.get("razorpay_signature")

    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        print("[Webhook] Missing Razorpay verification fields -- rejecting.")
        return jsonify({"error": "Missing Razorpay verification fields"}), 400

    # Task 10A -- unchanged: the durable transaction snapshot, fetched
    # fresh from Razorpay's own order.notes, never from the browser's
    # own resent payload.
    campaign_context = RazorpayProvider.fetch_order_campaign_context(razorpay_order_id)

    payment_request = PaymentRequest(
        provider=PaymentProviderType.RAZORPAY,
        purpose=PaymentPurpose.REPORT_PURCHASE,
        reference=razorpay_order_id,
        payment_id=razorpay_payment_id,
        signature=razorpay_signature,
        campaign_context=campaign_context,
    )
    return _orchestrate(payment_request)


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
      },
      "current_residency": {
        "Sun":   {planet, from_rashi, to_rashi, entering_date, exit_date, motion},
        "Moon":  { ... },
        ...
        "Ketu":  { ... }
      }
    }

    U4C.2 -- `current_residency` is new; `positions`/`future_transits`
    are UNCHANGED, byte-for-byte, for backward compatibility (Flutter
    and every existing website consumer read only those two and must
    keep working unmodified -- see U4C.2 report Sec.9). It is computed
    via transit_engine.get_current_sign_residency() (U4C.1A) -- the
    SAME canonical boundary primitive future_transits already uses,
    never a new date-boundary algorithm -- and answers a DIFFERENT
    question than future_transits[planet][0] does: "what residency
    contains RIGHT NOW" (current_residency), vs. "what is the NEXT
    transition from here" (future_transits[0]). U4C.0 found the
    website was using future_transits[0] for a "Current Period" label,
    which is wrong whenever a sign is later re-entered (e.g. a
    retrograde re-entry) -- current_residency exists precisely so the
    frontend never has to recreate that ingress-boundary logic itself
    to answer "what's the current period" correctly.
    """
    current = get_current_positions()
    future = get_all_planets_next_12()
    residency = {
        p: get_current_sign_residency(p)
        for p in ("Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Rahu", "Ketu")
    }
    return jsonify({**current, "future_transits": future, "current_residency": residency})

# ------------------- ADD MORE HEre ------------------- #

# ------------------- ADMIN REPORT DOWNLOAD ------------------- #

@app.route("/admin/download/<int:order_id>")
@admin_or_bridge_required
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
# Paid Report Platform v1.0 -- R6 (Backend Route Integration). This
# route's own contract changed: it now requires the COMPLETE report/
# customer payload (name/email/phone/dob/tob/pob/latitude/longitude,
# plus `partner` for relationship_future_report) and REJECTS the OLD
# {product}-only payload before ever contacting Razorpay -- see R6's
# own report for why this is a deliberate, LOCKED decision (never a
# backward-compatible fallback) and why this backend change is NOT
# independently deployable against the OLD frontend.
@app.route("/api/razorpay-order", methods=["POST"])
def create_razorpay_order():
    import time
    from modules.payments.campaign_attribution import (
        sanitize_campaign_attribution_snapshot,
        build_razorpay_notes_fields,
    )
    from modules.payments.order_service import OrderService, OrderValidationError
    from modules.payments.report_product_registry import ReportProduct
    from modules.payments.payment_logger import log_payment_event, new_correlation_id

    correlation_id = new_correlation_id()
    data = request.get_json(silent=True) or {}

    # Section B.1-3 / Section D -- create_pending_order() (R3) is the
    # ONE place that resolves report_slug against the ReportProduct
    # registry and validates every required customer/birth field --
    # entirely BEFORE Razorpay is ever contacted. An incomplete
    # payload, an unknown product, or an inactive product is rejected
    # right here, with zero Razorpay API calls and zero charge risk.
    try:
        order = OrderService().create_pending_order(data)
    except OrderValidationError as exc:
        log_payment_event(
            "report_order_validation_failed", status="FAILED", correlation_id=correlation_id,
            provider="RAZORPAY", product=(data.get("report_slug") or data.get("product")), error=str(exc),
        )
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400

    try:
        # Section B.5 -- safe reconciliation metadata ONLY. Deliberately
        # never name/email/dob/tob/pob/latitude/longitude/partner --
        # the Order itself (resolved later by razorpay_order_id, R4's
        # PaymentFinalizationService) is now the sole source of that
        # data. Task 10A's own campaign-attribution snapshot is
        # unrelated, non-PII (utm_source/utm_medium/utm_campaign/
        # referrer only) reconciliation metadata, unchanged.
        campaign_context = sanitize_campaign_attribution_snapshot(data.get("campaign_context"))
        notes = {"internal_order_id": str(order.id), "report_slug": order.product}
        notes.update(build_razorpay_notes_fields(campaign_context))

        product = ReportProduct.query.get(order.product)
        razorpay_payload = {
            # Section B.4 -- the registry-derived, immutable snapshot
            # create_pending_order() already stored on this Order --
            # never recomputed from client input at any point.
            "amount": order.amount_paise,
            "currency": (product.currency if product else "INR"),
            "receipt": f"order_{order.id}",
            "payment_capture": 1,
            "notes": notes,
        }

        # Existing retry safeguard, unchanged.
        try:
            rp_order = razorpay_client.order.create(razorpay_payload)
        except Exception as e1:
            print("⚠️ Razorpay order first attempt failed:", str(e1))
            time.sleep(0.8)
            try:
                rp_order = razorpay_client.order.create(razorpay_payload)
            except Exception as e2:
                # Section C -- the internal Order (already committed
                # above) is NEVER deleted here. It stays exactly as
                # create_pending_order() left it: payment_status=
                # "CREATED", razorpay_order_id=NULL -- safely
                # identifiable later, never charged.
                log_payment_event(
                    "report_order_razorpay_creation_failed", status="FAILED", correlation_id=correlation_id,
                    provider="RAZORPAY", product=order.product, order_id=order.id, error=str(e2),
                )
                return jsonify({
                    "error": "razorpay_order_creation_failed",
                    "message": "Could not create a payment order. Please try again.",
                }), 502

        # Section B.6 -- persisted only AFTER Razorpay itself confirms
        # the order.
        order.razorpay_order_id = rp_order.get("id")
        order.payment_status = "PAYMENT_PENDING"
        db.session.commit()

        return jsonify({
            "order_id": rp_order.get("id"),
            "internal_order_id": order.id,
            "currency": rp_order.get("currency", "INR"),
            # Paise -- matches Razorpay's own native unit and
            # Order.amount_paise exactly. See R6's own report for why
            # this deliberately does not reproduce the old, historically
            # inconsistent rupees-vs-paise contract between the two
            # pre-existing frontend flows.
            "amount": order.amount_paise,
            "product": order.product,
        }), 200

    except Exception as exc:
        log_payment_event(
            "report_order_unexpected_error", status="FAILED", correlation_id=correlation_id,
            provider="RAZORPAY", product=order.product, order_id=order.id, error=str(exc), exc_info=True,
        )
        return jsonify({
            "error": "internal_error",
            "message": "An unexpected error occurred while creating the payment order.",
        }), 500




# ------------------- MAIN ------------------- #
if __name__ == "__main__":
    app.run(debug=True)
