"""
test_report_reviews.py -- F10-P15 verified-purchaser report reviews.

LOCAL ONLY: refuses to run unless DATABASE_URL (from .env) points at
127.0.0.1/localhost jyotishasha_local. Creates its own marker orders and
deletes them (and, via ON DELETE CASCADE, their reviews) at the end. No email
is sent, no Razorpay/OpenAI call is made.

Covers: unauthorized/forged/expired tokens, wrong email binding, unpaid and
undelivered orders, disabled-secret fail-closed, input validation, XSS text
stored as plain text and held for moderation, duplicate submissions (one row,
edits, edit limit), negative reviews published exactly like positive ones,
empty-state summary, average/count/distribution, moderation (reason codes,
admin auth), rate limiting, inactive products in availability, and the
delivery-email review link (present only when the secret is configured).
"""
import os
import sys
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import dotenv_values  # noqa: E402

LOCAL_DB_URL = os.environ.get("DATABASE_URL") or dotenv_values(".env").get("DATABASE_URL", "")
_u = urlparse(LOCAL_DB_URL)
if _u.hostname not in ("127.0.0.1", "localhost") or _u.path != "/jyotishasha_local":
    raise SystemExit("REFUSING TO RUN: test_report_reviews.py needs the local jyotishasha_local database.")
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "sk-local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")
os.environ.pop("REDIS_URL", None)  # exercise the in-process limiter deterministically
os.environ["REVIEW_LINK_SECRET"] = "local-test-review-secret-0123456789abcdef"
os.environ["ADMIN_BRIDGE_SECRET"] = "local-test-bridge-secret"

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import Order  # noqa: E402
from modules.payments.report_product_registry import ReportProduct  # noqa: E402
from modules.payments.report_delivery_service import delivery_message  # noqa: E402
from modules.reviews import rate_limit  # noqa: E402
from modules.reviews.models import ReportReview  # noqa: E402
from modules.reviews.review_tokens import issue_review_token  # noqa: E402

passed = failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


MARKER = "f10p15-review-test"
ADMIN = {"X-Admin-Bridge-Key": os.environ["ADMIN_BRIDGE_SECRET"]}
client = app.test_client()
_n = {"i": 0}


def make_order(product="career_report", *, payment_status="PAID", report_stage="Ready", email_status="SENT",
               name="Ravi Kumar Sharma", language="en"):
    _n["i"] += 1
    order = Order(name=name, email=f"{MARKER}-{_n['i']}@example.test", product=product, status="PAID",
                  payment_status=payment_status, report_stage=report_stage, email_status=email_status,
                  language=language, amount_paise=5100)
    db.session.add(order)
    db.session.commit()
    return order


def token_for(order):
    return issue_review_token(order.id, order.email)


_ip = {"n": 0}


def post(path, body, headers=None, ip=None):
    # A fresh client IP per call keeps functional checks independent of the
    # rate limiter; section 7 pins one IP to test the limiter itself.
    if ip is None:
        _ip["n"] += 1
        ip = f"10.{_ip['n'] // 65025 % 250}.{_ip['n'] // 255 % 255}.{_ip['n'] % 255}"
    return client.post(path, json=body, headers={**(headers or {}), "X-Forwarded-For": ip})


def cleanup():
    ids = [o.id for o in Order.query.filter(Order.email.like(f"{MARKER}-%")).all()]
    if ids:
        ReportReview.query.filter(ReportReview.order_id.in_(ids)).delete(synchronize_session=False)
        Order.query.filter(Order.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()


GOOD = "Clear and practical report. The career timing section matched my situation well."

with app.app_context():
    cleanup()
    rate_limit.reset_memory_for_tests()
    try:
        print("\n=== 1. Authorization / eligibility ===")
        delivered = make_order()
        r = post("/api/reviews/eligibility", {"token": token_for(delivered)})
        check("delivered paid order is eligible", r.status_code == 200 and r.json["eligible"] and r.json["product"] == "career_report")
        check("default display name is privacy-safe ('Ravi S.', no email)", r.json["default_display_name"] == "Ravi S.")
        check("no token -> 403", post("/api/reviews/submit", {"rating": 5, "body": GOOD}).status_code == 403)
        check("forged token -> 403 invalid_token", post("/api/reviews/submit", {"token": "abc.def.ghi", "rating": 5, "body": GOOD}).json.get("error") == "invalid_token")
        tampered = token_for(delivered)[:-2] + ("AA" if not token_for(delivered).endswith("AA") else "BB")
        check("tampered signature -> 403", post("/api/reviews/submit", {"token": tampered, "rating": 5, "body": GOOD}).status_code == 403)
        other = make_order()
        wrong_email = issue_review_token(other.id, "someone-else@example.test")
        check("token bound to a different email -> 403", post("/api/reviews/submit", {"token": wrong_email, "rating": 5, "body": GOOD}).status_code == 403)
        check("token for a non-existent order -> 403", post("/api/reviews/submit", {"token": issue_review_token(999999999, "x@example.test"), "rating": 5, "body": GOOD}).status_code == 403)
        unpaid = make_order(payment_status="CREATED")
        check("unpaid order -> not_paid", post("/api/reviews/submit", {"token": token_for(unpaid), "rating": 5, "body": GOOD}).json.get("error") == "not_paid")
        not_ready = make_order(report_stage="Processing")
        check("report not generated -> not_delivered", post("/api/reviews/submit", {"token": token_for(not_ready), "rating": 5, "body": GOOD}).json.get("error") == "not_delivered")
        email_failed = make_order(email_status="FAILED")
        check("PDF email not sent -> not_delivered", post("/api/reviews/submit", {"token": token_for(email_failed), "rating": 5, "body": GOOD}).json.get("error") == "not_delivered")
        saved = os.environ.pop("REVIEW_LINK_SECRET")
        check("secret missing -> fail closed (503 reviews_disabled)", post("/api/reviews/eligibility", {"token": "x"}).json.get("error") == "reviews_disabled")
        os.environ["REVIEW_LINK_SECRET"] = "too-short"
        check("secret too short -> fail closed", post("/api/reviews/eligibility", {"token": "x"}).status_code == 503)
        os.environ["REVIEW_LINK_SECRET"] = saved
        check("token is never accepted from the query string", client.post(f"/api/reviews/submit?token={token_for(delivered)}", json={"rating": 5, "body": GOOD}).status_code == 403)

        print("\n=== 2. Validation and XSS ===")
        t = token_for(make_order())
        for bad, code in [({"rating": 0}, "invalid_rating"), ({"rating": 6}, "invalid_rating"), ({"rating": "5"}, "invalid_rating"),
                          ({"rating": True}, "invalid_rating"), ({"rating": 4, "body": "too short"}, "invalid_body_length"),
                          ({"rating": 4, "body": "x" * 2001}, "invalid_body_length"),
                          ({"rating": 4, "body": GOOD, "display_name": "a" * 41}, "invalid_display_name"),
                          ({"rating": 4, "body": GOOD, "display_name": "Ravi 12345"}, "invalid_display_name")]:
            payload = {"token": t, "body": GOOD, **bad}
            check(f"rejects {list(bad)}={str(list(bad.values()))[:30]} -> {code}", post("/api/reviews/submit", payload).json.get("error") == code)
        xss = make_order()
        r = post("/api/reviews/submit", {"token": token_for(xss), "rating": 4, "body": "<script>alert(1)</script> nice report overall, very detailed"})
        row = ReportReview.query.filter_by(order_id=xss.id).one()
        check("HTML is stored verbatim as text (never rendered server-side)", "<script>" in row.body)
        check("HTML content is held PENDING for a human (auto flag 'html')", r.json["review"]["status"] == "PENDING" and "html" in (row.auto_flags or ""))
        link = make_order()
        r = post("/api/reviews/submit", {"token": token_for(link), "rating": 5, "body": "Great report, also visit www.spam-site.com for more readings"})
        check("link -> PENDING (spam guard), not published", r.json["review"]["status"] == "PENDING")
        phone = make_order()
        r = post("/api/reviews/submit", {"token": token_for(phone), "rating": 5, "body": "Good report. Call me on +91 98765 43210 for details please"})
        check("phone number -> PENDING (personal data guard)", r.json["review"]["status"] == "PENDING")

        print("\n=== 3. Negative reviews are treated exactly like positive ones ===")
        neg = make_order(product="sadhesati_report")
        r1 = post("/api/reviews/submit", {"token": token_for(neg), "rating": 1, "body": "Did not find this useful at all; the predictions were too generic for me."})
        pos = make_order(product="sadhesati_report")
        r5 = post("/api/reviews/submit", {"token": token_for(pos), "rating": 5, "body": "Very detailed and helpful explanation of my Sade Sati phase and remedies."})
        check("1-star review auto-PUBLISHED", r1.json["review"]["status"] == "PUBLISHED")
        check("5-star review auto-PUBLISHED", r5.json["review"]["status"] == "PUBLISHED")
        s = client.get("/api/reviews/product/sadhesati_report").json
        check("summary counts both (2) and averages 3.0", s["review_count"] == 2 and s["average_rating"] == 3.0)
        check("distribution shows the 1-star review", s["distribution"]["1"] == 1 and s["distribution"]["5"] == 1)
        check("public review exposes no email / order id", all(set(x) == {"id", "rating", "body", "display_name", "language", "date"} for x in s["reviews"]))

        print("\n=== 4. Duplicates and edits ===")
        dup = make_order(product="financial_report")
        t = token_for(dup)
        post("/api/reviews/submit", {"token": t, "rating": 3, "body": "Average report with some useful financial timing points."})
        post("/api/reviews/submit", {"token": t, "rating": 4, "body": "Updated: re-read it and the dasha section was quite useful."})
        rows = ReportReview.query.filter_by(order_id=dup.id).all()
        check("second submission edits the same row (one review per order)", len(rows) == 1 and rows[0].rating == 4 and rows[0].edit_count == 1)
        post("/api/reviews/submit", {"token": t, "rating": 4, "body": "Edit two of my review, still a useful financial report overall."})
        post("/api/reviews/submit", {"token": t, "rating": 4, "body": "Edit three of my review, still a useful financial report overall."})
        r = post("/api/reviews/submit", {"token": t, "rating": 5, "body": "Edit four should be refused because of the edit limit."})
        check("edit limit enforced (409 edit_limit_reached)", r.status_code == 409 and r.json["error"] == "edit_limit_reached")
        r = post("/api/reviews/eligibility", {"token": t})
        check("eligibility shows the buyer's own review with edits_left=0", r.json["review"]["edits_left"] == 0)

        print("\n=== 5. Empty state, unknown and disabled products ===")
        e = client.get("/api/reviews/product/legal_disputes_report").json
        check("product with no reviews -> count 0, average null, empty list", e["review_count"] == 0 and e["average_rating"] is None and e["reviews"] == [])
        check("unknown product -> 404", client.get("/api/reviews/product/not_a_product").status_code == 404)
        avail = client.get("/api/report-products/availability").json["products"]
        inactive = ReportProduct.query.filter_by(active=False).first()
        active = ReportProduct.query.filter_by(active=True).first()
        check("availability mirrors the registry active flag (inactive -> false)", inactive is None or avail[inactive.report_slug] is False)
        check("availability: active product -> true", active is None or avail[active.report_slug] is True)
        check("availability exposes only slug -> bool", all(isinstance(v, bool) for v in avail.values()) and len(avail) == ReportProduct.query.count())

        print("\n=== 6. Moderation ===")
        check("admin list without credentials -> 401/403", client.get("/api/admin/reviews").status_code in (401, 403))
        pending = client.get("/api/admin/reviews?status=PENDING", headers=ADMIN).json["reviews"]
        target = next(x for x in pending if x["id"] == ReportReview.query.filter_by(order_id=link.id).one().id)
        check("pending queue shows the flagged review with its flags", "link" in (target["auto_flags"] or ""))
        r = client.post(f"/api/admin/reviews/{target['id']}/moderate", json={"action": "reject"}, headers=ADMIN)
        check("reject without a reason code -> 400", r.status_code == 400 and r.json["error"] == "reject_reason_required")
        r = client.post(f"/api/admin/reviews/{target['id']}/moderate", json={"action": "reject", "reason": "NEGATIVE"}, headers=ADMIN)
        check("'negative' is not an allowed reject reason", r.status_code == 400)
        r = client.post(f"/api/admin/reviews/{target['id']}/moderate", json={"action": "reject", "reason": "SPAM"}, headers=ADMIN)
        check("reject with SPAM reason works and is recorded", r.status_code == 200 and r.json["moderation_reason"] == "SPAM")
        xss_id = ReportReview.query.filter_by(order_id=xss.id).one().id
        client.post(f"/api/admin/reviews/{xss_id}/moderate", json={"action": "publish"}, headers=ADMIN)
        cr = client.get("/api/reviews/product/career_report").json
        check("rejected review never appears publicly", all(x["id"] != target["id"] for x in cr["reviews"]))
        check("moderator-published review appears (raw text, clients escape)", any(x["id"] == xss_id for x in cr["reviews"]))
        check("moderation endpoint without credentials -> 401/403", client.post(f"/api/admin/reviews/{xss_id}/moderate", json={"action": "reject", "reason": "SPAM"}).status_code in (401, 403))

        print("\n=== 7. Rate limiting ===")
        rate_limit.reset_memory_for_tests()
        codes = [post("/api/reviews/submit", {"token": "bad"}, ip="10.9.9.9").status_code for _ in range(12)]
        check("11th+ submit from one IP within an hour -> 429", codes[:10].count(429) == 0 and codes[10:] == [429, 429])
        check("another IP is unaffected", post("/api/reviews/submit", {"token": "bad"}, ip="10.9.9.8").status_code == 403)

        print("\n=== 8. Delivery email review link ===")
        order = make_order(language="hi")
        subject, body = delivery_message(order)
        check("Hindi delivery email links to /hi/review with the token in the URL fragment", "https://www.jyotishasha.com/hi/review#t=" in body)
        en_order = make_order()
        _, en_body = delivery_message(en_order)
        check("English delivery email links to /review#t=", "https://www.jyotishasha.com/review#t=" in en_body and "?t=" not in en_body)
        token = en_body.split("/review#t=")[1].split()[0]
        check("emailed token is accepted by the eligibility endpoint", post("/api/reviews/eligibility", {"token": token}, ip="10.1.1.1").status_code == 200)
        saved = os.environ.pop("REVIEW_LINK_SECRET")
        _, plain = delivery_message(en_order)
        os.environ["REVIEW_LINK_SECRET"] = saved
        check("without REVIEW_LINK_SECRET the email body is unchanged (no link)", "review" not in plain.lower() and plain.endswith("Team Jyotishasha"))

        print("\n=== 9. F10-P16 hardening ===")
        rate_limit.reset_memory_for_tests()
        codes = [client.post("/api/reviews/submit", json={"token": "bad"}, headers={"X-Forwarded-For": f"203.0.113.{i}, 10.50.50.50"}).status_code for i in range(12)]
        check("spoofed leading X-Forwarded-For values cannot dodge the limiter (rightmost proxy IP is the key)", codes[10:] == [429, 429])
        check("client_key uses the rightmost X-Forwarded-For entry", rate_limit.client_key("1.1.1.1", "6.6.6.6, 7.7.7.7") == rate_limit.client_key("1.1.1.1", "7.7.7.7"))
        big = client.post("/api/reviews/submit", data='{"token": "' + "x" * 20000 + '"}', content_type="application/json", headers={"X-Forwarded-For": "10.60.0.1"})
        check("oversized submit body -> 413 before parsing", big.status_code == 413)
        big = client.post("/api/reviews/eligibility", data='{"token": "' + "x" * 20000 + '"}', content_type="application/json", headers={"X-Forwarded-For": "10.60.0.2"})
        check("oversized eligibility body -> 413", big.status_code == 413)
        from modules.reviews.review_tokens import read_review_token
        from itsdangerous import URLSafeTimedSerializer
        import hashlib
        hardened = make_order()
        sha1_token = URLSafeTimedSerializer(os.environ["REVIEW_LINK_SECRET"], salt="jyotishasha.report-review.v1").dumps({"o": hardened.id, "e": hashlib.sha256(hardened.email.strip().lower().encode()).hexdigest()[:16]})
        check("tokens are HMAC-SHA256: a SHA-1-signed token with the same secret is refused", post("/api/reviews/eligibility", {"token": sha1_token}).status_code == 403)
        check("issued tokens round-trip", read_review_token(token_for(hardened))[0] == hardened.id)
        r = post("/api/reviews/submit", {"token": token_for(hardened), "rating": 3, "body": "Totally unrelated text about cricket scores, not about the report at all."})
        rid = ReportReview.query.filter_by(order_id=hardened.id).one().id
        client.post(f"/api/admin/reviews/{rid}/moderate", json={"action": "reject", "reason": "OFF_TOPIC"}, headers=ADMIN)
        r = post("/api/reviews/submit", {"token": token_for(hardened), "rating": 3, "body": "Still unrelated text about cricket, edited to slip past the moderator."})
        check("editing a REJECTED review sends it back to PENDING, not straight to PUBLISHED", r.status_code == 200 and r.json["review"]["status"] == "PENDING")
        check("a re-submitted rejected review stays off the public page", all(x["id"] != rid for x in client.get("/api/reviews/product/career_report").json["reviews"]))

        print("\n=== 10. F10-P17 privacy request: find and delete a buyer's review ===")
        gone = make_order()
        post("/api/reviews/submit", {"token": token_for(gone), "rating": 2, "body": "Honest but negative feedback that the buyer later asks us to delete."})
        found = client.get(f"/api/admin/reviews?order_id={gone.id}", headers=ADMIN).json["reviews"]
        check("admin finds a review by order id, whatever its status", len(found) == 1 and found[0]["order_id"] == gone.id)
        check("order lookup requires admin credentials", client.get(f"/api/admin/reviews?order_id={gone.id}").status_code in (401, 403))
        check("non-numeric order id -> 400", client.get("/api/admin/reviews?order_id=1;drop", headers=ADMIN).status_code == 400)
        check("public reviews never expose the order id", all("order_id" not in x for x in client.get("/api/reviews/product/career_report").json["reviews"]))
        gid = found[0]["id"]
        check("delete without admin credentials -> 401/403", client.post(f"/api/admin/reviews/{gid}/moderate", json={"action": "delete"}).status_code in (401, 403))
        r = client.post(f"/api/admin/reviews/{gid}/moderate", json={"action": "delete"}, headers=ADMIN)
        check("admin delete removes the row entirely (no copy kept)", r.status_code == 200 and r.json["status"] == "DELETED" and ReportReview.query.get(gid) is None)
        check("deleted review is gone from the public page and summary", all(x["id"] != gid for x in client.get("/api/reviews/product/career_report").json["reviews"]))
        check("the order itself is untouched by review deletion", db.session.get(Order, gone.id) is not None)
        check("deleting again -> 404", client.post(f"/api/admin/reviews/{gid}/moderate", json={"action": "delete"}, headers=ADMIN).status_code == 404)

        print("\n=== 11. F10-P21T concurrent first submissions for one order ===")
        from types import SimpleNamespace
        from sqlalchemy import event, text
        from sqlalchemy.exc import IntegrityError
        from modules.reviews.review_service import is_duplicate_order_review
        raced = make_order()
        fired = {"n": 0}

        def competing_first_review(session, flush_context, instances):
            # Runs after submit_review's SELECT ... FOR UPDATE found no row and
            # just before its INSERT: a second request commits its review first.
            if fired["n"]:
                return
            fired["n"] += 1
            with db.engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO report_reviews (order_id, product, rating, body, display_name, language, status,"
                    " edit_count, created_at, updated_at, published_at)"
                    " VALUES (:o, 'career_report', 4, :b, 'Racer A.', 'en', 'PUBLISHED', 0, now(), now(), now())"),
                    {"o": raced.id, "b": GOOD})

        event.listen(db.session, "before_flush", competing_first_review)
        try:
            r = post("/api/reviews/submit", {"token": token_for(raced), "rating": 2, "body": GOOD})
        finally:
            event.remove(db.session, "before_flush", competing_first_review)
        check("losing a first-submission race -> 409 try_again, not 500", fired["n"] == 1 and r.status_code == 409 and r.json == {"error": "try_again"})
        rows = ReportReview.query.filter_by(order_id=raced.id).all()
        check("the race leaves exactly one review: the winner's, untouched", len(rows) == 1 and rows[0].rating == 4 and rows[0].edit_count == 0)
        r = post("/api/reviews/submit", {"token": token_for(raced), "rating": 2, "body": GOOD})
        check("retrying after try_again edits that one review (edit limit still applies)", r.status_code == 200 and r.json["review"]["edits_left"] == 2 and ReportReview.query.filter_by(order_id=raced.id).count() == 1)
        other_violation = IntegrityError("INSERT", {}, SimpleNamespace(diag=SimpleNamespace(constraint_name="ck_report_reviews_rating_1_5")))
        check("only the UNIQUE(order_id) conflict maps to try_again; other integrity errors are re-raised",
              not is_duplicate_order_review(other_violation) and not is_duplicate_order_review(IntegrityError("INSERT", {}, Exception("no diag"))))
    finally:
        cleanup()
        check("cleanup removed all marker orders and their reviews", Order.query.filter(Order.email.like(f"{MARKER}-%")).count() == 0)

print(f"\nRESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
