"""
test_reports_ads_p02a_original_reports_measurement.py
-------------------------------------------------
Reports Ads P0.2A -- the canonical purchase measurement
(modules/payments/purchase_measurement.py) now covers ALL 88 paid web reports:

    54 focused SELF   (focused_v1)          product_family focused_report / self
     9 focused DUAL   (focused_dual_v1)     product_family focused_report / dual
    24 original       (standard_v1)         product_family original_report / standard   (INR 51)
     1 relationship   (love_premium_v1)     product_family original_report / relationship (INR 199)

Sections:
  A. the explicit original-report category table: keys == exactly the 25
     original registry products (and the legacy price table); no fallback.
  B. registry-wide coverage: every one of the 88 registry products yields a
     correct canonical object for a PAID Order and NOTHING for an unpaid one.
  C. real /api/razorpay-order + /webhook flows (Razorpay's network boundary
     mocked) for an original standard report and the relationship report:
     canonical values, unpaid / failed payments never measured, duplicate
     callbacks, attribution (P0.1) persisted, no PII, tampered client fields ignored.
  D. safety: an unmapped future original product is still measured (logged
     ERROR, category "other") and never raises; other generators return None.

LOCAL ONLY (jyotishasha_local). No credential is stored here: set
LOCAL_TEST_DATABASE_URL (or PGPASSWORD / pgpass with the password-free default).
The run is refused unless the connected database is jyotishasha_local. Test
orders are removed at the end; no product flag is ever changed.
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
from modules.intents.question_catalog import get_question  # noqa: E402
from modules.models_processed_payments import ProcessedPayment  # noqa: E402
from modules.payments.report_product_registry import ReportProduct  # noqa: E402
from modules.payments.razorpay_provider import RazorpayProvider  # noqa: E402
from modules.payments.report_generation_dispatcher import ReportGenerationDispatcher, ReportGenerationDispatchStatus  # noqa: E402
from modules.payments import purchase_measurement as pm  # noqa: E402
from modules.payments.payment_models import PaymentVerificationResult, PaymentStatus, PaymentProviderType  # noqa: E402
from config.pricing import PRODUCT_PRICES  # noqa: E402
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


MARKER = "ads-p02a-test"
_n = {"n": 0}


def _unique(prefix):
    _n["n"] += 1
    return f"{prefix}-{_n['n']}"


# The 25 original products, frozen here independently of the code under test.
EXPECTED_ORIGINALS = {
    "business_report", "career_report", "children_parenting_report", "delay_in_marriage_report", "divorce_possibility_report",
    "financial_report", "financial_stability_report", "foreign_travel_report", "gemstone_consultation", "government_job_report",
    "jupiter_transit_report", "legal_disputes_report", "lifestyle_analysis_report", "love_disappointment_report", "love_marriage_report",
    "love_relationship_report", "marriage_report", "mood_mental_health_report", "problem_in_marriage_report", "property_report",
    "sadhesati_report", "saturn_transit_report", "second_marriage_report", "startup_suggestion_report", "relationship_future_report",
}
STANDARD_SLUG = "startup_suggestion_report"      # standard_v1, category finance
RELATIONSHIP_SLUG = "relationship_future_report"  # love_premium_v1, category love
PII_MARKERS = ("Original Test User", "9876543210", "1994-01-26", "Sindhnur Rural", "Original Partner", "1992-08-15", MARKER)
ALLOWED = set(pm.ALLOWED_FIELDS)
CATEGORY_VOCAB = {"transit", "finance", "love", "marriage", "self"}


def standard_payload(**over):
    p = {"product": STANDARD_SLUG, "name": "Original Test User", "email": f"{MARKER}-{_unique('s')}@example.com", "phone": "9876543210",
         "dob": "1994-01-26", "tob": "08:40", "pob": "Sindhnur Rural", "latitude": "15.6167", "longitude": "76.6833", "language": "en"}
    p.update(over)
    return p


def relationship_payload(**over):
    p = {"product": RELATIONSHIP_SLUG, "name": "Original Test User", "email": f"{MARKER}-{_unique('r')}@example.com",
         "dob": "1994-01-26", "tob": "08:40", "pob": "Sindhnur Rural", "latitude": 15.6167, "longitude": 76.6833, "language": "en",
         "partner": {"name": "Original Partner", "dob": "1992-08-15", "tob": "06:30", "pob": "Mumbai", "latitude": 19.076, "longitude": 72.8777}}
    p.update(over)
    return p


def mock_razorpay():
    m = MagicMock()
    m.order.create.side_effect = lambda payload: {"id": _unique("order_rp_p02a"), "currency": "INR"}
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


def pay(client, order, payment_id=None, verify_result=None, dispatch_result=None):
    payment_id = payment_id or _unique("pay_rp_p02a")
    record = {"id": payment_id, "order_id": order.razorpay_order_id, "amount": order.amount_paise, "status": "captured"}
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
    db.session.execute(text("DELETE FROM processed_payments WHERE reference LIKE 'order_rp_p02a%' OR reference LIKE 'rp_p02a_%'"))
    db.session.commit()


def bulk_order(slug, price, paid):
    o = Order(name="Original Test User", email=f"{MARKER}-bulk-{_unique('b')}@example.com", phone="9876543210", product=slug,
              status="PAID" if paid else "PENDING", payment_status="PAID" if paid else "PAYMENT_PENDING",
              razorpay_order_id=_unique("rp_p02a_order"), amount_paise=int(price) * 100)
    db.session.add(o)
    db.session.flush()
    return o


def main():
    with app.app_context():
        assert db.session.execute(text("SELECT current_database()")).scalar() == "jyotishasha_local", "Refusing to run: not jyotishasha_local"
        cleanup()
        client = app.test_client()
        try:
            # ==========================================================
            print("\n=== A. explicit category table for the original 25 ===")
            # ==========================================================
            originals = {r.report_slug: r for r in ReportProduct.query.filter(ReportProduct.generator.in_(("standard_v1", "love_premium_v1"))).all()}
            mapping = pm.ORIGINAL_REPORT_CATEGORIES
            check("A1: the registry holds exactly 25 original products (24 standard_v1 + 1 love_premium_v1)",
                  len(originals) == 25 and sum(1 for r in originals.values() if r.generator == "standard_v1") == 24
                  and [r.generator for r in originals.values() if r.report_slug == RELATIONSHIP_SLUG] == ["love_premium_v1"])
            check("A2: the registry's originals equal the frozen expected 25 slugs", set(originals) == EXPECTED_ORIGINALS)
            check("A3: COVERAGE -- ORIGINAL_REPORT_CATEGORIES keys equal EXACTLY the 25 original registry products (no missing, no extra)",
                  set(mapping) == set(originals) == EXPECTED_ORIGINALS and len(mapping) == 25)
            check("A4: ...and the legacy pricing table covers the same 25", set(PRODUCT_PRICES) == EXPECTED_ORIGINALS)
            check("A5: every mapped category is from the approved vocabulary; NONE is the 'other' fallback",
                  set(mapping.values()) <= CATEGORY_VOCAB and pm.UNMAPPED_ORIGINAL_CATEGORY not in mapping.values())
            check("A6: the registry prices are 51 for the 24 standard reports and 199 for relationship_future_report",
                  all(r.price == 51 for s, r in originals.items() if s != RELATIONSHIP_SLUG) and originals[RELATIONSHIP_SLUG].price == 199
                  and all(r.currency == "INR" for r in originals.values()))
            check("A7: approved naming -- standard_v1 -> original_report/standard, love_premium_v1 -> original_report/relationship",
                  pm.MEASURED_GENERATORS["standard_v1"] == ("original_report", "standard") and pm.MEASURED_GENERATORS["love_premium_v1"] == ("original_report", "relationship")
                  and pm.MEASURED_GENERATORS["focused_v1"] == ("focused_report", "self") and pm.MEASURED_GENERATORS["focused_dual_v1"] == ("focused_report", "dual"))

            # ==========================================================
            print("\n=== B. registry-wide coverage: 88 / 88 ===")
            # ==========================================================
            registry = ReportProduct.query.all()
            by_gen = {}
            for r in registry:
                by_gen.setdefault(r.generator, []).append(r)
            check("B1: the registry holds exactly 88 paid report products: 54 focused_v1 + 9 focused_dual_v1 + 24 standard_v1 + 1 love_premium_v1",
                  len(registry) == 88 and {g: len(v) for g, v in by_gen.items()} == {"focused_v1": 54, "focused_dual_v1": 9, "standard_v1": 24, "love_premium_v1": 1})

            good = 0
            problems = []
            unpaid_leaks = []
            seen_tx = set()
            counts = {("focused_report", "self"): 0, ("focused_report", "dual"): 0, ("original_report", "standard"): 0, ("original_report", "relationship"): 0}
            for r in registry:
                paid = bulk_order(r.report_slug, r.price, paid=True)
                unpaid = bulk_order(r.report_slug, r.price, paid=False)
                m = pm.build_purchase_measurement(paid.id)
                if pm.build_purchase_measurement(unpaid.id) is not None:
                    unpaid_leaks.append(r.report_slug)
                if m is None:
                    problems.append((r.report_slug, "no measurement"))
                    continue
                family, rtype = pm.MEASURED_GENERATORS[r.generator]
                expected_category = get_question(r.report_slug).category if family == "focused_report" else mapping[r.report_slug]
                ok = (m["transaction_id"] == f"ord_{paid.id}" and m["transaction_id"] not in seen_tx
                      and m["value"] == r.price and m["currency"] == "INR" and m["item_id"] == r.report_slug and m["item_name"] == r.name
                      and m["item_category"] == expected_category and m["product_family"] == family and m["report_type"] == rtype
                      and m["payment_provider"] == "RAZORPAY" and m["source_platform"] == "web"
                      and set(m) <= ALLOWED and not any(x in json.dumps(m) for x in PII_MARKERS))
                seen_tx.add(m["transaction_id"])
                if ok:
                    good += 1
                    counts[(family, rtype)] += 1
                else:
                    problems.append((r.report_slug, m))
            db.session.commit()
            print(f"  COVERAGE: {good}/88 registry products produce a correct canonical purchase_measurement; breakdown {counts}")
            check("B2: 88 / 88 -- every registry product yields the correct canonical object for a PAID Order", good == 88 and not problems)
            check("B3: breakdown is exactly 54 focused SELF + 9 focused DUAL + 24 original standard + 1 original relationship",
                  counts == {("focused_report", "self"): 54, ("focused_report", "dual"): 9, ("original_report", "standard"): 24, ("original_report", "relationship"): 1})
            check("B4: an UNPAID Order of every one of the 88 products yields NOTHING", not unpaid_leaks)
            check("B5: canonical values -- INR 51 for 87 products and INR 199 for relationship_future_report",
                  sum(1 for r in registry if r.price == 51) == 87 and [r.report_slug for r in registry if r.price == 199] == [RELATIONSHIP_SLUG])
            check("B6: all 88 transaction ids are distinct and follow ord_<Order.id>", len(seen_tx) == 88)

            # ==========================================================
            print("\n=== C. real order -> /webhook flows for the original reports ===")
            # ==========================================================
            attribution = {"attribution_type": "latest_click", "utm_source": "google", "utm_medium": "cpc", "utm_campaign": "orig_std",
                           "gclid": "P02A_GCLID", "landing_page": "/reports/startup_suggestion_report"}
            tamper = {"amount": 1, "price": 1, "value": 1, "currency": "USD", "product_family": "focused_report", "item_category": "evil",
                      "item_name": "EVIL", "report_type": "self", "transaction_id": "ord_1", "payment_provider": "STRIPE", "source_platform": "app"}

            std = create_order(client, standard_payload(attribution=attribution, **tamper))
            check("C0: an original standard order is created through the real route (PAYMENT_PENDING, amount 5100 paise)", std.payment_status == "PAYMENT_PENDING" and std.amount_paise == 5100)
            check("C1: unpaid standard order -> no measurement", pm.build_purchase_measurement(std.id) is None)
            bad, _ = pay(client, std, verify_result=failed_verification(std.razorpay_order_id))
            check("C2: failed verification -> non-2xx, NO purchase_measurement, Order still unpaid",
                  bad.status_code >= 400 and "purchase_measurement" not in (bad.get_json() or {}) and std.payment_status == "PAYMENT_PENDING" and pm.build_purchase_measurement(std.id) is None)
            r, pay_id = pay(client, std)
            body = r.get_json(); m = body.get("purchase_measurement")
            check("C3: verified standard purchase -> 200 with the canonical object",
                  r.status_code == 200 and body["status"] == "success" and m == {
                      "transaction_id": f"ord_{std.id}", "value": 51, "currency": "INR", "item_id": STANDARD_SLUG, "item_name": originals[STANDARD_SLUG].name,
                      "item_category": "finance", "product_family": "original_report", "report_type": "standard", "payment_provider": "RAZORPAY", "source_platform": "web"})
            check("C4: the Order is PAID; the object came from trusted data, not the tampered client fields (INR 51 from amount_paise)", std.payment_status == "PAID" and m["value"] == 51 and m["currency"] == "INR")
            check("C5: attribution (P0.1) was persisted against THIS original standard Order and is unaffected by payment",
                  OrderAttribution.query.filter_by(order_id=std.id).one().gclid == "P02A_GCLID" and int(m["transaction_id"][4:]) == std.id)
            check("C6: click ids / UTM stay out of the purchase payload; no PII anywhere in the response",
                  "P02A_GCLID" not in json.dumps(m) and "google" not in json.dumps(m) and not any(x in json.dumps(body) for x in PII_MARKERS))
            dup, _ = pay(client, std, payment_id=pay_id)
            check("C7: duplicate callback -> 'already_processing' with the IDENTICAL transaction_id (one payment claim)",
                  dup.get_json()["status"] == "already_processing" and dup.get_json()["purchase_measurement"]["transaction_id"] == m["transaction_id"]
                  and ProcessedPayment.query.filter_by(payment_id=pay_id).count() == 1)

            delayed = create_order(client, standard_payload())
            rd, _ = pay(client, delayed, dispatch_result=MagicMock(status=ReportGenerationDispatchStatus.DISPATCH_FAILED))
            check("C8: PAID with report generation delayed -> the purchase is still carried (real money)",
                  rd.get_json()["status"] == "payment_confirmed_processing_delayed" and rd.get_json()["purchase_measurement"]["transaction_id"] == f"ord_{delayed.id}")

            organic = create_order(client, standard_payload())
            ro, _ = pay(client, organic)
            check("C9: an organic standard purchase (no attribution) works and is measured; no attribution row",
                  ro.get_json()["purchase_measurement"]["value"] == 51 and OrderAttribution.query.filter_by(order_id=organic.id).count() == 0)

            rel = create_order(client, relationship_payload(attribution=dict(attribution, utm_campaign="orig_rel"), **tamper))
            check("C10: a relationship order is created (love_premium_v1, amount 19900 paise)", rel.payment_status == "PAYMENT_PENDING" and rel.amount_paise == 19900 and rel.partner_payload is not None)
            check("C11: unpaid relationship order -> no measurement", pm.build_purchase_measurement(rel.id) is None)
            badr, _ = pay(client, rel, verify_result=failed_verification(rel.razorpay_order_id))
            check("C12: failed relationship verification -> non-2xx, no measurement", badr.status_code >= 400 and "purchase_measurement" not in (badr.get_json() or {}) and pm.build_purchase_measurement(rel.id) is None)
            rr, rel_pay = pay(client, rel)
            rbody = rr.get_json(); rm = rbody.get("purchase_measurement")
            check("C13: verified relationship purchase -> canonical object with value 199, INR, original_report / relationship, category love",
                  rr.status_code == 200 and rm == {
                      "transaction_id": f"ord_{rel.id}", "value": 199, "currency": "INR", "item_id": RELATIONSHIP_SLUG, "item_name": originals[RELATIONSHIP_SLUG].name,
                      "item_category": "love", "product_family": "original_report", "report_type": "relationship", "payment_provider": "RAZORPAY", "source_platform": "web"})
            check("C14: relationship attribution persisted against the relationship Order; no partner/PII in the measurement",
                  OrderAttribution.query.filter_by(order_id=rel.id).one().utm_campaign == "orig_rel" and not any(x in json.dumps(rbody) for x in PII_MARKERS))
            rdup, _ = pay(client, rel, payment_id=rel_pay)
            check("C15: relationship duplicate callback carries the identical transaction_id", rdup.get_json()["purchase_measurement"]["transaction_id"] == rm["transaction_id"])

            # ==========================================================
            print("\n=== D. safety ===")
            # ==========================================================
            unmapped_paid = bulk_order(STANDARD_SLUG, 51, paid=True)
            db.session.commit()
            shrunk = {k: v for k, v in pm.ORIGINAL_REPORT_CATEGORIES.items() if k != STANDARD_SLUG}
            with patch.object(pm, "ORIGINAL_REPORT_CATEGORIES", shrunk), patch.object(pm._logger, "error") as logged:
                fallback = pm.build_purchase_measurement(unmapped_paid.id)
            check("D1: an unmapped original product (future misconfiguration) is still measured as a real sale, category 'other', with an ERROR logged, never raising",
                  fallback is not None and fallback["item_category"] == "other" and logged.called and fallback["value"] == 51)
            weird = ReportProduct.query.get(STANDARD_SLUG)
            original_generator = weird.generator
            ReportProduct.query.filter_by(report_slug=STANDARD_SLUG).update({"generator": "weird_v1"}, synchronize_session=False)
            db.session.commit()
            try:
                check("D2: a PAID order of an unmeasured generator returns None", pm.build_purchase_measurement(unmapped_paid.id) is None)
            finally:
                ReportProduct.query.filter_by(report_slug=STANDARD_SLUG).update({"generator": original_generator}, synchronize_session=False)
                db.session.commit()
            with patch.object(pm.db.session, "get", side_effect=RuntimeError("boom")):
                check("D3: an internal error is swallowed (None) -- payment finalization can never be broken by measurement", pm.build_purchase_measurement(std.id) is None)
        finally:
            db.session.rollback()
            _LazyRazorpayClient._real_client = None
            cleanup()

        check("Z: test orders removed and the standard product's generator restored",
              Order.query.filter(Order.email.like(f"{MARKER}%")).count() == 0 and ReportProduct.query.get(STANDARD_SLUG).generator == "standard_v1")

    print("\n==================================================")
    print(f"RESULT: {passed} passed, {failed} failed")
    print("==================================================")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
