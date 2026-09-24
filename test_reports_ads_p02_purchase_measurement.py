"""
test_reports_ads_p02_purchase_measurement.py
-------------------------------------------------
Reports Ads P0.2 -- the canonical purchase measurement object
(modules/payments/purchase_measurement.py), attached by POST /webhook to
the responses that already prove a payment is verified and the Order PAID.

Drives the REAL Flask routes (POST /api/razorpay-order, POST /webhook)
with only Razorpay's network boundary mocked (verify / fetch_payment /
fetch_order_campaign_context / the lazy client) and threading.Thread
mocked so no real report generation ever starts -- the same approach as
test_report_platform_r6_route_integration.py.

LOCAL ONLY (jyotishasha_local). No credential is stored in this file:
set LOCAL_TEST_DATABASE_URL (or rely on libpq's PGPASSWORD / pgpass with
the password-free default below). The run is refused unless the
connected database is jyotishasha_local. The two non-pilot focused test
products are flipped active only inside try/finally and always restored;
pilot products are never touched.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = os.environ.get(
    "LOCAL_TEST_DATABASE_URL",
    "postgresql://jyotishasha_dev@localhost:5432/jyotishasha_local",
)
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")
os.environ.setdefault("FCM_SERVICE_ACCOUNT_JSON", '{"project_id":"local-test-unused"}')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extensions  # noqa: E402
extensions.init_firebase = lambda: None  # never initialise Firebase from a test

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from models import Order, OrderAttribution  # noqa: E402
from modules.models_processed_payments import ProcessedPayment  # noqa: E402
from modules.payments.report_product_registry import ReportProduct  # noqa: E402
from modules.payments.razorpay_provider import RazorpayProvider  # noqa: E402
from modules.payments.report_generation_dispatcher import ReportGenerationDispatcher, ReportGenerationDispatchStatus  # noqa: E402
from modules.payments import purchase_measurement as pm  # noqa: E402
from modules.payments.payment_models import PaymentVerificationResult, PaymentStatus, PaymentProviderType  # noqa: E402
from config.razorpay_config import _LazyRazorpayClient  # noqa: E402

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


MARKER = "ads-p02-test"
_n = {"n": 0}


def _unique(prefix):
    _n["n"] += 1
    return f"{prefix}-{_n['n']}"


SELF_SLUG = "promotion_timing"                  # focused_v1, category career
DUAL_SLUG = "relationship_lead_to_marriage"      # focused_dual_v1, category relationship
STANDARD_SLUG = "startup_suggestion_report"      # original catalog -- out of scope
PII_MARKERS = ("Purchase Test User", "9876543210", "1994-01-26", "Sindhnur Rural", "Purchase Partner", "1992-08-15", MARKER)

ALLOWED = set(pm.ALLOWED_FIELDS)


def self_payload(**over):
    p = {"product": SELF_SLUG, "name": "Purchase Test User", "email": f"{MARKER}-{_unique('u')}@example.com", "phone": "9876543210",
         "dob": "1994-01-26", "tob": "08:40", "pob": "Sindhnur Rural", "latitude": "15.6167", "longitude": "76.6833", "language": "en"}
    p.update(over)
    return p


def dual_payload(**over):
    p = self_payload(product=DUAL_SLUG)
    p["partner"] = {"name": "Purchase Partner", "dob": "1992-08-15", "tob": "06:30", "pob": "Mumbai", "latitude": "19.076", "longitude": "72.8777"}
    p.update(over)
    return p


def mock_razorpay():
    m = MagicMock()
    m.order.create.side_effect = lambda payload: {"id": _unique("order_rp_p02"), "currency": "INR"}
    _LazyRazorpayClient._real_client = m
    return m


def create_order(client, payload):
    mock_razorpay()
    r = client.post("/api/razorpay-order", json=payload)
    assert r.status_code == 200, r.get_data(as_text=True)
    return db.session.get(Order, r.get_json()["internal_order_id"])


def verified(ref):
    return PaymentVerificationResult(status=PaymentStatus.VERIFIED, provider=PaymentProviderType.RAZORPAY, reference=ref, verified=True, message="ok")


def failed_verification(ref):
    return PaymentVerificationResult(status=PaymentStatus.FAILED, provider=PaymentProviderType.RAZORPAY, reference=ref, verified=False, message="bad signature")


def pay(client, order, payment_id=None, verify_result=None, amount_paise=None, dispatch_result=None):
    """Browser success callback through the REAL /webhook route."""
    payment_id = payment_id or _unique("pay_rp_p02")
    record = {"id": payment_id, "order_id": order.razorpay_order_id, "amount": order.amount_paise if amount_paise is None else amount_paise, "status": "captured"}
    body = {"razorpay_order_id": order.razorpay_order_id, "razorpay_payment_id": payment_id, "razorpay_signature": "sig_test"}
    patches = [
        patch.object(RazorpayProvider, "verify", return_value=verify_result or verified(order.razorpay_order_id)),
        patch.object(RazorpayProvider, "fetch_payment", staticmethod(lambda pid: record)),
        patch.object(RazorpayProvider, "fetch_order_campaign_context", staticmethod(lambda oid: None)),
        patch("threading.Thread"),
    ]
    if dispatch_result is not None:
        patches.append(patch.object(ReportGenerationDispatcher, "dispatch_if_pending", return_value=dispatch_result))
    for p_ in patches:
        p_.start()
    try:
        resp = client.post("/webhook", json=body)
    finally:
        for p_ in reversed(patches):
            p_.stop()
    db.session.expire_all()
    return resp, payment_id


def cleanup():
    Order.query.filter(Order.email.like(f"{MARKER}%")).delete(synchronize_session=False)
    db.session.commit()
    db.session.execute(text("DELETE FROM processed_payments WHERE reference LIKE 'order_rp_p02%'"))
    db.session.commit()


def set_active(slug, value):
    ReportProduct.query.filter_by(report_slug=slug).update({"active": value}, synchronize_session=False)
    db.session.commit()


def main():
    with app.app_context():
        assert db.session.execute(text("SELECT current_database()")).scalar() == "jyotishasha_local", "Refusing to run: not jyotishasha_local"
        cleanup()
        set_active(SELF_SLUG, True)
        set_active(DUAL_SLUG, True)
        original_prices = {s: ReportProduct.query.get(s).price for s in (SELF_SLUG, DUAL_SLUG)}
        try:
            client = app.test_client()

            # ==========================================================
            print("\n=== 1-2. unpaid / failed payment can NEVER produce a purchase ===")
            # ==========================================================
            unpaid = create_order(client, self_payload())
            check("1a: an Order that is PAYMENT_PENDING (order created, nothing paid) -> None",
                  unpaid.payment_status == "PAYMENT_PENDING" and pm.build_purchase_measurement(unpaid.id) is None)
            mock_razorpay()
            failing = MagicMock()
            failing.order.create.side_effect = Exception("razorpay down")
            _LazyRazorpayClient._real_client = failing
            with patch("time.sleep"):
                client.post("/api/razorpay-order", json=self_payload())
            created_only = Order.query.filter(Order.email.like(f"{MARKER}%"), Order.payment_status == "CREATED").order_by(Order.id.desc()).first()
            check("1b: an Order that stayed CREATED (Razorpay order never made) -> None", created_only is not None and pm.build_purchase_measurement(created_only.id) is None)
            check("1c: unknown / None / garbage order id -> None, never raises",
                  pm.build_purchase_measurement(99999999) is None and pm.build_purchase_measurement(None) is None and pm.build_purchase_measurement("abc") is None)

            bad, _ = pay(client, unpaid, verify_result=failed_verification(unpaid.razorpay_order_id))
            check("2a: failed verification (bad signature) -> non-2xx and NO purchase_measurement in the response",
                  bad.status_code >= 400 and "purchase_measurement" not in (bad.get_json() or {}))
            check("2b: ...the Order stays unpaid and still cannot be measured", unpaid.payment_status == "PAYMENT_PENDING" and pm.build_purchase_measurement(unpaid.id) is None)
            wrong_amount, _ = pay(client, unpaid, amount_paise=100)
            check("2c: a captured payment with the WRONG amount is rejected -> no measurement",
                  wrong_amount.status_code >= 400 and "purchase_measurement" not in (wrong_amount.get_json() or {}) and pm.build_purchase_measurement(unpaid.id) is None)

            # ==========================================================
            print("\n=== 3-9. verified PAID focused purchases ===")
            # ==========================================================
            # Client-supplied classification/price fields must be ignored entirely.
            tamper = {"amount": 1, "price": 1, "value": 1, "currency": "USD", "product_family": "original", "item_category": "evil",
                      "item_name": "EVIL", "report_type": "x", "transaction_id": "ord_1", "payment_provider": "STRIPE", "source_platform": "app"}
            self_order = create_order(client, self_payload(**tamper))
            r, self_pay_id = pay(client, self_order)
            body = r.get_json()
            m = body.get("purchase_measurement")
            db.session.refresh(self_order)
            check("3a: verified SELF purchase -> 200 status 'success' with a purchase_measurement", r.status_code == 200 and body["status"] == "success" and isinstance(m, dict))
            check("3b: the Order is PAID", self_order.payment_status == "PAID")
            check("3c: exact SELF payload from trusted data",
                  m == {"transaction_id": f"ord_{self_order.id}", "value": 51, "currency": "INR", "item_id": SELF_SLUG, "item_name": ReportProduct.query.get(SELF_SLUG).name,
                        "item_category": "career", "product_family": "focused_report", "report_type": "self", "payment_provider": "RAZORPAY", "source_platform": "web"})
            check("5: transaction_id maps to the correct internal Order (and its Razorpay order)",
                  m["transaction_id"] == f"ord_{self_order.id}" and db.session.get(Order, int(m["transaction_id"][4:])).razorpay_order_id == self_order.razorpay_order_id)
            check("6a: value comes from Order.amount_paise (5100 -> 51), not from the tampered client 'amount'/'price'/'value'", self_order.amount_paise == 5100 and m["value"] == 51)
            check("7a: currency is INR even though the client claimed USD", m["currency"] == "INR")
            check("8: item / classification come from the Order + registry + catalog, not the client tamper fields",
                  m["item_id"] == SELF_SLUG and m["item_name"] != "EVIL" and m["item_category"] == "career" and m["product_family"] == "focused_report"
                  and m["report_type"] == "self" and m["payment_provider"] == "RAZORPAY" and m["source_platform"] == "web")
            check("9a: category for a SELF question derives from the catalog (promotion_timing -> career)", m["item_category"] == "career")

            dual_order = create_order(client, dual_payload())
            rd, _ = pay(client, dual_order)
            dbody = rd.get_json()
            dm = dbody.get("purchase_measurement")
            db.session.refresh(dual_order)
            check("4a: verified DUAL purchase -> 200 with a purchase_measurement", rd.status_code == 200 and dbody["status"] == "success" and isinstance(dm, dict))
            check("4b: exact DUAL payload (dual report_type, relationship category)",
                  dm == {"transaction_id": f"ord_{dual_order.id}", "value": 51, "currency": "INR", "item_id": DUAL_SLUG, "item_name": ReportProduct.query.get(DUAL_SLUG).name,
                        "item_category": "relationship", "product_family": "focused_report", "report_type": "dual", "payment_provider": "RAZORPAY", "source_platform": "web"})
            check("5b: DUAL transaction_id maps to the DUAL Order", db.session.get(Order, int(dm["transaction_id"][4:])).product == DUAL_SLUG and dual_order.payment_status == "PAID")
            check("9b: category for a DUAL question derives from the catalog (relationship_lead_to_marriage -> relationship)", dm["item_category"] == "relationship")

            # value is derived from the Order snapshot: registry price changes after order creation don't matter
            price_order = create_order(client, self_payload())
            ReportProduct.query.filter_by(report_slug=SELF_SLUG).update({"price": 999}, synchronize_session=False)
            db.session.commit()
            rp, _ = pay(client, price_order)
            check("6b: a later registry price change does not alter the measured value (immutable Order.amount_paise snapshot)",
                  rp.status_code == 200 and rp.get_json()["purchase_measurement"]["value"] == 51)
            ReportProduct.query.filter_by(report_slug=SELF_SLUG).update({"price": original_prices[SELF_SLUG]}, synchronize_session=False)
            db.session.commit()

            # conversion of a fractional-rupee amount, and currency validation (direct, on an already PAID Order)
            Order.query.filter_by(id=self_order.id).update({"amount_paise": 12345}, synchronize_session=False)
            db.session.commit()
            check("6c: paise -> major units is exact (12345 paise -> 123.45)", pm.build_purchase_measurement(self_order.id)["value"] == 123.45)
            Order.query.filter_by(id=self_order.id).update({"amount_paise": 5100}, synchronize_session=False)
            db.session.commit()
            ReportProduct.query.filter_by(report_slug=SELF_SLUG).update({"currency": "USD"}, synchronize_session=False)
            db.session.commit()
            check("7b: an unsupported registry currency is refused (None), never guessed", pm.build_purchase_measurement(self_order.id) is None)
            ReportProduct.query.filter_by(report_slug=SELF_SLUG).update({"currency": "INR"}, synchronize_session=False)
            db.session.commit()
            check("7c: restored -> measurable again", pm.build_purchase_measurement(self_order.id)["currency"] == "INR")

            # ==========================================================
            print("\n=== 10. no PII / no identifiers in the payload ===")
            # ==========================================================
            blob = json.dumps([m, dm])
            check("10a: only allowlisted keys are ever present", set(m.keys()) <= ALLOWED and set(dm.keys()) <= ALLOWED)
            check("10b: no name / email / phone / DOB / place / partner data anywhere in either payload", not any(x in blob for x in PII_MARKERS))
            check("10c: no payment id, signature, click id or utm value in the payload",
                  self_pay_id not in blob and "sig_test" not in blob and not any(k in m for k in ("gclid", "gbraid", "wbraid", "fbclid", "utm_source", "razorpay_payment_id")))
            full_body = json.dumps(body)
            check("10d: the whole webhook response carries no PII either", not any(x in full_body for x in PII_MARKERS))

            # ==========================================================
            print("\n=== 12/13. duplicate callbacks and other statuses ===")
            # ==========================================================
            dup, _ = pay(client, self_order, payment_id=self_pay_id)
            dbody2 = dup.get_json()
            check("12a: a duplicate browser callback -> 200 'already_processing' (payment dedupe unchanged)", dup.status_code == 200 and dbody2["status"] == "already_processing")
            check("12b: ...and it carries the IDENTICAL transaction_id (so the browser can dedupe on it)",
                  dbody2["purchase_measurement"]["transaction_id"] == m["transaction_id"] and dbody2["purchase_measurement"]["value"] == 51)
            check("12c: still exactly one payment claim and one PAID Order", ProcessedPayment.query.filter_by(payment_id=self_pay_id).count() == 1 and self_order.payment_status == "PAID")

            delayed_order = create_order(client, self_payload())
            failed_dispatch = MagicMock(status=ReportGenerationDispatchStatus.DISPATCH_FAILED)
            rdl, _ = pay(client, delayed_order, dispatch_result=failed_dispatch)
            check("12d: PAID but report generation delayed -> 200 'payment_confirmed_processing_delayed' STILL carries the purchase (the money is real)",
                  rdl.status_code == 200 and rdl.get_json()["status"] == "payment_confirmed_processing_delayed"
                  and rdl.get_json()["purchase_measurement"]["transaction_id"] == f"ord_{delayed_order.id}")

            # ==========================================================
            print("\n=== 16-17. organic purchase, P0.1 attribution, scope, isolation ===")
            # ==========================================================
            organic = create_order(client, self_payload())
            ro, _ = pay(client, organic)
            check("16a: an organic purchase (no attribution sent) still completes and is measured",
                  ro.status_code == 200 and ro.get_json()["purchase_measurement"]["transaction_id"] == f"ord_{organic.id}")
            check("16b: ...and no attribution row exists for it (unchanged P0.1 behaviour)", OrderAttribution.query.filter_by(order_id=organic.id).count() == 0)

            attributed = create_order(client, self_payload(attribution={"attribution_type": "latest_click", "utm_source": "google", "utm_medium": "cpc",
                                                                        "gclid": "P02_GCLID", "landing_page": "/reports/focused/promotion-timing"}))
            before = OrderAttribution.query.filter_by(order_id=attributed.id).one()
            snapshot = (before.gclid, before.utm_source, before.attribution_type, before.landing_page)
            ra, _ = pay(client, attributed)
            after = OrderAttribution.query.filter_by(order_id=attributed.id).one()
            am = ra.get_json()["purchase_measurement"]
            check("17a: P0.1 attribution row is unaffected by payment + measurement", snapshot == (after.gclid, after.utm_source, after.attribution_type, after.landing_page) == ("P02_GCLID", "google", "latest_click", "/reports/focused/promotion-timing"))
            check("17b: the purchase joins to that attribution row by transaction_id (ord_<order_id> == order_attributions.order_id)", int(am["transaction_id"][4:]) == after.order_id)
            check("17c: click ids / UTM stay OUT of the purchase payload", "P02_GCLID" not in json.dumps(am) and "google" not in json.dumps(am))

            standard = create_order(client, {
                "product": STANDARD_SLUG, "name": "Purchase Test User", "email": f"{MARKER}-{_unique('s')}@example.com", "phone": "9876543210",
                "dob": "1994-01-26", "tob": "08:40", "pob": "Sindhnur Rural", "latitude": "15.6167", "longitude": "76.6833", "language": "en"})
            rs, _ = pay(client, standard)
            check("18a: an ORIGINAL (non-focused) paid report is out of scope -> success response unchanged, NO purchase_measurement",
                  rs.status_code == 200 and rs.get_json()["status"] == "success" and "purchase_measurement" not in rs.get_json())
            check("18b: ...and it is PAID exactly as before", standard.payment_status == "PAID" and pm.build_purchase_measurement(standard.id) is None)

            broken_order = create_order(client, self_payload())
            with patch.object(pm.db.session, "get", side_effect=RuntimeError("boom")):
                measured_none = pm.build_purchase_measurement(broken_order.id)
            rb, _ = pay(client, broken_order)
            check("19a: a measurement error inside the builder is swallowed (None) and logged", measured_none is None)
            check("19b: payment success response shape is otherwise unchanged (status/message/order_id present)",
                  rb.status_code == 200 and {"status", "message", "order_id", "purchase_measurement"} <= set(rb.get_json().keys()))
        finally:
            db.session.rollback()
            set_active(SELF_SLUG, False)
            set_active(DUAL_SLUG, False)
            for slug, price in original_prices.items():
                ReportProduct.query.filter_by(report_slug=slug).update({"price": price, "currency": "INR"}, synchronize_session=False)
            db.session.commit()
            _LazyRazorpayClient._real_client = None

        cleanup()
        active_focused = ReportProduct.query.filter(ReportProduct.generator.in_(("focused_v1", "focused_dual_v1")), ReportProduct.active.is_(True)).count()
        check("Z: all focused products inactive again; test orders removed", active_focused == 0 and Order.query.filter(Order.email.like(f"{MARKER}%")).count() == 0)

    print("\n==================================================")
    print(f"RESULT: {passed} passed, {failed} failed")
    print("==================================================")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
