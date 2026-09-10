"""
test_saved_audience_v2.py
------------------------------
Saved Audience V2 -- explicit FIXED audience type (exact users.id
membership, immutable once created) alongside the existing DYNAMIC/
criteria-based type. See modules/models_saved_audience.py's own module
docstring for the full product rationale.

Covers:
  FIXED -- create with 1/many member_user_ids, exact-membership preview,
  duplicate-id dedup, nonexistent-id fail-closed (no partial row),
  account-deletion CASCADE shrinking membership, NEVER All Users under
  any circumstance (empty membership included), recipient eligibility
  exclusions still apply, and a real Send Now dispatch uses fixed
  membership correctly (approved_criteria snapshot has type=fixed).

  DELETE -- soft-deactivate for both types; deactivated audiences drop
  out of the active list; deactivating an audience already referenced by
  an approved/frozen campaign never touches that campaign's own
  independent NotificationCampaignExecution.approved_criteria snapshot.

Run via scripts/l3_local_verify.py (same convention as
test_notification_campaign_execution.py) or directly with DATABASE_URL
set. LOCAL ONLY -- refuses to run against anything but jyotishasha_local.
"""
import os
import sys
import unittest
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault("DATABASE_URL", "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask_jwt_extended import create_access_token  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402
from modules.auth.models import User  # noqa: E402
from modules.models_user import AppUser  # noqa: E402
from modules.models_saved_audience import SavedAudience, SavedAudienceMember  # noqa: E402
from modules.services.saved_audience_criteria import CriteriaValidationError  # noqa: E402
from modules.services.saved_audience_service import (  # noqa: E402
    create_audience, update_audience, deactivate_audience, get_audience,
    list_audiences, preview_audience,
)
from notifications.saved_audience_recipient_resolver import (  # noqa: E402
    resolve_saved_audience_recipients, RecipientResolutionError,
)
from notifications.campaign_models import NotificationCampaign  # noqa: E402
from notifications.campaign_execution_models import (  # noqa: E402
    NotificationCampaignExecution, NotificationCampaignDelivery, NotificationCampaignAttempt,
    NotificationSendNowRequest,
)
from notifications.campaign_bell_models import NotificationCampaignBellItem  # noqa: E402


def iso(dt):
    return dt.isoformat()


class V2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = app.app_context(); cls.context.push()
        current_db = db.session.execute(text("SELECT current_database()")).scalar()
        assert current_db == "jyotishasha_local", f"Refusing to run -- expected jyotishasha_local, got {current_db!r}"
        cls.client = app.test_client()
        cls.base = 9979000
        cls.ids = list(range(cls.base, cls.base + 8))
        assert not User.query.filter(User.id.in_(cls.ids)).first()
        assert not AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).first()
        for offset, user_id in enumerate(cls.ids):
            uid = f"v2-fixed-{offset}"
            db.session.add(User(id=user_id, firebase_uid=uid, name=uid, email=f"{uid}@example.invalid"))
            # offset 6 has NO AppUser at all (missing_profile exclusion),
            # offset 7 has an AppUser with NO fcm_token (missing_token).
            if offset == 6:
                continue
            token = None if offset == 7 else f"v2-token-{offset}"
            db.session.add(AppUser(id=user_id + 100, firebase_uid=uid, fcm_token=token, lang="en", moon_sign="Aries"))
        db.session.commit()
        cls.audiences = []
        cls.campaigns = []
        os.environ["ADMIN_USER_IDS"] = str(cls.ids[0])
        cls.admin = {"Authorization": "Bearer " + create_access_token(identity=str(cls.ids[0]))}

    @classmethod
    def tearDownClass(cls):
        db.session.rollback()
        execution_ids = [e.id for e in NotificationCampaignExecution.query.filter(NotificationCampaignExecution.campaign_id.in_(cls.campaigns)).all()]
        delivery_ids = [d.id for d in NotificationCampaignDelivery.query.filter(NotificationCampaignDelivery.execution_id.in_(execution_ids)).all()]
        NotificationCampaignAttempt.query.filter(NotificationCampaignAttempt.delivery_id.in_(delivery_ids)).delete(synchronize_session=False)
        NotificationCampaignDelivery.query.filter(NotificationCampaignDelivery.id.in_(delivery_ids)).delete(synchronize_session=False)
        NotificationCampaignBellItem.query.filter(NotificationCampaignBellItem.execution_id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationSendNowRequest.query.filter(NotificationSendNowRequest.campaign_id.in_(cls.campaigns)).delete(synchronize_session=False)
        NotificationCampaignExecution.query.filter(NotificationCampaignExecution.id.in_(execution_ids)).delete(synchronize_session=False)
        NotificationCampaign.query.filter(NotificationCampaign.id.in_(cls.campaigns)).delete(synchronize_session=False)
        SavedAudienceMember.query.filter(SavedAudienceMember.saved_audience_id.in_(cls.audiences)).delete(synchronize_session=False)
        SavedAudience.query.filter(SavedAudience.id.in_(cls.audiences)).delete(synchronize_session=False)
        AppUser.query.filter(AppUser.id.between(cls.base + 100, cls.base + 199)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(cls.ids)).delete(synchronize_session=False)
        db.session.commit(); db.session.remove(); cls.context.pop()

    def _fixed(self, member_ids, name="V2 fixed"):
        a = create_audience(name=name, audience_type="fixed", member_user_ids=member_ids)
        self.audiences.append(a.id)
        return a

    def make_draft(self, audience_id, **overrides):
        payload = dict(title="Hello V2", body="Body text", audience_mode="SAVED_AUDIENCE",
                        saved_audience_id=audience_id, action={"type": "NONE", "target": None, "parameters": {}})
        payload.update(overrides)
        response = self.client.post("/admin/api/notifications", json=payload, headers=self.admin)
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.campaigns.append(body["id"])
        return body

    def send_now(self, campaign_id, matched, eligible, **overrides):
        payload = dict(revision=1, idempotency_key="key-" + campaign_id,
                        baseline={"generated_at": iso(datetime.now(timezone.utc)), "matched_user_count": matched, "eligible_recipient_count": eligible})
        payload.update(overrides)
        return self.client.post(f"/admin/api/notifications/{campaign_id}/send-now", json=payload, headers=self.admin)

    # ================= FIXED: creation + membership =================

    def test_fixed_one_user_matched_one(self):
        a = self._fixed([self.ids[0]])
        self.assertEqual(a.audience_type, "fixed")
        self.assertIsNone(a.criteria)
        result = preview_audience(a.id)
        self.assertEqual(result["member_count"], 1)
        self.assertEqual({u["id"] for u in result["users"]}, {self.ids[0]})

    def test_fixed_multiple_users_exact_ids(self):
        selected = [self.ids[0], self.ids[1], self.ids[2]]
        a = self._fixed(selected)
        result = preview_audience(a.id, page_size=200)
        self.assertEqual(result["member_count"], 3)
        self.assertEqual({u["id"] for u in result["users"]}, set(selected))

    def test_fixed_duplicate_ids_deduped_safely(self):
        a = self._fixed([self.ids[0], self.ids[0], self.ids[1], self.ids[0]])
        rows = SavedAudienceMember.query.filter_by(saved_audience_id=a.id).all()
        self.assertEqual(sorted(r.user_id for r in rows), sorted({self.ids[0], self.ids[1]}))
        self.assertEqual(len(rows), 2, "no duplicate member rows despite the id being sent 3 times")

    def test_fixed_invalid_nonexistent_id_fails_closed(self):
        before = SavedAudience.query.count()
        with self.assertRaises(CriteriaValidationError) as raised:
            create_audience(name="Should Fail", audience_type="fixed", member_user_ids=[self.ids[0], 999_999_999])
        self.assertEqual(raised.exception.code, "invalid_member_ids")
        self.assertEqual(SavedAudience.query.count(), before, "no partial row was created")
        self.assertIsNone(SavedAudience.query.filter_by(name="Should Fail").first())

    def test_fixed_structural_invalid_member_ids_rejected(self):
        for bad in ([], ["not-an-int"], [0], [-1], [True], "not-a-list", None):
            with self.assertRaises(CriteriaValidationError):
                create_audience(name="Should Fail 2", audience_type="fixed", member_user_ids=bad)

    def test_fixed_rejects_criteria_and_dynamic_rejects_member_ids(self):
        with self.assertRaises(CriteriaValidationError):
            create_audience(name="x", audience_type="fixed", criteria={"version": 1, "filters": {}}, member_user_ids=[self.ids[0]])
        with self.assertRaises(CriteriaValidationError):
            create_audience(name="x", audience_type="dynamic", criteria={"version": 1, "filters": {}}, member_user_ids=[self.ids[0]])

    def test_fixed_update_criteria_rejected(self):
        a = self._fixed([self.ids[0]])
        with self.assertRaises(CriteriaValidationError):
            update_audience(a.id, criteria={"version": 1, "filters": {}})

    # ================= FIXED: deleted/inactive identity =================

    def test_fixed_member_removed_on_account_deletion_cascade(self):
        extra_id = self.base + 900
        db.session.add(User(id=extra_id, firebase_uid="v2-cascade-victim", name="cascade", email="cascade@example.invalid"))
        db.session.commit()
        a = self._fixed([self.ids[0], extra_id])
        self.assertEqual(preview_audience(a.id)["member_count"], 2)

        db.session.delete(User.query.get(extra_id))
        db.session.commit()

        self.assertIsNone(SavedAudienceMember.query.filter_by(saved_audience_id=a.id, user_id=extra_id).first(),
                           "member row auto-removed by ON DELETE CASCADE")
        result = preview_audience(a.id)
        self.assertEqual(result["member_count"], 1)
        self.assertEqual({u["id"] for u in result["users"]}, {self.ids[0]})

    # ================= FIXED: never All Users =================

    def test_fixed_never_all_users_even_when_empty(self):
        extra_id = self.base + 901
        db.session.add(User(id=extra_id, firebase_uid="v2-empty-victim", name="empty", email="empty@example.invalid"))
        db.session.commit()
        a = self._fixed([extra_id])
        resolution = resolve_saved_audience_recipients(a.id)
        self.assertFalse(resolution.is_all_users)
        self.assertEqual(resolution.matched_user_count, 1)

        # Now shrink membership to genuinely zero (the only way possible --
        # deleting the sole member's account) and confirm STILL not All Users.
        db.session.delete(User.query.get(extra_id))
        db.session.commit()
        resolution = resolve_saved_audience_recipients(a.id)
        self.assertFalse(resolution.is_all_users, "an empty fixed audience must never be reported as All Users")
        self.assertEqual(resolution.matched_user_count, 0)
        self.assertEqual(resolution.eligible_recipient_count, 0)

    # ================= FIXED: recipient eligibility =================

    def test_fixed_recipient_eligibility_exclusions_still_apply(self):
        # ids[0] has a real token (eligible); ids[6] has no AppUser at
        # all (missing_profile); ids[7] has an AppUser with no token
        # (missing_token).
        a = self._fixed([self.ids[0], self.ids[6], self.ids[7]])
        resolution = resolve_saved_audience_recipients(a.id)
        self.assertEqual(resolution.matched_user_count, 3)
        self.assertEqual(resolution.eligible_recipient_count, 1)
        counts = dict(resolution.exclusion_counts)
        self.assertEqual(counts["missing_profile"], 1)
        self.assertEqual(counts["missing_token"], 1)

    # ================= FIXED: Composer preview + Campaign dispatch =================

    def test_fixed_campaign_dispatch_uses_fixed_membership(self):
        a = self._fixed([self.ids[0], self.ids[1]], name="V2 dispatch fixed")
        resolution = resolve_saved_audience_recipients(a.id)
        self.assertEqual(resolution.matched_user_count, 2)
        self.assertEqual(resolution.eligible_recipient_count, 2)

        draft = self.make_draft(a.id)
        response = self.send_now(draft["id"], matched=2, eligible=2)
        self.assertEqual(response.status_code, 202, response.get_json())
        body = response.get_json()
        self.assertEqual(body["state"], "FROZEN")
        self.assertEqual(body["target_count"], 2)
        self.assertFalse(body["all_users_confirmed"])

        execution = NotificationCampaignExecution.query.filter_by(campaign_id=draft["id"]).first()
        self.assertEqual(execution.approved_criteria.get("type"), "fixed")
        self.assertEqual(sorted(execution.approved_criteria.get("user_ids")), sorted([self.ids[0], self.ids[1]]))
        self.assertEqual(execution.approved_saved_audience_id, a.id)

    # ================= DYNAMIC: fail-closed on malformed criteria =================

    def test_dynamic_malformed_criteria_blocks_save_never_persists_empty(self):
        before = SavedAudience.query.count()
        with self.assertRaises(CriteriaValidationError):
            create_audience(name="Should Fail 3", criteria={"version": 1, "filters": {"age_min": "not-an-int"}})
        self.assertEqual(SavedAudience.query.count(), before)
        self.assertIsNone(SavedAudience.query.filter_by(name="Should Fail 3").first())

    # ================= DELETE / deactivate safety =================

    def test_delete_unused_fixed_audience_deactivates_and_drops_from_active_list(self):
        a = self._fixed([self.ids[0]], name="V2 delete-unused-fixed")
        deactivate_audience(a.id)
        refreshed = get_audience(a.id)
        self.assertFalse(refreshed.is_active)
        active_ids = {row.id for row in list_audiences(is_active=True)}
        self.assertNotIn(a.id, active_ids)
        # Preview still works (read-only inspection remains allowed, same
        # convention as an inactive DYNAMIC audience).
        self.assertEqual(preview_audience(a.id)["member_count"], 1)

    def test_delete_referenced_by_approved_campaign_preserves_history(self):
        a = self._fixed([self.ids[0], self.ids[1]], name="V2 delete-approved-fixed")
        draft = self.make_draft(a.id)
        response = self.send_now(draft["id"], matched=2, eligible=2)
        self.assertEqual(response.status_code, 202)
        execution = NotificationCampaignExecution.query.filter_by(campaign_id=draft["id"]).first()
        approved_snapshot_before = dict(execution.approved_criteria)

        # Deactivate the now-approved-and-referenced audience -- must
        # succeed (soft-delete is always safe) and must NOT touch the
        # execution's own independent, already-frozen snapshot.
        deactivate_audience(a.id)
        self.assertFalse(get_audience(a.id).is_active)

        db.session.refresh(execution)
        self.assertEqual(dict(execution.approved_criteria), approved_snapshot_before,
                          "deactivating the SavedAudience must never mutate an already-frozen execution snapshot")
        self.assertEqual(execution.approved_saved_audience_id, a.id)

        active_ids = {row.id for row in list_audiences(is_active=True)}
        self.assertNotIn(a.id, active_ids, "deactivated audience must not be selectable for NEW campaigns")


if __name__ == "__main__":
    unittest.main(verbosity=2)
