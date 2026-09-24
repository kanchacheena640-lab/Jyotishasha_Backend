"""
test_reports_ads_p01_order_attribution.py
-------------------------------------------------
Reports Ads P0.1 -- advertising attribution persisted against the
INTERNAL Order (models.OrderAttribution / table order_attributions,
modules/payments/order_attribution.py, wired into POST /api/razorpay-order).

Sections:
  A. pure sanitizer (no DB): full UTM set, gclid, gbraid/wbraid, fbclid,
     malformed / oversized / email-shaped values, PII keys ignored.
  B. schema: no PII columns, one row per Order, FK cascades.
  C. real Flask route integration (Razorpay's network boundary mocked,
     everything else real): SELF and DUAL focused orders, organic
     purchase, correct-Order persistence, isolation from payment, notes
     unchanged, existing campaign_context compatibility.

LOCAL ONLY (jyotishasha_local). The two non-pilot test products
(promotion_timing / relationship_lead_to_marriage) are flipped active only
inside try/finally and always restored to inactive; pilot products are
never touched. No real Razorpay / Celery / GPT / email call is ever made.
"""

import os
import sys
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# The LOCAL test database URL comes from the environment -- no credential is
# stored in this file. Set LOCAL_TEST_DATABASE_URL (with the local password),
# or leave it unset and supply the password via libpq's PGPASSWORD / pgpass.
# The password-free default below only names the local host/user/database.
# The run is refused below unless the connected database is jyotishasha_local.
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
from modules.payments.report_product_registry import ReportProduct  # noqa: E402
from modules.payments import order_attribution as oa  # noqa: E402
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


MARKER_EMAIL_PREFIX = "ads-p01-test"
_counter = {"n": 0}


def _unique(prefix):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


SELF_SLUG = "promotion_timing"                   # focused_v1
DUAL_SLUG = "relationship_lead_to_marriage"       # focused_dual_v1
PILOT_SLUGS = ("major_kundali_obstacles", "major_kundali_strengths")

PII_MARKERS = ("Attribution Test User", "9876543210", "1994-01-26", "Sindhnur Rural", "Attribution Partner", "1992-08-15")


def self_payload(**overrides):
    payload = {
        "product": SELF_SLUG, "name": "Attribution Test User",
        "email": f"{MARKER_EMAIL_PREFIX}-{_unique('u')}@example.com", "phone": "9876543210",
        "dob": "1994-01-26", "tob": "08:40", "pob": "Sindhnur Rural",
        "latitude": "15.6167", "longitude": "76.6833", "language": "en",
    }
    payload.update(overrides)
    return payload


def dual_payload(**overrides):
    payload = self_payload(product=DUAL_SLUG)
    payload["partner"] = {
        "name": "Attribution Partner", "dob": "1992-08-15", "tob": "06:30",
        "pob": "Mumbai", "latitude": "19.076", "longitude": "72.8777",
    }
    payload.update(overrides)
    return payload


def mock_razorpay():
    mock_client = MagicMock()
    mock_client.order.create.side_effect = lambda payload: {"id": _unique("order_rp_ads"), "currency": "INR"}
    _LazyRazorpayClient._real_client = mock_client
    return mock_client


def cleanup():
    # ON DELETE CASCADE removes the attribution rows with their Orders.
    Order.query.filter(Order.email.like(f"{MARKER_EMAIL_PREFIX}%")).delete(synchronize_session=False)
    db.session.commit()


def set_active(slug, value):
    ReportProduct.query.filter_by(report_slug=slug).update({"active": value}, synchronize_session=False)
    db.session.commit()


FULL_CLICK = {
    "attribution_type": "latest_click",
    "utm_source": "google", "utm_medium": "cpc", "utm_campaign": "promo_search_in",
    "utm_content": "ad_variant_a", "utm_term": "promotion astrology",
    "gclid": "Cj0KCQjw_TEST-gclid.123", "landing_page": "/reports/focused/promotion-timing",
    "referrer": "https://www.google.com/",
    "first_touch": {"utm_source": "newsletter", "utm_medium": "email", "landing_page": "/", "referrer": "https://t.co/abc"},
    "consent": {"geo_policy": "NORMAL", "analytics": None, "advertising": None},
}


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        assert db.session.execute(text("SELECT to_regclass('order_attributions')")).scalar() is not None, \
            "order_attributions table missing -- apply migration a7c3d91b2f40 to the LOCAL database first"
        cleanup()

        # ==============================================================
        print("\n=== A. sanitizer (pure) ===")
        # ==============================================================
        s = oa.sanitize_order_attribution(FULL_CLICK)
        check("A1 (1): full UTM set captured (source/medium/campaign/content/term)",
              (s["utm_source"], s["utm_medium"], s["utm_campaign"], s["utm_content"], s["utm_term"])
              == ("google", "cpc", "promo_search_in", "ad_variant_a", "promotion astrology"))
        check("A2 (2): gclid captured", s["gclid"] == "Cj0KCQjw_TEST-gclid.123")
        s3 = oa.sanitize_order_attribution({"attribution_type": "first_touch", "gbraid": "0AAAAAgbraid_1", "wbraid": "CjwwWbraid-2"})
        check("A3 (3): gbraid and wbraid captured", s3["gbraid"] == "0AAAAAgbraid_1" and s3["wbraid"] == "CjwwWbraid-2")
        s4 = oa.sanitize_order_attribution({"attribution_type": "first_touch", "fbclid": "IwAR0_fbclid-9"})
        check("A4 (4): fbclid captured", s4["fbclid"] == "IwAR0_fbclid-9")
        check("A5: landing_page and referrer captured", s["landing_page"] == "/reports/focused/promotion-timing" and s["referrer"] == "https://www.google.com/")
        check("A6: attribution_type and first_touch snapshot kept", s["attribution_type"] == "latest_click" and s["first_touch"]["utm_source"] == "newsletter")
        check("A7: consent snapshot kept (policy, unknown choice stays NULL)",
              s["consent_geo_policy"] == "NORMAL" and s["consent_analytics"] is None and s["consent_advertising"] is None)

        bad = oa.sanitize_order_attribution({
            "gclid": "has space", "gbraid": "<script>alert(1)</script>", "wbraid": "x" * 300, "fbclid": ["list"],
            "utm_source": 12345, "utm_medium": {"a": 1},
        })
        check("A8 (9): malformed click ids / non-string values are dropped, never stored",
              all(bad[k] is None for k in ("gclid", "gbraid", "wbraid", "fbclid", "utm_source", "utm_medium")) and bad["attribution_type"] == "none")
        big = oa.sanitize_order_attribution({"utm_source": "s" * 10000, "utm_campaign": "c" * 500})
        check("A9 (9): oversized free text is truncated to 256", len(big["utm_source"]) == 256 and len(big["utm_campaign"]) == 256)
        check("A10: control characters stripped", oa.sanitize_order_attribution({"utm_source": "goo\x00gle\n"})["utm_source"] == "google")
        em = oa.sanitize_order_attribution({"utm_source": "person@example.com", "utm_campaign": "ok", "referrer": "https://u:p@evil.example/x"})
        check("A11 (11): email-shaped values dropped (utm and referrer userinfo)", em["utm_source"] is None and em["referrer"] is None and em["utm_campaign"] == "ok")
        check("A12: non-dict attribution -> nothing to persist",
              all(oa.sanitize_order_attribution(v) is None for v in (None, "garbage", 42, ["a"], True)))
        check("A13: empty object -> a 'none' row is still warranted", oa.sanitize_order_attribution({})["attribution_type"] == "none")

        pii = oa.sanitize_order_attribution({
            "name": "Attribution Test User", "email": "x@y.com", "phone": "9876543210", "dob": "1994-01-26",
            "tob": "08:40", "pob": "Sindhnur Rural", "latitude": "15.6", "partner": {"name": "P"},
            "utm_source": "google",
        })
        allowed = set(OrderAttribution.__table__.columns.keys())
        check("A14 (11): PII keys in the payload are ignored -- output has only allowlisted columns",
              set(pii.keys()) <= allowed and not any(m in str(pii) for m in PII_MARKERS) and "x@y.com" not in str(pii))

        lp = oa._clean_landing_page
        check("A15: landing_page reduced to a bare path", lp("/hi/x?utm_source=a#f") == "/hi/x" and lp("http://evil.example/x") is None and lp("//evil.example/x") is None and lp("no-slash") is None)
        rf = oa._clean_referrer
        check("A16: referrer reduced to origin+path, non-http rejected",
              rf("https://t.co/x?q=1#z") == "https://t.co/x" and rf("javascript:alert(1)") is None and rf("ftp://h/x") is None)
        check("A17: claimed click/first_touch with no signal is downgraded to none",
              oa.sanitize_order_attribution({"attribution_type": "latest_click", "landing_page": "/x"})["attribution_type"] == "none")
        check("A18: missing/garbage type is derived from the signal",
              oa.sanitize_order_attribution({"gclid": "abc"})["attribution_type"] == "first_touch"
              and oa.sanitize_order_attribution({"attribution_type": "bogus", "gclid": "abc"})["attribution_type"] == "first_touch")
        bc = oa.sanitize_order_attribution({"consent": {"geo_policy": "MARS", "analytics": "yes", "advertising": 1}})
        check("A19: consent snapshot validated (bad policy / non-bool -> NULL)",
              bc["consent_geo_policy"] is None and bc["consent_analytics"] is None and bc["consent_advertising"] is None)

        # ==============================================================
        print("\n=== B. schema ===")
        # ==============================================================
        cols = set(db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='order_attributions'")).scalars().all())
        pii_cols = {"name", "email", "phone", "dob", "tob", "pob", "latitude", "longitude", "partner_payload", "firebase_uid", "session_id"}
        check("B1 (11): the table has no PII / identity columns", cols.isdisjoint(pii_cols) and {"order_id", "gclid", "gbraid", "wbraid", "fbclid", "utm_content", "utm_term"} <= cols)
        uq = db.session.execute(text("SELECT count(*) FROM pg_constraint WHERE conrelid='order_attributions'::regclass AND contype='u'")).scalar()
        cascade = db.session.execute(text("SELECT confdeltype FROM pg_constraint WHERE conrelid='order_attributions'::regclass AND contype='f'")).scalar()
        check("B2: exactly one attribution row per Order (UNIQUE order_id)", uq == 1)
        check("B3: FK to orders cascades on delete (never blocks/outlives an Order)", cascade == "c")

        # ==============================================================
        print("\n=== C. route integration (Razorpay mocked) ===")
        # ==============================================================
        set_active(SELF_SLUG, True)
        set_active(DUAL_SLUG, True)
        try:
            client = app.test_client()

            # --- SELF, full latest-click attribution ---
            mock = mock_razorpay()
            resp = client.post("/api/razorpay-order", json=self_payload(attribution=FULL_CLICK))
            body = resp.get_json()
            check("C1 (7): SELF order with attribution -> 200 and normal response shape",
                  resp.status_code == 200 and set(body.keys()) == {"order_id", "internal_order_id", "currency", "amount", "product"} and body["amount"] == 5100)
            order = db.session.get(Order, body["internal_order_id"])
            row = OrderAttribution.query.filter_by(order_id=order.id).first()
            check("C2 (6/7): attribution persisted against THIS internal Order (SELF, focused_v1 product)",
                  row is not None and order.product == SELF_SLUG and row.order_id == order.id)
            check("C3: all captured fields stored",
                  (row.utm_source, row.utm_medium, row.utm_campaign, row.utm_content, row.utm_term, row.gclid, row.landing_page, row.referrer, row.attribution_type)
                  == ("google", "cpc", "promo_search_in", "ad_variant_a", "promotion astrology", "Cj0KCQjw_TEST-gclid.123", "/reports/focused/promotion-timing", "https://www.google.com/", "latest_click"))
            check("C4: first-touch snapshot and consent snapshot stored",
                  row.first_touch and row.first_touch.get("utm_source") == "newsletter" and row.consent_geo_policy == "NORMAL"
                  and row.consent_analytics is None and row.consent_advertising is None)
            row_text = " ".join(str(getattr(row, c)) for c in row.__table__.columns.keys())
            check("C5 (11): no customer PII anywhere in the stored attribution row", not any(m in row_text for m in PII_MARKERS) and order.email not in row_text)

            # --- Razorpay notes are NOT expanded ---
            notes = mock.order.create.call_args.args[0]["notes"]
            check("C6 (locked): Razorpay notes NOT expanded with any new attribution field",
                  set(notes.keys()) <= {"internal_order_id", "report_slug", "utm_source", "utm_medium", "utm_campaign", "referrer"}
                  and not any(k in notes for k in ("gclid", "gbraid", "wbraid", "fbclid", "utm_content", "utm_term", "landing_page", "attribution")))

            # --- existing campaign_context still works alongside ---
            mock2 = mock_razorpay()
            ctx = {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "promo_search_in"}
            r2 = client.post("/api/razorpay-order", json=self_payload(campaign_context=ctx, attribution=FULL_CLICK))
            notes2 = mock2.order.create.call_args.args[0]["notes"]
            check("C7 (compat): existing campaign_context still reaches Razorpay notes unchanged",
                  r2.status_code == 200 and notes2.get("utm_source") == "google" and notes2.get("utm_campaign") == "promo_search_in")
            check("C7b: ...and the attribution row is ALSO persisted (temporary, documented duplication)",
                  OrderAttribution.query.filter_by(order_id=r2.get_json()["internal_order_id"]).count() == 1)

            # --- correct Order per request ---
            mock_razorpay()
            ra = client.post("/api/razorpay-order", json=self_payload(attribution={"attribution_type": "first_touch", "gclid": "AAA_first"})).get_json()
            rb = client.post("/api/razorpay-order", json=self_payload(attribution={"attribution_type": "first_touch", "gclid": "BBB_second"})).get_json()
            rowa = OrderAttribution.query.filter_by(order_id=ra["internal_order_id"]).one()
            rowb = OrderAttribution.query.filter_by(order_id=rb["internal_order_id"]).one()
            check("C8 (6): two orders -> each attribution row belongs to its own Order",
                  (rowa.gclid, rowb.gclid) == ("AAA_first", "BBB_second") and rowa.order_id != rowb.order_id)

            # --- DUAL ---
            mock_razorpay()
            rd = client.post("/api/razorpay-order", json=dual_payload(attribution=dict(FULL_CLICK, gclid=None, fbclid="IwAR_dual-1", utm_source="facebook", utm_medium="paid_social")))
            dbody = rd.get_json()
            dorder = db.session.get(Order, dbody["internal_order_id"])
            drow = OrderAttribution.query.filter_by(order_id=dorder.id).first()
            check("C9 (8): DUAL order (focused_dual_v1) -> 200 and attribution persisted against the DUAL Order",
                  rd.status_code == 200 and dorder.product == DUAL_SLUG and dorder.partner_payload is not None and drow is not None
                  and drow.fbclid == "IwAR_dual-1" and drow.utm_source == "facebook")
            drow_text = " ".join(str(getattr(drow, c)) for c in drow.__table__.columns.keys())
            check("C10 (11): DUAL partner birth data never enters the attribution row", not any(m in drow_text for m in PII_MARKERS))

            # --- organic / no attribution ---
            mock3 = mock_razorpay()
            ro = client.post("/api/razorpay-order", json=self_payload())
            oorder = db.session.get(Order, ro.get_json()["internal_order_id"])
            check("C11 (5): organic purchase with NO attribution still succeeds normally",
                  ro.status_code == 200 and oorder.payment_status == "PAYMENT_PENDING" and mock3.order.create.call_args.args[0]["amount"] == 5100)
            check("C11b: ...and no attribution row is created (older client / direct request)",
                  OrderAttribution.query.filter_by(order_id=oorder.id).count() == 0)

            mock_razorpay()
            rn = client.post("/api/razorpay-order", json=self_payload(attribution={"attribution_type": "none", "landing_page": "/reports/focused/x", "consent": {"geo_policy": "NORMAL", "analytics": None, "advertising": None}}))
            nrow = OrderAttribution.query.filter_by(order_id=rn.get_json()["internal_order_id"]).one()
            check("C12: browser reported 'no campaign signal' -> a 'none' row (distinct from no row)", nrow.attribution_type == "none" and nrow.gclid is None and nrow.landing_page == "/reports/focused/x")

            # --- invalid / oversized ---
            mock_razorpay()
            rg = client.post("/api/razorpay-order", json=self_payload(attribution="garbage"))
            check("C13 (9): non-object attribution -> order still 200, nothing persisted",
                  rg.status_code == 200 and OrderAttribution.query.filter_by(order_id=rg.get_json()["internal_order_id"]).count() == 0)
            mock_razorpay()
            rz = client.post("/api/razorpay-order", json=self_payload(attribution={"utm_source": "s" * 50000, "gclid": "not valid!!", "fbclid": "f" * 500, "landing_page": "http://evil.example/"}))
            zrow = OrderAttribution.query.filter_by(order_id=rz.get_json()["internal_order_id"]).one()
            check("C14 (9): oversized/invalid values -> order still 200; utm truncated, bad click ids + landing dropped",
                  rz.status_code == 200 and len(zrow.utm_source) == 256 and zrow.gclid is None and zrow.fbclid is None and zrow.landing_page is None)

            # --- attribution can never fail the payment path ---
            mock4 = mock_razorpay()
            with patch.object(oa, "sanitize_order_attribution", side_effect=RuntimeError("boom")):
                rf_ = client.post("/api/razorpay-order", json=self_payload(attribution=FULL_CLICK))
            forder = db.session.get(Order, rf_.get_json()["internal_order_id"])
            check("C15 (10): an internal attribution error is swallowed -- order + Razorpay order still succeed",
                  rf_.status_code == 200 and mock4.order.create.call_count == 1 and forder.payment_status == "PAYMENT_PENDING"
                  and OrderAttribution.query.filter_by(order_id=forder.id).count() == 0)

            # --- Razorpay failure keeps the (already persisted) attribution on the CREATED order ---
            failing = MagicMock()
            failing.order.create.side_effect = Exception("razorpay down")
            _LazyRazorpayClient._real_client = failing
            with patch("time.sleep"):
                rr = client.post("/api/razorpay-order", json=self_payload(attribution={"attribution_type": "first_touch", "gclid": "RZP_FAIL_1"}))
            created = Order.query.join(OrderAttribution, OrderAttribution.order_id == Order.id).filter(OrderAttribution.gclid == "RZP_FAIL_1").first()
            check("C16 (10): Razorpay failure -> non-2xx exactly as before; the CREATED order keeps its attribution",
                  rr.status_code >= 400 and created is not None and created.payment_status == "CREATED" and created.razorpay_order_id is None)

            # --- rejected orders never create attribution ---
            before = OrderAttribution.query.count()
            mock5 = mock_razorpay()
            r_inactive = client.post("/api/razorpay-order", json=self_payload(product=PILOT_SLUGS[0], attribution=FULL_CLICK))
            r_bad = client.post("/api/razorpay-order", json={"product": SELF_SLUG, "attribution": FULL_CLICK})
            check("C17 (10): inactive product / incomplete payload still rejected 4xx before Razorpay, no attribution row",
                  400 <= r_inactive.status_code < 500 and 400 <= r_bad.status_code < 500
                  and mock5.order.create.call_count == 0 and OrderAttribution.query.count() == before)

            # --- 1:1 idempotence ---
            first = oa.record_order_attribution(order.id, {"attribution_type": "first_touch", "gclid": "SECOND_WRITE"})
            check("C18: a repeat write for the same Order is a no-op (first write wins, still one row)",
                  first.gclid == "Cj0KCQjw_TEST-gclid.123" and OrderAttribution.query.filter_by(order_id=order.id).count() == 1)
        finally:
            db.session.rollback()
            set_active(SELF_SLUG, False)
            set_active(DUAL_SLUG, False)
            _LazyRazorpayClient._real_client = None

        cleanup()
        focused_active = ReportProduct.query.filter(ReportProduct.generator.in_(("focused_v1", "focused_dual_v1")), ReportProduct.active.is_(True)).count()
        check("Z: every focused product is inactive again (test flips fully reverted; pilots never touched)", focused_active == 0)

    print("\n==================================================")
    print(f"RESULT: {passed} passed, {failed} failed")
    print("==================================================")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
