"""
test_subscription_payment_verification.py
-------------------------------------------------
Task 17C: proves the website/Razorpay subscription payment-verification
security fix -- modules/services/subscription_service.py::
verify_subscription_payment() now REQUIRES and cryptographically checks
a Razorpay checkout signature (via the SAME RazorpayProvider.verify()
boundary chat_pack_service.py's own verify_chatpack_payment() already
uses) before granting any entitlement, exactly mirroring the proven
mocking pattern test_payment_activity_events.py already established
for that sibling path (monkeypatch RazorpayProvider.verify itself;
never touch/reach real Razorpay).

Entitlement activation itself (modules.subscription.dual_write_adapter.
mirror_subscription_activation -> SubscriptionService/EntitlementWriteService,
"System C") is a separate, already-tested system (Task 15) -- these
tests deliberately monkeypatch mirror_subscription_activation and
observe WHETHER/HOW it was called, rather than re-verifying its own
internal entitlement business rules, keeping this file's scope tightly
bound to what Task 17C actually changed: the verification gate in
front of it.

LOCAL ONLY -- connects exclusively to jyotishasha_local, refuses to run
against anything else. No real Razorpay/network call is ever made --
RazorpayProvider.verify itself is monkeypatched for every
success/failure scenario; the two "missing signature" tests exercise
the REAL RazorpayProvider.verify() (safe -- it fails before any network
call, exactly the same "no network call" property test_payment_
activity_events.py's own equivalent case already relies on). All test
rows are created with dedicated markers and deleted in a finally block,
keyed by their own ids -- never a broad DELETE.
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

    from modules.models_user import AppUser
    from modules.models_subscription import SubscriptionOrder
    from modules.payments.payment_models import (
        PaymentProviderType, PaymentStatus, PaymentVerificationResult,
    )
    from modules.payments.razorpay_provider import RazorpayProvider

    import modules.services.subscription_service as subscription_service_module
    from modules.services.subscription_service import (
        create_subscription_order, verify_subscription_payment,
    )

    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"REFUSING to run against {current_db!r} -- local only."
        )

        created_user_ids = []
        created_order_ids = []
        created_entitlement_profile_ids = []

        def new_user():
            u = AppUser(
                firebase_uid=f"phase17c-test-{uuid.uuid4().hex[:10]}",
                fcm_token=None,
                moon_sign="phase17c-marker",
            )
            db.session.add(u)
            db.session.commit()
            created_user_ids.append(u.id)
            return u.id

        def new_pending_order(user_id, plan_type="monthly", razorpay_order_id=None):
            o = SubscriptionOrder(
                user_id=user_id,
                razorpay_order_id=razorpay_order_id or f"order_17c_{uuid.uuid4().hex[:12]}",
                plan_type=plan_type,
                amount=49,
                status="pending",
            )
            db.session.add(o)
            db.session.commit()
            created_order_ids.append(o.id)
            return o

        # Fake RazorpayProvider.verify() implementations -- SAME shape/
        # convention test_payment_activity_events.py already established.
        def fake_verify_success(self, request):
            return PaymentVerificationResult(
                status=PaymentStatus.VERIFIED, provider=PaymentProviderType.RAZORPAY,
                reference=request.reference, verified=True, message="mocked verified",
            )

        def fake_verify_failed(self, request):
            return PaymentVerificationResult(
                status=PaymentStatus.FAILED, provider=PaymentProviderType.RAZORPAY,
                reference=request.reference, verified=False, message="mocked signature mismatch",
            )

        def fake_verify_raises(self, request):
            raise RuntimeError("simulated RazorpayProvider internal error (mocked, no real network)")

        real_verify = RazorpayProvider.verify

        try:
            # ==========================================================
            print("\n=== A: valid signature -> success, entitlement activation attempted ===")
            # ==========================================================
            user_a = new_user()
            order_a = new_pending_order(user_a)
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_a:
                RazorpayProvider.verify = fake_verify_success
                try:
                    result_a = verify_subscription_payment(order_a.razorpay_order_id, "pay_17c_a", user_a, "sig_a")
                finally:
                    RazorpayProvider.verify = real_verify
            check("A: success == True", result_a.get("success") is True)
            check("A: plan returned matches the order", result_a.get("plan") == "monthly")
            db.session.refresh(order_a)
            check("A: SubscriptionOrder.status == success", order_a.status == "success")
            check("A: SubscriptionOrder.payment_id persisted", order_a.payment_id == "pay_17c_a")
            check("A: SubscriptionOrder.verified_at is set", order_a.verified_at is not None)
            check("A: mirror_subscription_activation WAS called exactly once (entitlement activation attempted)", mock_mirror_a.call_count == 1)
            if mock_mirror_a.call_count == 1:
                _, kwargs_a = mock_mirror_a.call_args
                check("A: mirror called with the correct plan/user", mock_mirror_a.call_args[0][0] == user_a and kwargs_a.get("plan") == "monthly")

            # ==========================================================
            print("\n=== B: invalid signature -> controlled failure, no entitlement ===")
            # ==========================================================
            user_b = new_user()
            order_b = new_pending_order(user_b)
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_b:
                RazorpayProvider.verify = fake_verify_failed
                raised_b = False
                try:
                    try:
                        verify_subscription_payment(order_b.razorpay_order_id, "pay_17c_b", user_b, "bad-sig")
                    except ValueError:
                        raised_b = True
                finally:
                    RazorpayProvider.verify = real_verify
            check("B: ValueError raised (controlled failure)", raised_b)
            db.session.refresh(order_b)
            check("B: SubscriptionOrder.status NOT success (still pending)", order_b.status == "pending")
            check("B: SubscriptionOrder.payment_id NOT persisted", order_b.payment_id is None)
            check("B: mirror_subscription_activation NEVER called (no entitlement)", mock_mirror_b.call_count == 0)

            # ==========================================================
            print("\n=== C: missing signature -> rejected, no entitlement (REAL RazorpayProvider.verify(), no network) ===")
            # ==========================================================
            user_c = new_user()
            order_c = new_pending_order(user_c)
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_c:
                raised_c = False
                try:
                    verify_subscription_payment(order_c.razorpay_order_id, "pay_17c_c", user_c, None)
                except ValueError:
                    raised_c = True
            check("C: ValueError raised for missing signature", raised_c)
            db.session.refresh(order_c)
            check("C: SubscriptionOrder.status NOT success", order_c.status == "pending")
            check("C: mirror_subscription_activation NEVER called", mock_mirror_c.call_count == 0)

            # ==========================================================
            print("\n=== D: mismatched Razorpay order ID -> rejected BEFORE any verification/business effect ===")
            # ==========================================================
            user_d = new_user()
            order_d = new_pending_order(user_d)
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_d:
                RazorpayProvider.verify = fake_verify_success  # would succeed if ever reached -- must NOT be reached
                raised_d = False
                try:
                    try:
                        verify_subscription_payment("some-other-order-id-not-in-db", "pay_17c_d", user_d, "sig_d")
                    except ValueError:
                        raised_d = True
                finally:
                    RazorpayProvider.verify = real_verify
            check("D: ValueError raised (Order not found)", raised_d)
            db.session.refresh(order_d)
            check("D: the REAL order_d row untouched (still pending)", order_d.status == "pending")
            check("D: mirror_subscription_activation NEVER called", mock_mirror_d.call_count == 0)

            # ==========================================================
            print("\n=== E: RazorpayProvider.verify() itself raises -> controlled failure, no entitlement ===")
            # ==========================================================
            user_e = new_user()
            order_e = new_pending_order(user_e)
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_e:
                RazorpayProvider.verify = fake_verify_raises
                raised_e = False
                raised_e_type = None
                try:
                    try:
                        verify_subscription_payment(order_e.razorpay_order_id, "pay_17c_e", user_e, "sig_e")
                    except Exception as exc:
                        raised_e = True
                        raised_e_type = type(exc).__name__
                finally:
                    RazorpayProvider.verify = real_verify
            check("E: an exception propagated (controlled failure -- not silently swallowed)", raised_e)
            check("E: the ORIGINAL exception type propagated (not masked as a generic success)", raised_e_type == "RuntimeError")
            db.session.refresh(order_e)
            check("E: SubscriptionOrder.status NOT success", order_e.status == "pending")
            check("E: mirror_subscription_activation NEVER called", mock_mirror_e.call_count == 0)

            # ==========================================================
            print("\n=== F: duplicate successful callback -> idempotent, no duplicate entitlement effect ===")
            # ==========================================================
            # Reuse order_a (already status=success from Test A).
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_f:
                RazorpayProvider.verify = fake_verify_success
                try:
                    result_f = verify_subscription_payment(order_a.razorpay_order_id, "pay_17c_a", user_a, "sig_a")
                finally:
                    RazorpayProvider.verify = real_verify
            check("F: duplicate call still reports success (idempotent)", result_f.get("success") is True)
            check("F: duplicate call flagged already_processed", result_f.get("already_processed") is True)
            check("F: mirror_subscription_activation NOT called again (no duplicate business effect)", mock_mirror_f.call_count == 0)

            # ==========================================================
            print("\n=== G: payment replay across a DIFFERENT SubscriptionOrder -> must not grant entitlement to it ===")
            # ==========================================================
            user_g = new_user()
            order_g = new_pending_order(user_g)  # a genuinely different order, different razorpay_order_id
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_g:
                RazorpayProvider.verify = fake_verify_success  # would succeed if reached -- must not be reachable via order_g's own id/user with order_a's payment
                raised_g = False
                try:
                    # Attacker attempts to replay order_a's own real (order_id, payment_id) pair,
                    # but scoped to order_g's owning user -- the lookup below can only ever find a
                    # row by (razorpay_order_id, user_id) TOGETHER, so this must fail to find order_g.
                    try:
                        verify_subscription_payment(order_a.razorpay_order_id, "pay_17c_a", user_g, "sig_a")
                    except ValueError:
                        raised_g = True
                finally:
                    RazorpayProvider.verify = real_verify
            check("G: replay against a mismatched order/user combination is rejected", raised_g)
            db.session.refresh(order_g)
            check("G: order_g remains untouched/pending (no entitlement granted to it)", order_g.status == "pending")
            check("G: mirror_subscription_activation NEVER called for order_g", mock_mirror_g.call_count == 0)

            # ==========================================================
            print("\n=== H: wrong user/profile ownership -> rejected ===")
            # ==========================================================
            user_h_owner = new_user()
            user_h_attacker = new_user()
            order_h = new_pending_order(user_h_owner)
            with patch("modules.services.subscription_service.mirror_subscription_activation") as mock_mirror_h:
                RazorpayProvider.verify = fake_verify_success
                raised_h = False
                try:
                    try:
                        # Correct order_id + a plausible payment_id/signature, but the WRONG user_id.
                        verify_subscription_payment(order_h.razorpay_order_id, "pay_17c_h", user_h_attacker, "sig_h")
                    except ValueError:
                        raised_h = True
                finally:
                    RazorpayProvider.verify = real_verify
            check("H: wrong-owner verification attempt rejected", raised_h)
            db.session.refresh(order_h)
            check("H: the real owner's order remains untouched/pending", order_h.status == "pending")
            check("H: mirror_subscription_activation NEVER called", mock_mirror_h.call_count == 0)

            # ==========================================================
            print("\n=== I: create_subscription_order() (order creation) remains unchanged ===")
            # ==========================================================
            # Task 17C fix note: order CREATION itself was never touched by
            # this security fix (only verify_subscription_payment() was) --
            # this test still must not hit real Razorpay, so
            # razorpay_client.order.create is mocked here exactly like
            # test_payment_activity_events.py's own established pattern.
            import config.razorpay_config as razorpay_config_module
            real_client_order_create = razorpay_config_module.razorpay_client.order.create
            fake_razorpay_order_i = {"id": f"order_17c_created_{uuid.uuid4().hex[:12]}", "amount": 53900, "currency": "INR"}
            razorpay_config_module.razorpay_client.order.create = lambda payload: fake_razorpay_order_i
            user_i = new_user()
            try:
                created_dict_i = create_subscription_order(user_i, "yearly")
            finally:
                razorpay_config_module.razorpay_client.order.create = real_client_order_create
            order_i_row = SubscriptionOrder.query.filter_by(user_id=user_i).first()
            created_order_ids.append(order_i_row.id)
            check("I: create_subscription_order still creates a pending SubscriptionOrder (unchanged business behavior)", order_i_row is not None and order_i_row.status == "pending")
            check("I: plan_type/amount unchanged shape", created_dict_i.get("plan_type") == "yearly" and created_dict_i.get("amount") == 539)

            # ==========================================================
            print("\n=== J: financial/business event ordering -- synthesized from A-H above ===")
            # ==========================================================
            # This codebase's website/Razorpay subscription path emits NO
            # activity_events canonical event at all today (confirmed by
            # source inspection -- no record_event/_emit_* call exists
            # anywhere in subscription_service.py, before or after this
            # fix; adding one is explicitly out of this task's scope, see
            # final report Step 10). The equivalent, actually-existing
            # "financial/business success" signals for this path are
            # SubscriptionOrder.status=="success" and the
            # mirror_subscription_activation() call (which is what
            # ultimately drives the real subscription_started/
            # CurrentEntitlement activity, an already-separately-tested
            # system per Task 15). Tests A-H above already prove, together,
            # that NEITHER of those two signals is ever produced except
            # strictly after RazorpayProvider.verify() has returned
            # VERIFIED for the exact order/payment/signature triplet
            # bound to the correct, owning SubscriptionOrder -- this
            # check states that conclusion explicitly, synthesized from
            # the evidence already gathered above, rather than
            # re-deriving it.
            ordering_proven = (
                mock_mirror_a.call_count == 1  # A: success -> activation attempted, exactly once
                and mock_mirror_b.call_count == 0  # B: invalid signature -> never
                and mock_mirror_c.call_count == 0  # C: missing signature -> never
                and mock_mirror_d.call_count == 0  # D: mismatched order id -> never
                and mock_mirror_e.call_count == 0  # E: provider exception -> never
                and mock_mirror_f.call_count == 0  # F: duplicate success -> never again
                and mock_mirror_g.call_count == 0  # G: cross-order replay -> never
                and mock_mirror_h.call_count == 0  # H: wrong ownership -> never
            )
            check("J: entitlement-activation signal occurs ONLY after successful verification, across every scenario tested", ordering_proven)

        finally:
            # ----------------------------------------------------------
            # Cleanup -- precise, per-row, never a broad DELETE.
            # ----------------------------------------------------------
            for oid in dict.fromkeys(created_order_ids):
                db.session.execute(text("DELETE FROM subscription_orders WHERE id = :id"), {"id": oid})
            db.session.commit()

            for uid in dict.fromkeys(created_user_ids):
                db.session.execute(text("DELETE FROM app_users WHERE id = :id"), {"id": uid})
            db.session.commit()

            remaining_orders = SubscriptionOrder.query.filter(SubscriptionOrder.id.in_(created_order_ids or [-1])).count()
            check("cleanup: all Task-17C SubscriptionOrder fixtures removed", remaining_orders == 0)

            remaining_users = AppUser.query.filter(AppUser.id.in_(created_user_ids or [-1])).count()
            check("cleanup: all Task-17C AppUser fixtures removed", remaining_users == 0)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
