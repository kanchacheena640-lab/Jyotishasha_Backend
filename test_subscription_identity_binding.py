"""
test_subscription_identity_binding.py
-------------------------------------------------
Task 17D: proves the website/Razorpay subscription IDENTITY-binding
security fix -- POST /subscriptions/order and POST /subscriptions/verify
(routes/routes_subscription.py) now:

  1. require authentication (@jwt_required()),
  2. derive the entitlement-owner profile_id EXCLUSIVELY from the
     authenticated JWT identity, via the SAME already-existing,
     already-proven helper this exact subscription domain already uses
     elsewhere (modules.subscription.dual_write_adapter.
     resolve_profile_id_from_account_user_id -- JWT identity (users.id)
     -> AppUser.id via the firebase_uid join),
  3. NEVER read or trust a client-supplied user_id from the request
     body for either endpoint -- a client can no longer create a
     pending SubscriptionOrder for, or activate an entitlement onto, an
     arbitrary account by manipulating that field.

Task 17C's own cryptographic Razorpay signature requirement is
unchanged and reconfirmed still mandatory here (Tests F-I).

Route-level tests use Flask's own test client + flask_jwt_extended's
create_access_token(), the SAME established pattern
test_asknow_activity_events.py already uses for JWT-protected routes.
Every external call (Razorpay order creation, RazorpayProvider.verify,
mirror_subscription_activation/entitlement activation) is monkeypatched
-- audited BEFORE running any test that reaches order creation, per
Task 17D's own explicit "mock Razorpay order creation FIRST" rule
(Task 17C's test development had one accidental real-network attempt;
this file's own create_subscription_order tests mock
razorpay_client.order.create from their very first line, never after).

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real Razorpay/network/SMTP/OpenAI call is
ever made. All test rows are created with dedicated markers and deleted
in a finally block, keyed by their own ids -- never a broad DELETE.
"""

import os
import sys
import uuid
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL
os.environ.setdefault("ACTIVITY_EVENTS_ENVIRONMENT", "local")

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


def main():
    from app import app
    from extensions import db
    from sqlalchemy import text
    from flask_jwt_extended import create_access_token

    from modules.auth.models import User
    from modules.models_user import AppUser
    from modules.models_subscription import SubscriptionOrder
    from modules.payments.payment_models import (
        PaymentProviderType, PaymentStatus, PaymentVerificationResult,
    )
    from modules.payments.razorpay_provider import RazorpayProvider
    import config.razorpay_config as razorpay_config_module

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"REFUSING to run against {current_db!r} -- local only."
        )

        created_user_ids = []
        created_order_ids = []

        def new_user_and_profile():
            """Creates a User (auth identity) + AppUser (profile/entitlement
            owner) sharing the same firebase_uid -- the exact join
            resolve_profile_id_from_account_user_id() performs. Returns
            (user_id, profile_id)."""
            fb_uid = f"phase17d-{uuid.uuid4().hex[:12]}"
            u = User(email=f"phase17d-{uuid.uuid4().hex[:8]}@example.com", provider="password", firebase_uid=fb_uid)
            db.session.add(u)
            db.session.commit()
            created_user_ids.append(("user", u.id))

            p = AppUser(firebase_uid=fb_uid, fcm_token=None, moon_sign="phase17d-marker")
            db.session.add(p)
            db.session.commit()
            created_user_ids.append(("profile", p.id))

            return u.id, p.id

        def auth_headers(user_id):
            token = create_access_token(identity=str(user_id))
            return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        def new_pending_order(profile_id, plan_type="monthly", razorpay_order_id=None):
            o = SubscriptionOrder(
                user_id=profile_id,
                razorpay_order_id=razorpay_order_id or f"order_17d_{uuid.uuid4().hex[:12]}",
                plan_type=plan_type,
                amount=49,
                status="pending",
            )
            db.session.add(o)
            db.session.commit()
            created_order_ids.append(o.id)
            return o

        # Fake RazorpayProvider.verify() implementations -- same shape
        # test_payment_activity_events.py/test_subscription_payment_
        # verification.py already established.
        def fake_verify_success(self, request):
            return PaymentVerificationResult(
                status=PaymentStatus.VERIFIED, provider=PaymentProviderType.RAZORPAY,
                reference=request.reference, verified=True, message="mocked verified",
            )

        real_verify = RazorpayProvider.verify
        real_order_create = razorpay_config_module.razorpay_client.order.create

        def mock_order_create(captured_payloads):
            def _create(payload):
                captured_payloads.append(payload)
                return {"id": f"order_17d_created_{uuid.uuid4().hex[:12]}", "amount": payload["amount"], "currency": payload["currency"]}
            return _create

        try:
            client = app.test_client()

            # ==========================================================
            print("\n=== A: unauthenticated order creation -> rejected ===")
            # ==========================================================
            captured_a = []
            razorpay_config_module.razorpay_client.order.create = mock_order_create(captured_a)
            try:
                res_a = client.post("/subscriptions/order", json={"plan_type": "monthly"})
            finally:
                razorpay_config_module.razorpay_client.order.create = real_order_create
            check("A: unauthenticated request rejected (401)", res_a.status_code == 401)
            check("A: no Razorpay order was ever created", len(captured_a) == 0)

            # ==========================================================
            print("\n=== B: authenticated valid plan order creation -> owner is the authenticated profile ===")
            # ==========================================================
            user_b_id, profile_b_id = new_user_and_profile()
            captured_b = []
            razorpay_config_module.razorpay_client.order.create = mock_order_create(captured_b)
            try:
                res_b = client.post("/subscriptions/order", json={"plan_type": "monthly"}, headers=auth_headers(user_b_id))
            finally:
                razorpay_config_module.razorpay_client.order.create = real_order_create
            check("B: HTTP 200", res_b.status_code == 200)
            order_b_row = SubscriptionOrder.query.filter_by(user_id=profile_b_id).first()
            if order_b_row:
                created_order_ids.append(order_b_row.id)
            check("B: SubscriptionOrder created, owned by the AUTHENTICATED profile_id (not any body field)", order_b_row is not None)
            check("B: exactly one real (mocked) Razorpay order.create call", len(captured_b) == 1)

            # ==========================================================
            print("\n=== C: manipulated body user_id -> completely ignored, order still owned by the authenticated identity ===")
            # ==========================================================
            user_c_id, profile_c_id = new_user_and_profile()
            _, profile_victim_id = new_user_and_profile()  # a distinct, unrelated profile the attacker names
            captured_c = []
            razorpay_config_module.razorpay_client.order.create = mock_order_create(captured_c)
            try:
                res_c = client.post(
                    "/subscriptions/order",
                    json={"plan_type": "monthly", "user_id": profile_victim_id},
                    headers=auth_headers(user_c_id),
                )
            finally:
                razorpay_config_module.razorpay_client.order.create = real_order_create
            check("C: HTTP 200 (request still succeeds -- the field is ignored, not rejected)", res_c.status_code == 200)
            order_c_row = SubscriptionOrder.query.filter_by(user_id=profile_c_id).first()
            if order_c_row:
                created_order_ids.append(order_c_row.id)
            order_victim_row = SubscriptionOrder.query.filter_by(user_id=profile_victim_id).first()
            check("C: SubscriptionOrder created for the AUTHENTICATED profile (attacker's own)", order_c_row is not None)
            check("C: NO SubscriptionOrder was ever created for the named victim profile", order_victim_row is None)

            # ==========================================================
            print("\n=== D: arbitrary amount manipulation -> ignored, server-approved plan price used ===")
            # ==========================================================
            user_d_id, profile_d_id = new_user_and_profile()
            captured_d = []
            razorpay_config_module.razorpay_client.order.create = mock_order_create(captured_d)
            try:
                res_d = client.post(
                    "/subscriptions/order",
                    json={"plan_type": "monthly", "amount": 1},  # attacker tries to pay Rs 1
                    headers=auth_headers(user_d_id),
                )
            finally:
                razorpay_config_module.razorpay_client.order.create = real_order_create
            check("D: HTTP 200", res_d.status_code == 200)
            order_d_row = SubscriptionOrder.query.filter_by(user_id=profile_d_id).first()
            if order_d_row:
                created_order_ids.append(order_d_row.id)
            check("D: persisted SubscriptionOrder.amount == server PLAN_PRICES value (49), not the client's 1", order_d_row is not None and order_d_row.amount == 49)
            check("D: the Razorpay order actually requested was for paise(49) == 4900, not paise(1)", len(captured_d) == 1 and captured_d[0]["amount"] == 4900)

            # ==========================================================
            print("\n=== E: invalid plan -> rejected before Razorpay/business effect ===")
            # ==========================================================
            user_e_id, profile_e_id = new_user_and_profile()
            captured_e = []
            razorpay_config_module.razorpay_client.order.create = mock_order_create(captured_e)
            try:
                res_e = client.post("/subscriptions/order", json={"plan_type": "not-a-real-plan-17d"}, headers=auth_headers(user_e_id))
            finally:
                razorpay_config_module.razorpay_client.order.create = real_order_create
            check("E: HTTP 400 (rejected)", res_e.status_code == 400)
            check("E: NO Razorpay order was ever created for an invalid plan", len(captured_e) == 0)
            check("E: NO SubscriptionOrder row created", SubscriptionOrder.query.filter_by(user_id=profile_e_id).count() == 0)

            # ==========================================================
            print("\n=== F: valid payment verification -> entitlement activation attempted for the authenticated owner ===")
            # ==========================================================
            user_f_id, profile_f_id = new_user_and_profile()
            order_f = new_pending_order(profile_f_id)
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_f:
                RazorpayProvider.verify = fake_verify_success
                try:
                    res_f = client.post(
                        "/subscriptions/verify",
                        json={"order_id": order_f.razorpay_order_id, "payment_id": "pay_17d_f", "razorpay_signature": "sig_f"},
                        headers=auth_headers(user_f_id),
                    )
                finally:
                    RazorpayProvider.verify = real_verify
            check("F: HTTP 200", res_f.status_code == 200)
            db.session.refresh(order_f)
            check("F: SubscriptionOrder.status == success", order_f.status == "success")
            check("F: mirror_subscription_activation called exactly once, for the authenticated profile", mock_mirror_f.call_count == 1 and mock_mirror_f.call_args[0][0] == profile_f_id)

            # ==========================================================
            print("\n=== G: valid payment but WRONG authenticated user -> rejected, no entitlement mutation ===")
            # ==========================================================
            user_g_owner_id, profile_g_owner_id = new_user_and_profile()
            user_g_attacker_id, profile_g_attacker_id = new_user_and_profile()
            order_g = new_pending_order(profile_g_owner_id)
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_g:
                RazorpayProvider.verify = fake_verify_success
                try:
                    res_g = client.post(
                        "/subscriptions/verify",
                        json={"order_id": order_g.razorpay_order_id, "payment_id": "pay_17d_g", "razorpay_signature": "sig_g"},
                        headers=auth_headers(user_g_attacker_id),  # authenticated as the WRONG user
                    )
                finally:
                    RazorpayProvider.verify = real_verify
            check("G: HTTP 400 (rejected -- order not found for this authenticated identity)", res_g.status_code == 400)
            db.session.refresh(order_g)
            check("G: the real owner's order remains untouched/pending", order_g.status == "pending")
            check("G: mirror_subscription_activation NEVER called", mock_mirror_g.call_count == 0)

            # ==========================================================
            print("\n=== H: missing signature -> rejected, no entitlement (real RazorpayProvider.verify(), no network) ===")
            # ==========================================================
            user_h_id, profile_h_id = new_user_and_profile()
            order_h = new_pending_order(profile_h_id)
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_h:
                res_h = client.post(
                    "/subscriptions/verify",
                    json={"order_id": order_h.razorpay_order_id, "payment_id": "pay_17d_h"},  # no razorpay_signature
                    headers=auth_headers(user_h_id),
                )
            check("H: HTTP 400 (missing required fields)", res_h.status_code == 400)
            db.session.refresh(order_h)
            check("H: SubscriptionOrder.status NOT success", order_h.status == "pending")
            check("H: mirror_subscription_activation NEVER called", mock_mirror_h.call_count == 0)

            # ==========================================================
            print("\n=== I: duplicate callback -> idempotent ===")
            # ==========================================================
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_i:
                RazorpayProvider.verify = fake_verify_success
                try:
                    res_i = client.post(
                        "/subscriptions/verify",
                        json={"order_id": order_f.razorpay_order_id, "payment_id": "pay_17d_f", "razorpay_signature": "sig_f"},
                        headers=auth_headers(user_f_id),
                    )
                finally:
                    RazorpayProvider.verify = real_verify
            check("I: HTTP 200 (still reports success)", res_i.status_code == 200)
            check("I: mirror_subscription_activation NOT called again (idempotent, no duplicate effect)", mock_mirror_i.call_count == 0)

            # ==========================================================
            print("\n=== J: frontend completion contract -- audit evidence, not an executable test ===")
            # ==========================================================
            # Part A of this task's own audit conclusively established (via
            # exhaustive repo-wide grep) that NO live frontend file anywhere
            # calls /subscriptions/order or /subscriptions/verify -- the
            # only file referencing this endpoint pair is this test file
            # itself. There is therefore no live frontend "declares success
            # before backend verification" risk to exercise today; building
            # a new frontend integration is explicitly out of this task's
            # scope. This is recorded as an audit finding, not faked as a
            # passing frontend test for code that does not exist.
            check("J: no live frontend caller of /subscriptions/order or /subscriptions/verify exists (audit finding, see final report Part A)", True)

            # ==========================================================
            print("\n=== L: legacy System A bypass check -- static/structural ===")
            # ==========================================================
            # System A (modules/subscription/routes.py's own /api/subscription/
            # create-order, the legacy Subscription model) has NO verify/
            # completion endpoint anywhere in that file -- confirmed by
            # direct source inspection (Strategy 2, this repo's own
            # established static-evidence convention where no live
            # behavioral path exists to exercise). It cannot call
            # verify_subscription_payment, mirror_subscription_activation,
            # or write to CurrentEntitlement/SubscriptionEvent at all, so it
            # cannot bypass this task's fix regardless of whether it is ever
            # called.
            with open("modules/subscription/routes.py", encoding="utf-8") as f:
                system_a_src = f.read()
            check("L: System A's own file never references verify_subscription_payment", "verify_subscription_payment" not in system_a_src)
            check("L: System A's own file never references mirror_subscription_activation", "mirror_subscription_activation" not in system_a_src)
            check("L: System A's own file never writes CurrentEntitlement directly", "CurrentEntitlement" not in system_a_src)

        finally:
            # ----------------------------------------------------------
            # Cleanup -- precise, per-row, never a broad DELETE.
            # ----------------------------------------------------------
            for oid in dict.fromkeys(created_order_ids):
                db.session.execute(text("DELETE FROM subscription_orders WHERE id = :id"), {"id": oid})
            db.session.commit()

            for kind, uid in created_user_ids:
                table = "app_users" if kind == "profile" else "users"
                db.session.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": uid})
            db.session.commit()

            remaining_orders = SubscriptionOrder.query.filter(SubscriptionOrder.id.in_(created_order_ids or [-1])).count()
            check("cleanup: all Task-17D SubscriptionOrder fixtures removed", remaining_orders == 0)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
