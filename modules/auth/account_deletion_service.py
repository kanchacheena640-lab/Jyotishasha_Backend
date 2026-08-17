# modules/auth/account_deletion_service.py

"""
Account Deletion Service -- D1 (Backend Deletion Service only).

Implements the D0.1 Design Lock's exact DELETE / RETAIN / ANONYMIZE
policy against the local database. This file owns ONLY the database
side of account deletion -- it never touches Firebase Auth, Firestore,
or any HTTP layer (those are D2/D3, explicitly out of scope here).

==================================================
IDENTITY -- NEVER COLLAPSED (see D0.1 / Phase 0 identity mapping)
==================================================
Two separate identity tables, joined only by `firebase_uid`:
- `users` (modules/auth/models.py::User) -- the login/account identity.
  `firebase_uid` is UNIQUE, indexed.
- `app_users` (modules/models_user.py::AppUser) -- the astrology/
  business/profile identity. `firebase_uid` has NO unique constraint
  (verified directly against the model AND against every migration --
  no migration ever added one). This service NEVER assumes exactly one
  AppUser row per firebase_uid -- resolve_firebase_identity() below
  always returns a LIST of profile_ids, never a single value.

`users.id` and `app_users.id` are always kept in separate fields
throughout this file -- never merged into one "user id" concept.

==================================================
GATE 1 FINDING (documented, not silently worked around)
==================================================
The D0.1 audit's own source material (Phase 0) read model definitions
from `modules/models_notification.py` (UserNotification) and the
root-level `models_notification_log.py` (NotificationLog). Re-verifying
against current code for this phase found those two files are NEVER
imported anywhere in the live application -- the actual, live
`user_notifications`/`notification_logs` tables are defined in
`notifications/notification_models.py` (imported throughout
services/event_scheduler.py, services/attention_policy.py,
modules/alerts/persistence_repository.py, and every test in this
repo). Table names, columns, and the `user_id`-is-really-`app_users.id`
convention are IDENTICAL between the two definitions -- only the
Python import path differed. This file imports from the live,
actually-used module (`notifications.notification_models`). This does
NOT change D0.1's DELETE/RETAIN/ANONYMIZE policy for these two tables
in any way; it corrects a documentation/implementation-path detail
only, exactly the class of thing Gate 1 exists to catch.

==================================================
POLICY SUMMARY (D0.1)
==================================================
Personal-data child tables -- ALWAYS deleted, unconditionally:
    UserDashaTimeline, AlertMicroEvent, AIReport, UserNotification,
    NotificationLog, DailyPersonalizedCache, FreeDailyQuestion.

Financial-adjacent tables -- NEVER deleted, NEVER field-modified:
    CurrentEntitlement, SubscriptionEvent, ChatPack, AskNowOrder,
    SubscriptionOrder. (SubscriptionPurchaseMapping is the one
    exception -- see below.)

`AppUser` (the profile) itself:
    - If NO financial-adjacent row exists for this profile_id ->
      hard DELETE the row (its personal-data children are already gone
      by this point, so nothing still references it).
    - If ANY financial-adjacent row exists -> ANONYMIZE in place
      (personal fields nulled, subscription/asknow_tokens reset to
      defaults) so every retained financial row's FK/link target keeps
      existing. `firebase_uid` is deliberately KEPT -- D0.1 designates
      it the pending-cleanup marker for the later Firebase-side
      deletion step (D3), not this phase's job to clear.

`SubscriptionPurchaseMapping.user_id` (optional, nullable, FK to
users.id, NOT required for resolution per its own model docstring) is
set to NULL. Its `profile_id` (the real resolution key, FK to
app_users.id) is never touched.

Legacy System-A `Subscription` (FK to users.id, nullable=False) rows
for this identity are deleted outright -- unlike SubscriptionEvent,
this is a mutable "current state" row, not an append-only audit trail,
and the system is already slated for full removal elsewhere. Confirmed
empty in production as of the last migration audit; this is a
defensive rule, not a live concern.

`users` row: hard DELETED once the two steps above have run.

Nothing else (ProcessedPayment, ProcessedSubscriptionEvent, Order,
Subscription's own audit value) is touched by this file at all -- they
carry no per-profile linkage this service could safely act on (see
D0.1 §1/§4), and are retained by simply never being queried here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from extensions import db

from modules.auth.models import User
from modules.models_user import AppUser, UserDashaTimeline
from modules.models_premium_subscription import CurrentEntitlement, SubscriptionEvent
from modules.models_subscription_purchase_mapping import SubscriptionPurchaseMapping
from modules.subscription.models import Subscription
from modules.models_chat_pack import ChatPack
from modules.models_asknow import AskNowOrder
from modules.models_subscription import SubscriptionOrder
from modules.models_ai_reports import AIReport
from modules.alerts.persistence_models import AlertMicroEvent
from modules.models_daily_cache import DailyPersonalizedCache
from modules.models_free_daily import FreeDailyQuestion

# See "GATE 1 FINDING" above -- the live, actually-imported module, not
# modules/models_notification.py or the root-level models_notification_log.py
# (both confirmed dead/unimported anywhere in this codebase).
from notifications.notification_models import NotificationLog, UserNotification


class AccountDeletionError(Exception):
    """Raised only after the transaction has already been rolled back
    (see delete_account_data()'s own try/except) -- callers never need
    to roll back themselves."""


@dataclass(frozen=True)
class ResolvedIdentity:
    """Output of resolve_firebase_identity(). `user` and `profile_ids`
    are deliberately separate fields in separate identity spaces --
    never collapsed into a single id. `profile_ids` is a LIST because
    AppUser.firebase_uid is NOT uniquely constrained (see module
    docstring) -- code that assumes len == 1 is a bug, not this
    dataclass's contract."""

    firebase_uid: str
    user: Optional[User]
    profile_ids: List[int] = field(default_factory=list)
    found: bool = False


@dataclass(frozen=True)
class DeletionResult:
    """Structured, JSON-serializable outcome of one delete_account_data()
    call."""

    firebase_uid: str
    hard_deleted_profile_ids: List[int] = field(default_factory=list)
    anonymized_profile_ids: List[int] = field(default_factory=list)
    retained_financial_profile_ids: List[int] = field(default_factory=list)
    user_deleted: bool = False
    already_absent: bool = False

    def to_dict(self) -> dict:
        return {
            "firebase_uid": self.firebase_uid,
            "hard_deleted_profile_ids": list(self.hard_deleted_profile_ids),
            "anonymized_profile_ids": list(self.anonymized_profile_ids),
            "retained_financial_profile_ids": list(self.retained_financial_profile_ids),
            "user_deleted": self.user_deleted,
            "already_absent": self.already_absent,
        }


def resolve_firebase_identity(firebase_uid: str) -> ResolvedIdentity:
    """
    Read-only. Never mutates anything. Resolves the `users` row (by
    firebase_uid, genuinely unique there) AND every `app_users` row
    sharing that SAME firebase_uid (never assumed unique -- see module
    docstring). A missing/already-deleted identity is not an error
    here -- it simply produces found=False, which
    delete_account_data() treats as a safe, idempotent no-op.
    """
    if not firebase_uid:
        raise ValueError("firebase_uid is required")

    user = User.query.filter_by(firebase_uid=firebase_uid).first()
    app_user_rows = AppUser.query.filter_by(firebase_uid=firebase_uid).all()
    profile_ids = [row.id for row in app_user_rows]

    return ResolvedIdentity(
        firebase_uid=firebase_uid,
        user=user,
        profile_ids=profile_ids,
        found=(user is not None or bool(profile_ids)),
    )


# ---------------------------------------------------------------------------
# Table lookups -- explicit (model, column_name) pairs, deliberately NOT a
# hasattr()-based heuristic: SubscriptionPurchaseMapping has BOTH
# `profile_id` (app_users.id, the real resolution key) and `user_id`
# (users.id, optional) columns, so an implicit "pick whichever attribute
# exists" rule would be fragile the moment a future model carries both
# for different reasons. Being explicit here is the safer choice.
# ---------------------------------------------------------------------------
_FINANCIAL_PROFILE_LOOKUPS = [
    (CurrentEntitlement, "profile_id"),
    (SubscriptionEvent, "profile_id"),
    (SubscriptionPurchaseMapping, "profile_id"),
    (ChatPack, "user_id"),          # user_id here IS app_users.id, by this codebase's own documented convention (D0.1 / Phase 0)
    (AskNowOrder, "user_id"),       # deprecated feature, but real historical evidence -- retained regardless
    (SubscriptionOrder, "user_id"),
]

_PERSONAL_CHILD_LOOKUPS = [
    (UserDashaTimeline, "user_id"),       # FK -> app_users.id, nullable=False
    (AlertMicroEvent, "profile_id"),      # FK -> app_users.id
    (AIReport, "profile_id"),             # FK -> app_users.id
    (UserNotification, "user_id"),        # no FK; app_users.id by convention
    (NotificationLog, "user_id"),         # no FK; app_users.id by convention
    (DailyPersonalizedCache, "profile_id"),  # carries BOTH user_id (users.id) and profile_id (app_users.id) as separate columns -- profile_id is the one that matches app_users.id
    (FreeDailyQuestion, "user_id"),       # no FK; app_users.id by convention
]


def _has_financial_history(profile_id: int) -> bool:
    for model, column in _FINANCIAL_PROFILE_LOOKUPS:
        row = model.query.filter_by(**{column: profile_id}).first()
        if row is not None:
            return True
    return False


def _delete_personal_children(profile_id: int) -> None:
    for model, column in _PERSONAL_CHILD_LOOKUPS:
        model.query.filter_by(**{column: profile_id}).delete(synchronize_session=False)


def _anonymize_app_user(app_user: AppUser) -> None:
    """Nulls every personal field, using columns already nullable today
    (verified directly -- no migration required). `firebase_uid` is
    deliberately NOT touched here -- see module docstring."""
    app_user.name = None
    app_user.email = None
    app_user.phone = None
    app_user.dob = None
    app_user.tob = None
    app_user.pob = None
    app_user.lat = None
    app_user.lng = None
    app_user.lagna = None
    app_user.moon_sign = None
    app_user.nakshatra = None
    app_user.fcm_token = None
    app_user.subscription = "free"
    app_user.asknow_tokens = 0


def delete_account_data(resolved_identity: ResolvedIdentity) -> DeletionResult:
    """
    ONE atomic transaction covering every write this function makes.
    Any exception rolls back the ENTIRE transaction -- no partial
    application is ever left behind (Gate 3).

    Idempotent: calling this again for an identity that is already
    fully gone (found=False on a fresh resolve) is a safe, cheap
    no-op. Calling it again for a profile that was ANONYMIZED (not
    hard-deleted) on a prior call is also safe -- re-nulling
    already-null fields and re-running now-empty child deletes are
    both no-ops, never errors, never touch a different profile.
    """
    if not resolved_identity.found:
        return DeletionResult(firebase_uid=resolved_identity.firebase_uid, already_absent=True)

    hard_deleted: List[int] = []
    anonymized: List[int] = []
    retained_financial: List[int] = []

    try:
        for profile_id in resolved_identity.profile_ids:
            has_financial = _has_financial_history(profile_id)

            # Personal-data children are ALWAYS removed first, regardless
            # of what happens to the parent AppUser row below -- this is
            # what makes the later hard-delete-vs-anonymize branch safe
            # (by the time we reach it, nothing personal still points at
            # this profile_id).
            _delete_personal_children(profile_id)

            app_user = AppUser.query.get(profile_id)
            if app_user is None:
                # Already gone (e.g. a concurrent/retried call raced
                # ahead of this one) -- not an error, just nothing left
                # to do for this profile_id.
                continue

            if has_financial:
                _anonymize_app_user(app_user)
                anonymized.append(profile_id)
                retained_financial.append(profile_id)
            else:
                db.session.delete(app_user)
                hard_deleted.append(profile_id)

        user_deleted = False
        if resolved_identity.user is not None:
            users_id = resolved_identity.user.id

            # Optional, informational-only link (see its own model
            # docstring) -- safe to sever; column is already nullable.
            SubscriptionPurchaseMapping.query.filter_by(user_id=users_id).update(
                {"user_id": None}, synchronize_session=False,
            )

            # Legacy System-A rows -- deleted outright, not retained
            # (see module docstring for why this differs from
            # SubscriptionEvent's own append-only treatment).
            Subscription.query.filter_by(user_id=users_id).delete(synchronize_session=False)

            db.session.delete(resolved_identity.user)
            user_deleted = True

        db.session.commit()

    except Exception as exc:
        db.session.rollback()
        raise AccountDeletionError(
            f"Account deletion failed for firebase_uid={resolved_identity.firebase_uid!r}: {exc}"
        ) from exc

    return DeletionResult(
        firebase_uid=resolved_identity.firebase_uid,
        hard_deleted_profile_ids=hard_deleted,
        anonymized_profile_ids=anonymized,
        retained_financial_profile_ids=retained_financial,
        user_deleted=user_deleted,
    )


def clear_pending_firebase_marker(profile_ids: List[int]) -> None:
    """
    D3 companion. Clears the temporary `firebase_uid` pending-cleanup
    marker (see this module's docstring, "`firebase_uid` is
    deliberately KEPT") on ANONYMIZED AppUser rows, ONCE the caller has
    already confirmed Firebase-side cleanup (Firestore + Auth) actually
    succeeded for that same firebase_uid.

    Deliberately a SEPARATE, narrow transaction from delete_account_data()
    -- it cannot participate in that transaction, because by definition
    it only ever runs strictly AFTER a real (out-of-process, non-DB)
    Firebase deletion has already completed. Scoped by explicit
    `profile_ids`, never by re-matching on firebase_uid, so it can never
    reach a row beyond the exact set the caller already deleted-from-
    Firebase.

    Idempotent: rows whose firebase_uid is already NULL are simply
    matched and set to NULL again -- not an error.

    Does not, and must never, touch any retained financial-adjacent
    table -- none of them carry a firebase_uid column at all (see
    _FINANCIAL_PROFILE_LOOKUPS), so there is nothing there this
    function could disturb even in principle.
    """
    if not profile_ids:
        return

    try:
        AppUser.query.filter(AppUser.id.in_(profile_ids)).update(
            {"firebase_uid": None}, synchronize_session=False,
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise AccountDeletionError(
            f"Failed to clear pending firebase_uid marker for profile_ids={profile_ids!r}: {exc}"
        ) from exc
