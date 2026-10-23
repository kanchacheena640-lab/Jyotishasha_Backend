"""
test_report_payment_verified_event.py
--------------------------------------
R2-E2 -- website (Razorpay) paid-report purchases record payment_verified.

Proves, against the real local PostgreSQL ledger (its partial unique index
ux_activity_events_dedupe_key is what makes the event exactly-once):

  1. first successful website payment -> exactly one payment_verified row
     with the canonical contract (purpose/provider/order_reference/amount/
     currency, entity order/<id>, dedupe key, campaign, no personal data)
  2. duplicate delivery of the same payment -> still one row
  3. browser callback vs Razorpay webhook racing in two threads -> one row
  4. failed signature / wrong amount / non-pending Order -> no row
  5. analytics failures (ledger write, currency lookup) never fail the
     payment and never keep report dispatch from running (route level)
  6. a Google Play request never produces a website report event
  7. the admin metric report_payment_verified counts the purchase

Razorpay's network API is mocked throughout; report dispatch is stopped at
threading.Thread (no generation, email or AI call). LOCAL ONLY: refuses to
run against anything but jyotishasha_local on localhost.
"""

import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = os.environ.get("LOCAL_TEST_DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/jyotishasha_local")
if not any(host in LOCAL_DB_URL for host in ("@127.0.0.1:", "@localhost:")) or not LOCAL_DB_URL.endswith("/jyotishasha_local"):
    raise SystemExit("Refusing to run: LOCAL_TEST_DATABASE_URL must point at jyotishasha_local on localhost.")
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from models import Order  # noqa: E402
from modules.models_activity_events import ActivityEvent  # noqa: E402
from modules.models_processed_payments import ProcessedPayment  # noqa: E402
from modules.payments.order_service import OrderService  # noqa: E402
from modules.payments.payment_models import (  # noqa: E402
    PaymentProviderType, PaymentPurpose, PaymentRequest, PaymentStatus, PaymentVerificationResult,
)
from modules.payments.payment_finalization_service import (  # noqa: E402
    PaymentFinalizationService, ReportPaymentFinalizationStatus,
)
from modules.payments.razorpay_provider import RazorpayProvider  # noqa: E402
from modules.payments.campaign_attribution import (  # noqa: E402
    build_razorpay_notes_fields, sanitize_campaign_attribution_snapshot,
)
from modules.payments import report_payment_events  # noqa: E402
from modules.payments.report_payment_events import (  # noqa: E402
    emit_report_payment_verified, report_payment_verified_dedupe_key,
)

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


STANDARD_SLUG = "career_report"
MARKER_EMAIL_PREFIX = "r2e2-pv-test"
RUN = uuid.uuid4().hex[:8]
PII = ("R2E2 Tester", MARKER_EMAIL_PREFIX, "9876501234", "1990-08-15", "06:30", "Varanasi", "25.3176")
CAMPAIGN = sanitize_campaign_attribution_snapshot({"utm_source": "google", "utm_medium": "organic", "utm_campaign": "saturn-seo"})
_counter = {"n": 0}


def _unique(prefix):
    _counter["n"] += 1
    return f"{prefix}_{RUN}_{_counter['n']}"


def make_pending_order(**overrides):
    payload = {
        "product": STANDARD_SLUG, "name": "R2E2 Tester",
        "email": f"{MARKER_EMAIL_PREFIX}-{RUN}@example.com", "phone": "9876501234",
        "dob": "1990-08-15", "tob": "06:30", "pob": "Varanasi",
        "latitude": "25.3176", "longitude": "82.9739", "language": "en",
    }
    payload.update(overrides)
    order = OrderService().create_pending_order(payload)
    order.razorpay_order_id = _unique("order_r2e2")
    order.payment_status = "PAYMENT_PENDING"
    db.session.commit()
    db.session.refresh(order)
    return order


def make_request(order, payment_id=None, source=None, campaign_context=None):
    return PaymentRequest(
        provider=PaymentProviderType.RAZORPAY, purpose=PaymentPurpose.REPORT_PURCHASE,
        reference=order.razorpay_order_id, payment_id=payment_id or _unique("pay_r2e2"),
        signature=None if source == "webhook" else "sig_test",
        metadata={"source": source} if source else {}, campaign_context=campaign_context,
    )


def verified(reference):
    return PaymentVerificationResult(status=PaymentStatus.VERIFIED, provider=PaymentProviderType.RAZORPAY,
                                     reference=reference, verified=True, message="ok")


def rejected(reference):
    return PaymentVerificationResult(status=PaymentStatus.FAILED, provider=PaymentProviderType.RAZORPAY,
                                     reference=reference, verified=False, message="signature mismatch")


def payment_record(order, payment_id, amount_paise=None):
    return {"id": payment_id, "order_id": order.razorpay_order_id,
            "amount": order.amount_paise if amount_paise is None else amount_paise, "status": "captured"}


def events_for(payment_id):
    db.session.expire_all()
    return ActivityEvent.query.filter_by(dedupe_key=f"payment_verified:RAZORPAY:{payment_id}").all()


def verified_events_for_order(order_id):
    db.session.expire_all()
    return ActivityEvent.query.filter_by(event_name="payment_verified", entity_type="order", entity_id=str(order_id)).all()


def mocks(order, verify_result=None, amount_paise=None):
    """verify + fetch_payment mocked for one Order (no Razorpay network)."""
    return (
        patch.object(RazorpayProvider, "verify", return_value=verify_result or verified(order.razorpay_order_id)),
        patch.object(RazorpayProvider, "fetch_payment",
                     staticmethod(lambda pid: payment_record(order, pid, amount_paise=amount_paise))),
    )


def cleanup():
    db.session.rollback()
    db.session.execute(text("DELETE FROM activity_events WHERE dedupe_key LIKE :p"),
                       {"p": f"payment_verified:RAZORPAY:pay_r2e2_{RUN}%"})
    db.session.execute(text("DELETE FROM processed_payments WHERE payment_id LIKE :p"), {"p": f"pay_r2e2_{RUN}%"})
    Order.query.filter(Order.email.like(f"{MARKER_EMAIL_PREFIX}%")).delete(synchronize_session=False)
    db.session.commit()


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        if current_db != "jyotishasha_local":
            raise SystemExit("Refusing to run outside jyotishasha_local.")
        cleanup()
        service = PaymentFinalizationService()
        try:
            run_all(service)
        finally:
            cleanup()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


def run_all(service):
    # ------------------------------------------------------------------
    print("\n=== 1. first successful website payment ===")
    order = make_pending_order()
    req = make_request(order, campaign_context=CAMPAIGN)
    m1, m2 = mocks(order)
    with m1, m2:
        result = service.finalize_report_payment(req)
    check("1a: FINALIZED", result.status == ReportPaymentFinalizationStatus.FINALIZED)
    rows = events_for(req.payment_id)
    check("1b: exactly one payment_verified row", len(rows) == 1)
    ev = rows[0] if rows else None
    if ev is not None:
        p = ev.properties or {}
        check("1c: event_name / platform", ev.event_name == "payment_verified" and ev.platform == "backend_internal")
        check("1d: purpose REPORT_PURCHASE, provider RAZORPAY", p.get("purpose") == "REPORT_PURCHASE" and p.get("provider") == "RAZORPAY")
        check("1e: order_reference = Razorpay order id; entity = internal Order id",
              p.get("order_reference") == order.razorpay_order_id and ev.entity_type == "order" and ev.entity_id == str(order.id))
        check("1f: amount from Order.amount_paise in rupees (5100 -> 51), currency INR",
              order.amount_paise == 5100 and p.get("amount") == 51 and p.get("currency") == "INR")
        check("1g: dedupe key = payment_verified:RAZORPAY:<payment_id>", ev.dedupe_key == f"payment_verified:RAZORPAY:{req.payment_id}")
        check("1h: campaign attribution preserved", (ev.campaign_context or {}).get("utm_campaign") == "saturn-seo"
              and (ev.campaign_context or {}).get("utm_source") == "google")
        blob = f"{ev.properties} {ev.campaign_context} {ev.firebase_uid} {ev.profile_id} {ev.anonymous_id}"
        check("1i: no personal data in the event", not any(v in blob for v in PII) and "sig_test" not in blob)
        check("1j: allowed keys only", set(p) <= {"purpose", "provider", "order_reference", "amount", "currency"})
    db.session.expire_all()
    check("1k: Order PAID, claim recorded (payment behaviour unchanged)",
          db.session.get(Order, order.id).payment_status == "PAID"
          and ProcessedPayment.query.filter_by(provider="RAZORPAY", payment_id=req.payment_id).count() == 1)

    # ------------------------------------------------------------------
    print("\n=== 2. duplicate delivery (browser retry, then Razorpay webhook) ===")
    m1, m2 = mocks(order)
    with m1, m2, patch.object(report_payment_events, "record_event", wraps=report_payment_events.record_event) as spy:
        again = service.finalize_report_payment(make_request(order, payment_id=req.payment_id))
        hook = service.finalize_report_payment(make_request(order, payment_id=req.payment_id, source="webhook"))
    check("2a: both duplicates resolve ALREADY_FINALIZED",
          again.status == hook.status == ReportPaymentFinalizationStatus.ALREADY_FINALIZED)
    check("2b: no emit attempted for ALREADY_FINALIZED", spy.call_count == 0)
    check("2c: still exactly one row for the payment and the Order",
          len(events_for(req.payment_id)) == 1 and len(verified_events_for_order(order.id)) == 1)
    emit_report_payment_verified(req, order_id=order.id, product_slug=order.product, amount_paise=order.amount_paise)
    check("2d: a forced second emit is rejected by the ledger's unique dedupe index", len(events_for(req.payment_id)) == 1)

    # ------------------------------------------------------------------
    print("\n=== 3. browser callback vs Razorpay webhook race (two threads) ===")
    race_order = make_pending_order()
    race_order_id = race_order.id
    race_payment = _unique("pay_r2e2")
    barrier = threading.Barrier(2)
    outcomes = []

    def worker(source):
        with app.app_context():
            o = db.session.get(Order, race_order_id)
            r = make_request(o, payment_id=race_payment, source=source)
            barrier.wait()
            try:
                outcomes.append(PaymentFinalizationService().finalize_report_payment(r).status)
            except Exception as exc:  # pragma: no cover -- reported as a failure below
                outcomes.append(f"error:{exc}")
            finally:
                db.session.remove()

    m1, m2 = mocks(race_order)
    with m1, m2:
        threads = [threading.Thread(target=worker, args=(s,)) for s in (None, "webhook")]
        [t.start() for t in threads]
        [t.join(30) for t in threads]
    finalized = outcomes.count(ReportPaymentFinalizationStatus.FINALIZED)
    check(f"3a: exactly one FINALIZED (outcomes={outcomes})", finalized == 1 and len(outcomes) == 2)
    check("3b: exactly one payment_verified row after the race",
          len(events_for(race_payment)) == 1 and len(verified_events_for_order(race_order_id)) == 1)

    # ------------------------------------------------------------------
    print("\n=== 4. unverified / mismatched / non-pending -> no event ===")
    bad_sig = make_pending_order()
    r = make_request(bad_sig)
    m1, m2 = mocks(bad_sig, verify_result=rejected(bad_sig.razorpay_order_id))
    with m1, m2:
        res = service.finalize_report_payment(r)
    check("4a: failed signature -> VERIFICATION_FAILED, no event",
          res.status == ReportPaymentFinalizationStatus.VERIFICATION_FAILED and not events_for(r.payment_id))

    wrong_amt = make_pending_order()
    r = make_request(wrong_amt)
    m1, m2 = mocks(wrong_amt, amount_paise=wrong_amt.amount_paise + 100)
    with m1, m2:
        res = service.finalize_report_payment(r)
    db.session.expire_all()
    check("4b: wrong amount -> not finalized, Order not PAID, no event",
          res.status != ReportPaymentFinalizationStatus.FINALIZED and db.session.get(Order, wrong_amt.id).payment_status != "PAID"
          and not events_for(r.payment_id))

    created = make_pending_order()
    created.payment_status = "CREATED"
    db.session.commit()
    r = make_request(created)
    m1, m2 = mocks(created)
    with m1, m2:
        res = service.finalize_report_payment(r)
    check("4c: Order not PAYMENT_PENDING -> INVALID_STATE, no event",
          res.status == ReportPaymentFinalizationStatus.INVALID_STATE and not events_for(r.payment_id))

    pending = make_pending_order()
    check("4d: a pending Order that is never paid has no event", not verified_events_for_order(pending.id))

    # ------------------------------------------------------------------
    print("\n=== 5. analytics failures never fail the payment or block dispatch ===")
    boom = make_pending_order()
    r = make_request(boom)
    m1, m2 = mocks(boom)
    with m1, m2, patch.object(report_payment_events, "record_event", side_effect=RuntimeError("ledger down")):
        res = service.finalize_report_payment(r)
    db.session.expire_all()
    check("5a: ledger write raising -> still FINALIZED and PAID",
          res.status == ReportPaymentFinalizationStatus.FINALIZED and db.session.get(Order, boom.id).payment_status == "PAID")

    lookup = make_pending_order()
    r = make_request(lookup)
    m1, m2 = mocks(lookup)
    real_get = db.session.get

    def failing_get(model, ident, *a, **kw):
        if getattr(model, "__name__", "") == "ReportProduct":
            db.session.execute(text("SELECT 1/0"))  # a genuine failed SQL statement on the shared session
        return real_get(model, ident, *a, **kw)

    with m1, m2, patch.object(db.session, "get", side_effect=failing_get):
        res = service.finalize_report_payment(r)
    healthy = True
    try:
        db.session.execute(text("SELECT 1")).scalar()
    except Exception:
        healthy = False
        db.session.rollback()
    rows = events_for(r.payment_id)
    check("5b: failed currency lookup -> still FINALIZED", res.status == ReportPaymentFinalizationStatus.FINALIZED)
    check("5c: shared session still usable afterwards (dispatch can run)", healthy)
    check("5d: event still recorded, without currency", len(rows) == 1 and "currency" not in (rows[0].properties or {}))

    # Route level. Report dispatch is stopped at the dispatcher (a spy that
    # records the call and reports DISPATCHED): the real generation task
    # imports WeasyPrint, whose native libraries are not installed on this
    # machine -- the existing R6 route test fails its dispatch checks here
    # for that reason on main as well.
    from modules.payments.report_generation_dispatcher import (
        ReportGenerationDispatcher, ReportGenerationDispatchResult, ReportGenerationDispatchStatus,
    )
    client = app.test_client()

    def webhook_body(source, order_obj, payment_id):
        if source == "browser":
            return {"razorpay_order_id": order_obj.razorpay_order_id, "razorpay_payment_id": payment_id,
                    "razorpay_signature": "sig_test"}
        return {"event": "payment.captured",
                "payload": {"payment": {"entity": {"id": payment_id, "order_id": order_obj.razorpay_order_id,
                                                    "notes": build_razorpay_notes_fields(CAMPAIGN)}}}}

    def post_webhook(source, order_obj, payment_id, analytics_down=False):
        dispatched = []

        def spy_dispatch(self, order_id):
            dispatched.append(order_id)
            return ReportGenerationDispatchResult(status=ReportGenerationDispatchStatus.DISPATCHED, order_id=order_id)

        m1, m2 = mocks(order_obj)
        extra = (patch.object(report_payment_events, "record_event", side_effect=RuntimeError("ledger down"))
                 if analytics_down else patch.object(report_payment_events, "EVENT_SOURCE", report_payment_events.EVENT_SOURCE))
        with m1, m2, extra, \
             patch.object(RazorpayProvider, "verify_webhook_signature", return_value=True), \
             patch.object(RazorpayProvider, "fetch_order_campaign_context", staticmethod(lambda oid: CAMPAIGN)), \
             patch.object(ReportGenerationDispatcher, "dispatch_if_pending", spy_dispatch):
            resp = client.post("/webhook", json=webhook_body(source, order_obj, payment_id))
        return resp, dispatched

    for source in ("browser", "webhook"):
        o = make_pending_order()
        pid = _unique("pay_r2e2")
        resp, dispatched = post_webhook(source, o, pid, analytics_down=True)
        db.session.expire_all()
        fresh = db.session.get(Order, o.id)
        check(f"5e: /webhook ({source}) with analytics failing -> 200 success, PAID, dispatch called once",
              resp.status_code == 200 and (resp.get_json() or {}).get("status") == "success"
              and fresh.payment_status == "PAID" and dispatched == [o.id] and not events_for(pid))

    for source in ("browser", "webhook"):
        o = make_pending_order()
        pid = _unique("pay_r2e2")
        resp, dispatched = post_webhook(source, o, pid)
        rows = events_for(pid)
        check(f"5f: /webhook ({source}) end to end -> 200, dispatch once, one event with campaign",
              resp.status_code == 200 and dispatched == [o.id] and len(rows) == 1
              and (rows[0].campaign_context or {}).get("utm_source") == "google")
        resp2, dispatched2 = post_webhook("webhook" if source == "browser" else "browser", o, pid)
        check(f"5g: /webhook ({source}) then the other source for the same payment -> still one event",
              resp2.status_code == 200 and len(events_for(pid)) == 1 and len(verified_events_for_order(o.id)) == 1)

    # ------------------------------------------------------------------
    print("\n=== 6. Google Play never produces a website report event ===")
    gp = make_pending_order()
    gp_req = PaymentRequest(provider=PaymentProviderType.GOOGLE_PLAY, purpose=PaymentPurpose.REPORT_PURCHASE,
                            reference=gp.razorpay_order_id, payment_id=_unique("pay_r2e2_gp"), signature=None, metadata={})
    with patch.object(report_payment_events, "record_event") as spy:
        emit_report_payment_verified(gp_req, order_id=gp.id, product_slug=gp.product, amount_paise=gp.amount_paise)
    check("6a: GOOGLE_PLAY request -> no website emit", spy.call_count == 0)
    check("6b: no website dedupe key for GOOGLE_PLAY", report_payment_verified_dedupe_key(gp_req) is None)
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules", "payments", "payment_service.py"),
               encoding="utf-8").read()
    check("6c: PaymentService does not use the new emitter (Google Play path untouched)",
          "report_payment_events" not in src and "emit_report_payment_verified" not in src)

    # ------------------------------------------------------------------
    print("\n=== 7. admin metric counts the website purchase ===")
    from modules.activity_events.website_analytics_service import WebsiteAnalyticsService
    from modules.activity_events.analytics_models import AnalyticsWindow

    class LocalWebsiteAnalyticsService(WebsiteAnalyticsService):
        # The admin service reads environment="production" rows only; these
        # test rows are "local". Same report_payment_verified() query path.
        ENVIRONMENT = "local"

    def metric_now():
        now = datetime.now(timezone.utc)
        return LocalWebsiteAnalyticsService().report_payment_verified(
            AnalyticsWindow(start=now - timedelta(hours=1), end=now + timedelta(minutes=5))).value

    before = metric_now()
    counted = make_pending_order()
    r = make_request(counted, campaign_context=CAMPAIGN)
    m1, m2 = mocks(counted)
    with m1, m2:
        service.finalize_report_payment(r)
        service.finalize_report_payment(make_request(counted, payment_id=r.payment_id, source="webhook"))  # duplicate
    after = metric_now()
    check(f"7a: report_payment_verified rises by exactly 1 for one website purchase ({before} -> {after})",
          isinstance(before, int) and after == before + 1)


if __name__ == "__main__":
    main()
