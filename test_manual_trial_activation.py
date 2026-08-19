"""
test_manual_trial_activation.py
----------------------------------
Manual Trial Activation -- proves automatic trial provisioning was
removed from AppUser-creation paths, and that the new
POST /api/profile/activate-trial endpoint is the sole, server-
authoritative, one-time way a 7-day trial can start.

Covers:
  A. register_or_update_user() creates a brand-new AppUser WITHOUT
     starting a trial (no CurrentEntitlement row at all).
  B. POST /api/users/update-fcm creates a brand-new AppUser (via the
     real HTTP route, real JWT/Firebase-token flow, Firebase verify
     monkeypatched) WITHOUT starting a trial.
  C. POST /api/user/bootstrap and modules/user_service.py::
     register_or_update_user() both call the exact same
     get_or_create_app_user() primitive (A) already proves has zero
     trial side effect, and neither file calls
     provision_trial_for_new_profile() at all any more -- verified
     directly against the live source text below (not just recalled),
     since exercising bootstrap's own real Kundali calculation is out
     of scope for this fast, DB-focused test file.
  D. GET /api/profile/subscription-info returns trial_available=true
     for a brand-new, never-provisioned profile.
  E. POST /api/profile/activate-trial, first call: creates exactly one
     7-day trial, unlocks all 6 SUBSCRIPTION_SECTIONS, subscription-info
     now reports membership_state=TRIAL and trial_available=false.
  F. Repeated activation (same profile, same session) is idempotent --
     does NOT extend/restart trial_expires_at, returns
     activated=false/reason=already_active.
  G. A previously-claimed, now-EXPIRED trial cannot activate again --
     rejected with reason=trial_already_used, no second
     CurrentEntitlement/SubscriptionEvent row.
  H. An ACTIVE paid subscriber cannot receive a trial via this endpoint
     -- rejected with reason=already_subscribed, subscription_expires_at
     untouched.
  I. Concurrent/"double" activation (two back-to-back calls with no
     eligibility check bypassed) cannot create two trial starts --
     exactly one SubscriptionEvent(event_type="TRIAL_STARTED") row for
     the profile.
  J. No auth / unresolvable profile -> clean 401/404, not a crash.
  K. GET /api/subscription (legacy route, real URL is doubled to
     /api/subscription/api/subscription per its own file comment) no
     longer mirror-starts a System C trial on first call for a new
     profile -- discovered as a 4th auto-provisioning path beyond the
     3 originally audited (bootstrap/update-fcm/register-or-update),
     via modules/subscription/dual_write_adapter.py::mirror_trial_start().

Uses the LOCAL scratch Postgres DB ONLY. No production access.
"""

import inspect
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"
os.environ["DATABASE_URL"] = LOCAL_DB_URL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402

from modules.auth.models import User  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
from modules.models_premium_subscription import CurrentEntitlement  # noqa: E402
from modules.entitlement.subscription_sections import SUBSCRIPTION_SECTIONS  # noqa: E402

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


# Distinct id range, not used by any other test_*.py fixture in this repo.
PROFILE_IDS = list(range(987001, 987012))
USER_IDS = list(range(987101, 987112))


def cleanup():
    CurrentEntitlement.query.filter(
        CurrentEntitlement.profile_id.in_(PROFILE_IDS),
    ).delete(synchronize_session=False)
    db.session.execute(
        text("DELETE FROM subscription_events WHERE profile_id = ANY(:ids)"),
        {"ids": PROFILE_IDS},
    )
    # Legacy Subscription rows (modules/subscription/models.py) FK to
    # users.id -- test K's GET /api/subscription call still creates one
    # of these (unchanged, only its trial-mirror was removed), so it
    # must be purged before the users rows below.
    db.session.execute(
        text("DELETE FROM subscriptions WHERE user_id = ANY(:ids)"),
        {"ids": USER_IDS},
    )
    AppUser.query.filter(AppUser.id.in_(PROFILE_IDS)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(USER_IDS)).delete(synchronize_session=False)
    db.session.commit()


def link_user_to_profile(user_id, profile_id, firebase_uid):
    """Same shape test_alerts_dashboard_api.py's own `link()` helper
    uses -- a `users` row and an `app_users` row sharing one
    firebase_uid, which resolve_profile_id_from_account_user_id()
    joins on."""
    db.session.add(User(id=user_id, email=f"trial-test-{user_id}@example.com",
                         provider="password", firebase_uid=firebase_uid))
    if db.session.get(AppUser, profile_id) is None:
        db.session.add(AppUser(id=profile_id, firebase_uid=firebase_uid))
    else:
        db.session.get(AppUser, profile_id).firebase_uid = firebase_uid
    db.session.commit()


def bearer(user_id):
    with app.app_context():
        token = create_access_token(identity=str(user_id))
    return {"Authorization": f"Bearer {token}"}


def main():
    with app.app_context():
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        print(f"Connected to database: {current_db}")
        assert current_db == "jyotishasha_local", (
            f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        )

        cleanup()
        client = app.test_client()

        # ==========================================================
        print("=== A: register_or_update_user() creates AppUser WITHOUT starting a trial ===")
        # ==========================================================
        from modules.user_service import register_or_update_user

        fb_a = "fb-manual-trial-a"
        result_a = register_or_update_user({
            "firebase_uid": fb_a, "name": "Trial Test A", "email": "a@example.com",
        })
        check("A: AppUser was created", result_a is not None and result_a.id is not None)
        row_a = CurrentEntitlement.query.filter_by(profile_id=result_a.id).first()
        check("A: NO CurrentEntitlement row exists for the new profile", row_a is None)
        PROFILE_IDS.append(result_a.id)  # ensure cleanup covers the real assigned id

        # ==========================================================
        print("\n=== B: POST /api/users/update-fcm creates AppUser WITHOUT starting a trial ===")
        # ==========================================================
        import modules.auth.routes_profile as routes_profile_module

        class FakeFirebaseVerification:
            def __init__(self):
                self.calls = []

            def __call__(self, token):
                self.calls.append(token)
                return {"uid": token}  # token IS the fake uid, for simplicity

        fake_verify_b = FakeFirebaseVerification()
        real_verify = routes_profile_module.firebase_auth.verify_id_token
        routes_profile_module.firebase_auth.verify_id_token = fake_verify_b

        fb_b = "fb-manual-trial-b"
        try:
            resp_b = client.post(
                "/api/users/update-fcm",
                json={"fcm_token": "tok-b"},
                headers={"Authorization": f"Bearer {fb_b}"},
            )
        finally:
            routes_profile_module.firebase_auth.verify_id_token = real_verify

        check("B: update-fcm returned 200", resp_b.status_code == 200)
        app_user_b = AppUser.query.filter_by(firebase_uid=fb_b).first()
        check("B: AppUser was created", app_user_b is not None)
        row_b = CurrentEntitlement.query.filter_by(profile_id=app_user_b.id).first() if app_user_b else None
        check("B: NO CurrentEntitlement row exists for the new profile", row_b is None)
        if app_user_b:
            PROFILE_IDS.append(app_user_b.id)

        # ==========================================================
        print("\n=== C: bootstrap + register-or-update no longer call provision_trial_for_new_profile() ===")
        # ==========================================================
        # (A) above already proves register_or_update_user() itself has
        # zero trial side effect at the DB level. This additionally
        # verifies, directly against the live source, that neither call
        # site invokes the old auto-provisioning helper any more -- the
        # exact code-level guarantee requirement 8 asks for, without
        # exercising bootstrap's own real Kundali calculation here.
        import routes.routes_profile_bootstrap as bootstrap_module
        bootstrap_src = inspect.getsource(bootstrap_module.bootstrap_user_profile)
        check(
            "C: routes_profile_bootstrap.bootstrap_user_profile() does not call "
            "provision_trial_for_new_profile()",
            "provision_trial_for_new_profile(" not in bootstrap_src,
        )
        register_src = inspect.getsource(__import__(
            "modules.user_service", fromlist=["register_or_update_user"],
        ).register_or_update_user)
        check(
            "C: user_service.register_or_update_user() does not call "
            "provision_trial_for_new_profile()",
            "provision_trial_for_new_profile(" not in register_src,
        )
        update_fcm_src = inspect.getsource(routes_profile_module.update_fcm_token)
        check(
            "C: routes_profile.update_fcm_token() does not call "
            "provision_trial_for_new_profile()",
            "provision_trial_for_new_profile(" not in update_fcm_src,
        )

        # ==========================================================
        print("\n=== D: GET /api/profile/subscription-info reports trial_available=true for a brand-new profile ===")
        # ==========================================================
        p_d, u_d = 987001, 987101
        link_user_to_profile(u_d, p_d, "fb-manual-trial-d")
        resp_d = client.get("/api/profile/subscription-info", headers=bearer(u_d))
        body_d = resp_d.get_json()
        check("D: HTTP 200", resp_d.status_code == 200)
        check("D: membership_state == NONE", body_d.get("membership_state") == "NONE")
        check("D: trial_available == true", body_d.get("trial_available") is True)

        # ==========================================================
        print("\n=== E: first activation creates exactly one 7-day trial, unlocks all 6 sections ===")
        # ==========================================================
        before = datetime.utcnow()
        resp_e = client.post("/api/profile/activate-trial", headers=bearer(u_d))
        after = datetime.utcnow()
        body_e = resp_e.get_json()

        check("E: HTTP 200", resp_e.status_code == 200)
        check("E: success == true", body_e.get("success") is True)
        check("E: activated == true", body_e.get("activated") is True)
        check("E: membership_state == TRIAL", body_e.get("membership_state") == "TRIAL")
        check("E: trial_available == false now", body_e.get("trial_available") is False)
        check(
            f"E: all 6 sections accessible (got {body_e.get('accessible_segments')})",
            set(body_e.get("accessible_segments") or []) == set(SUBSCRIPTION_SECTIONS)
            and len(SUBSCRIPTION_SECTIONS) == 6,
        )

        row_e = CurrentEntitlement.query.filter_by(profile_id=p_d).first()
        check("E: CurrentEntitlement row created", row_e is not None)
        check(
            "E: trial_started_at within this call's window",
            row_e is not None and before <= row_e.trial_started_at <= after,
        )
        check(
            "E: trial_expires_at - trial_started_at == 7 days",
            row_e is not None and (row_e.trial_expires_at - row_e.trial_started_at) == timedelta(days=7),
        )

        # subscription-info reflects it too, end to end
        resp_e2 = client.get("/api/profile/subscription-info", headers=bearer(u_d))
        body_e2 = resp_e2.get_json()
        check("E: subscription-info now shows membership_state=TRIAL", body_e2.get("membership_state") == "TRIAL")
        check("E: subscription-info now shows trial_available=false", body_e2.get("trial_available") is False)

        # ==========================================================
        print("\n=== F: repeated activation is idempotent -- never extends/restarts ===")
        # ==========================================================
        original_started_at = row_e.trial_started_at
        original_expires_at = row_e.trial_expires_at

        resp_f = client.post("/api/profile/activate-trial", headers=bearer(u_d))
        body_f = resp_f.get_json()
        db.session.refresh(row_e)

        check("F: HTTP 200 (not an error)", resp_f.status_code == 200)
        check("F: activated == false", body_f.get("activated") is False)
        check("F: reason == already_active", body_f.get("reason") == "already_active")
        check("F: trial_started_at unchanged", row_e.trial_started_at == original_started_at)
        check("F: trial_expires_at unchanged (no extension)", row_e.trial_expires_at == original_expires_at)

        # ==========================================================
        print("\n=== G: a previously-claimed, now-EXPIRED trial cannot activate again ===")
        # ==========================================================
        p_g, u_g = 987002, 987102
        link_user_to_profile(u_g, p_g, "fb-manual-trial-g")
        # Directly provision + backdate an already-expired trial (same
        # technique the 7-day-duration test suite already established)
        # -- simulates a profile whose trial genuinely ran its course.
        from modules.subscription.subscription_service import SubscriptionService
        SubscriptionService().start_trial(p_g)
        row_g = CurrentEntitlement.query.filter_by(profile_id=p_g).first()
        row_g.trial_started_at = datetime.utcnow() - timedelta(days=10)
        row_g.trial_expires_at = row_g.trial_started_at + timedelta(days=7)
        db.session.commit()

        events_before_g = db.session.execute(
            text("SELECT COUNT(*) FROM subscription_events WHERE profile_id = :p AND event_type = 'TRIAL_STARTED'"),
            {"p": p_g},
        ).scalar()

        resp_g = client.post("/api/profile/activate-trial", headers=bearer(u_g))
        body_g = resp_g.get_json()

        check("G: HTTP 400 (rejected)", resp_g.status_code == 400)
        check("G: success == false", body_g.get("success") is False)
        check("G: reason == trial_already_used", body_g.get("reason") == "trial_already_used")
        events_after_g = db.session.execute(
            text("SELECT COUNT(*) FROM subscription_events WHERE profile_id = :p AND event_type = 'TRIAL_STARTED'"),
            {"p": p_g},
        ).scalar()
        check("G: no new TRIAL_STARTED event was recorded", events_after_g == events_before_g)

        # ==========================================================
        print("\n=== H: an ACTIVE paid subscriber cannot receive a trial ===")
        # ==========================================================
        p_h, u_h = 987003, 987103
        link_user_to_profile(u_h, p_h, "fb-manual-trial-h")
        expires_at_h = datetime.utcnow() + timedelta(days=30)
        SubscriptionService().activate_subscription(
            profile_id=p_h, plan="PRIME_PLUS_MONTHLY", selected_segment=None,
            expires_at=expires_at_h,
        )

        resp_h = client.post("/api/profile/activate-trial", headers=bearer(u_h))
        body_h = resp_h.get_json()
        row_h = CurrentEntitlement.query.filter_by(profile_id=p_h).first()

        check("H: HTTP 400 (rejected)", resp_h.status_code == 400)
        check("H: reason == already_subscribed", body_h.get("reason") == "already_subscribed")
        check("H: status is still ACTIVE", row_h.status == "ACTIVE")
        check("H: subscription_expires_at untouched", row_h.subscription_expires_at == expires_at_h)
        check("H: trial_started_at was never set", row_h.trial_started_at is None)

        # ==========================================================
        print("\n=== I: two back-to-back activation calls cannot create two trial starts ===")
        # ==========================================================
        p_i, u_i = 987004, 987104
        link_user_to_profile(u_i, p_i, "fb-manual-trial-i")

        resp_i1 = client.post("/api/profile/activate-trial", headers=bearer(u_i))
        resp_i2 = client.post("/api/profile/activate-trial", headers=bearer(u_i))
        body_i1, body_i2 = resp_i1.get_json(), resp_i2.get_json()

        check("I: first call activated", body_i1.get("activated") is True)
        check("I: second call did NOT activate", body_i2.get("activated") is False)
        event_count_i = db.session.execute(
            text("SELECT COUNT(*) FROM subscription_events WHERE profile_id = :p AND event_type = 'TRIAL_STARTED'"),
            {"p": p_i},
        ).scalar()
        check("I: exactly ONE TRIAL_STARTED event for this profile", event_count_i == 1)
        entitlement_rows_i = CurrentEntitlement.query.filter_by(profile_id=p_i).count()
        check("I: exactly ONE CurrentEntitlement row for this profile", entitlement_rows_i == 1)

        # ==========================================================
        print("\n=== J: no auth / unresolvable profile -> clean rejection, not a crash ===")
        # ==========================================================
        resp_j1 = client.post("/api/profile/activate-trial")
        check("J: no Authorization header -> 401", resp_j1.status_code == 401)

        u_j_orphan = 987105
        # A JWT for a user_id that resolves to no profile at all
        # (no User row, no AppUser row created for it).
        resp_j2 = client.post("/api/profile/activate-trial", headers=bearer(u_j_orphan))
        body_j2 = resp_j2.get_json()
        check("J: unresolvable profile -> 404", resp_j2.status_code == 404)
        check("J: reason == no_profile", body_j2.get("reason") == "no_profile")

        # ==========================================================
        print("\n=== K: GET /api/subscription no longer auto-mirror-starts a trial ===")
        # ==========================================================
        p_k, u_k = 987006, 987106
        link_user_to_profile(u_k, p_k, "fb-manual-trial-k")

        resp_k = client.get(
            "/api/subscription/api/subscription",  # doubled path -- see routes.py's own comment
            headers=bearer(u_k),
        )
        check("K: HTTP 200 (route itself still works)", resp_k.status_code == 200)
        row_k = CurrentEntitlement.query.filter_by(profile_id=p_k).first()
        check("K: NO CurrentEntitlement row was mirror-created", row_k is None)

        cleanup()

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
