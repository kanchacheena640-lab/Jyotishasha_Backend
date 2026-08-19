# modules/entitlement/entitlement_write_service.py

"""
EntitlementWriteService -- THE only component allowed to write to
CurrentEntitlement or create SubscriptionEvent rows.

    EntitlementService        reads   CurrentEntitlement (never writes)
    EntitlementWriteService   writes  CurrentEntitlement + SubscriptionEvent

This split mirrors ReportCacheRepository's role for AIReport: one
dedicated module owns every write to a given table so every other
module (EntitlementService, PremiumReportService, the AI Report
Engine, routes) only ever reads through the appropriate read-only
service and never touches these two tables directly. That rule must
remain true going forward.

Design notes:
- CurrentEntitlement stays a single-row-per-profile *cache* (same
  "cache, not history" principle as AIReport) -- every method here
  updates the one existing row in place, or creates it if missing.
- SubscriptionEvent stays append-only history -- every state
  transition below records exactly one new event row and never
  updates/deletes an existing one.
- Every public method commits its own transaction (this is a real
  write service, not a read-only helper) and rolls back completely on
  any failure -- there is no path that leaves a partial write
  (CurrentEntitlement updated but no SubscriptionEvent, or vice versa).
- Every public method returns an EntitlementWriteResult -- never a raw
  ORM model -- describing what happened. Expected "nothing to do"
  cases (duplicate trial, renewing/expiring something that doesn't
  exist, invalid input) are reported as a structured result with
  success=True/False and a descriptive `action`, not raised as
  exceptions. Business outcomes and infrastructure failures are kept
  strictly separate: an unexpected failure (SQLAlchemyError,
  IntegrityError, a dropped connection, or any other exception the
  code above did not anticipate) is rolled back and RE-RAISED, never
  converted into an EntitlementWriteResult. A structured result always
  means "the database is fine, here is the business outcome"; an
  exception always means "the write did not happen, something is
  actually wrong."
- This service makes no access decisions and calls no access-control
  code -- it only records entitlement state changes. EntitlementService
  remains the sole place that answers "does this profile have access."

State transitions implemented here:

    (no row) --start_trial--> TRIAL
    TRIAL --expire_trial--> EXPIRED
    TRIAL / (no row) --activate_subscription--> ACTIVE
    ACTIVE / GRACE / EXPIRED --renew_subscription--> ACTIVE
    ACTIVE --enter_grace--> GRACE
    GRACE --exit_grace--> EXPIRED
    ACTIVE / GRACE --expire_subscription--> EXPIRED
    ACTIVE / GRACE --cancel_subscription--> (unchanged status, auto_renew=False)
    any --record_refund--> REFUNDED
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.models_premium_subscription import (
    CurrentEntitlement,
    SubscriptionEvent,
    SUBSCRIPTION_PLANS,
)
from modules.entitlement.subscription_sections import SUBSCRIPTION_SECTIONS
from modules.entitlement.entitlement_write_models import EntitlementWriteResult
from modules.entitlement.plan_access_policy import ACCESS_SELECTED, PLAN_SEGMENT_ACCESS

DEFAULT_TRIAL_DURATION_DAYS = 7

# Statuses that mean "this profile is currently paying" -- start_trial
# must never overwrite either of these.
_ACTIVE_SUBSCRIPTION_STATUSES = ("ACTIVE", "GRACE")


class EntitlementWriteService:
    def __init__(self, trial_duration_days: int = DEFAULT_TRIAL_DURATION_DAYS):
        self._trial_duration_days = trial_duration_days

    # ------------------------------------------------------------
    def start_trial(self, profile_id: int) -> EntitlementWriteResult:
        try:
            row = CurrentEntitlement.query.filter_by(profile_id=profile_id).first()
            previous_status = row.status if row is not None else None

            # A trial is a one-time-per-profile promotion: never restart
            # it once it has ever been started (even if it has since
            # expired), and never overwrite a paying (ACTIVE/GRACE)
            # profile that skipped the trial and went straight to
            # purchase.
            already_ineligible = row is not None and (
                row.trial_started_at is not None
                or row.status in _ACTIVE_SUBSCRIPTION_STATUSES
            )
            if already_ineligible:
                return EntitlementWriteResult(
                    success=True,
                    action="TRIAL_SKIPPED",
                    profile_id=profile_id,
                    previous_status=previous_status,
                    new_status=previous_status,
                    plan=row.plan,
                    selected_segment=row.selected_segment,
                    expires_at=row.subscription_expires_at,
                    message="Trial not started: this profile has already trialed, "
                            "or already has an active/grace subscription.",
                )

            now = datetime.utcnow()
            trial_expires_at = now + timedelta(days=self._trial_duration_days)

            if row is None:
                row = CurrentEntitlement(profile_id=profile_id)
                db.session.add(row)

            row.status = "TRIAL"
            row.trial_started_at = now
            row.trial_expires_at = trial_expires_at

            event = self._record_event(
                profile_id=profile_id,
                event_type="TRIAL_STARTED",
                status="TRIAL",
                starts_at=now,
                expires_at=trial_expires_at,
            )
            row.last_event_id = event.id

            db.session.commit()
            return EntitlementWriteResult(
                success=True,
                action="TRIAL_STARTED",
                profile_id=profile_id,
                previous_status=previous_status,
                new_status="TRIAL",
                expires_at=trial_expires_at,
                message=f"Trial started, expires {trial_expires_at.isoformat()}.",
            )
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------
    def expire_trial(self, profile_id: int) -> EntitlementWriteResult:
        try:
            row = CurrentEntitlement.query.filter_by(profile_id=profile_id).first()
            if row is None:
                return EntitlementWriteResult(
                    success=False,
                    action="TRIAL_EXPIRE_FAILED_NO_ENTITLEMENT",
                    profile_id=profile_id,
                    message="No entitlement exists.",
                )

            previous_status = row.status

            # Only a profile currently ON TRIAL can be trial-expired --
            # never overwrite a paid ACTIVE/GRACE subscription just
            # because a trial-expiry sweep happened to target this
            # profile_id (e.g. after the profile has since purchased).
            if row.status != "TRIAL":
                return EntitlementWriteResult(
                    success=True,
                    action="TRIAL_EXPIRE_SKIPPED",
                    profile_id=profile_id,
                    previous_status=previous_status,
                    new_status=previous_status,
                    plan=row.plan,
                    selected_segment=row.selected_segment,
                    expires_at=row.subscription_expires_at,
                    message="Not currently on trial; nothing to expire.",
                )

            row.status = "EXPIRED"

            event = self._record_event(
                profile_id=profile_id,
                event_type="TRIAL_EXPIRED",
                status="EXPIRED",
                expires_at=row.trial_expires_at,
            )
            row.last_event_id = event.id

            db.session.commit()
            return EntitlementWriteResult(
                success=True,
                action="TRIAL_EXPIRED",
                profile_id=profile_id,
                previous_status=previous_status,
                new_status="EXPIRED",
                expires_at=row.trial_expires_at,
                message="Trial expired.",
            )
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------
    def activate_subscription(
        self,
        profile_id: int,
        plan: str,
        selected_segment: Optional[str],
        expires_at: datetime,
        transaction_reference: Optional[str] = None,
    ) -> EntitlementWriteResult:
        try:
            if plan not in SUBSCRIPTION_PLANS:
                return EntitlementWriteResult(
                    success=False, action="ERROR", profile_id=profile_id,
                    message=f"Unknown plan: {plan!r}",
                )
            if PLAN_SEGMENT_ACCESS.get(plan) == ACCESS_SELECTED:
                if not selected_segment or selected_segment not in SUBSCRIPTION_SECTIONS:
                    return EntitlementWriteResult(
                        success=False, action="ERROR", profile_id=profile_id,
                        message=f"{plan} requires a valid selected_segment.",
                    )
            if expires_at is None:
                return EntitlementWriteResult(
                    success=False, action="ERROR", profile_id=profile_id,
                    message="expires_at is required.",
                )

            # subscription_expires_at is a naive-UTC column (same as
            # every other timestamp in this class); a caller may pass a
            # timezone-aware value (e.g. GooglePlayProvider's parsed
            # RFC3339 timestamps). Normalize once, here, rather than
            # storing a mix of aware/naive values that would later fail
            # to compare against datetime.utcnow().
            if expires_at.tzinfo is not None:
                expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)

            now = datetime.utcnow()

            # Subscription Purchase System -- S15. A stale/replayed/
            # already-expired purchase must never activate at all,
            # independent of whatever CurrentEntitlement currently
            # holds.
            if expires_at <= now:
                return EntitlementWriteResult(
                    success=False, action="ACTIVATION_SKIPPED_EXPIRED", profile_id=profile_id,
                    message=(
                        f"expires_at ({expires_at.isoformat()}) is not in the future; "
                        f"not activating."
                    ),
                )

            # S15 -- lock this profile's row for the rest of this
            # transaction. A concurrent activate_subscription() call for
            # the same profile_id (two different purchase_tokens racing
            # -- e.g. two devices) blocks here until this transaction
            # commits or rolls back, then reads this write's own
            # committed result -- never a stale read racing a concurrent
            # write. Standard SQLAlchemy/Postgres row locking; no new
            # framework introduced.
            #
            # SELECT ... FOR UPDATE only locks a row that already
            # exists -- it has nothing to lock on a profile's very
            # first-ever purchase, so two concurrent first purchases
            # can both see "no row" and both attempt to INSERT. The
            # table's own existing UNIQUE(profile_id) constraint is the
            # real backstop for that specific case (see the
            # IntegrityError handling below), exactly the same
            # insert-first/catch-conflict/reconcile shape already used
            # by SubscriptionPurchaseMappingService.
            row = (
                CurrentEntitlement.query
                .filter_by(profile_id=profile_id)
                .with_for_update()
                .first()
            )

            stale = self._is_stale_activation(row, expires_at)
            if stale is not None:
                return stale

            try:
                return self._write_activation(
                    row=row, profile_id=profile_id, plan=plan,
                    selected_segment=selected_segment, expires_at=expires_at,
                    now=now, transaction_reference=transaction_reference,
                )
            except IntegrityError:
                # Lost the first-ever-row insert race -- a concurrent
                # activate_subscription() for this exact profile_id won
                # and already committed its own row. Roll back this
                # attempt, re-read WITH the lock (guaranteed to see that
                # committed row now), and reapply the same staleness
                # decision against it rather than crashing or blindly
                # overwriting the winner.
                db.session.rollback()
                row = (
                    CurrentEntitlement.query
                    .filter_by(profile_id=profile_id)
                    .with_for_update()
                    .first()
                )
                stale = self._is_stale_activation(row, expires_at)
                if stale is not None:
                    return stale
                return self._write_activation(
                    row=row, profile_id=profile_id, plan=plan,
                    selected_segment=selected_segment, expires_at=expires_at,
                    now=now, transaction_reference=transaction_reference,
                )
        except Exception:
            db.session.rollback()
            raise

    def _is_stale_activation(
        self, row: Optional[CurrentEntitlement], expires_at: datetime,
    ) -> Optional[EntitlementWriteResult]:
        """S15 downgrade/staleness protection. Only a currently ACTIVE
        entitlement needs protecting here -- TRIAL/PENDING/EXPIRED/
        CANCELLED/GRACE/REFUNDED (or no row at all) all still allow a
        fresh activation exactly as before (trial-to-paid and
        resubscribe-after-cancel/expiry are unaffected). Reuses the
        existing subscription_expires_at column as the only signal --
        no new versioning/priority metadata invented: an incoming
        purchase only replaces what's active if it would actually
        extend coverage beyond it. Returns a structured, unsuccessful
        EntitlementWriteResult if the incoming purchase should be
        rejected as stale, or None if it's safe to proceed."""
        if (
            row is not None
            and row.status == "ACTIVE"
            and row.subscription_expires_at is not None
            and expires_at <= row.subscription_expires_at
        ):
            return EntitlementWriteResult(
                success=False, action="ACTIVATION_SKIPPED_STALE", profile_id=row.profile_id,
                previous_status=row.status, new_status=row.status,
                plan=row.plan, selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
                message=(
                    f"Currently active entitlement already extends to "
                    f"{row.subscription_expires_at.isoformat()}; this purchase's "
                    f"expires_at ({expires_at.isoformat()}) would not extend it -- ignored."
                ),
            )
        return None

    def _write_activation(
        self, *, row: Optional[CurrentEntitlement], profile_id: int, plan: str,
        selected_segment: Optional[str], expires_at: datetime, now: datetime,
        transaction_reference: Optional[str],
    ) -> EntitlementWriteResult:
        previous_status = row.status if row is not None else None

        if row is None:
            row = CurrentEntitlement(profile_id=profile_id)
            db.session.add(row)

        row.status = "ACTIVE"
        row.plan = plan
        row.selected_segment = selected_segment
        row.subscription_started_at = now
        row.subscription_expires_at = expires_at

        event = self._record_event(
            profile_id=profile_id,
            event_type="SUBSCRIPTION_STARTED",
            status="ACTIVE",
            plan=plan,
            selected_segment=selected_segment,
            starts_at=now,
            expires_at=expires_at,
            transaction_id=transaction_reference,
        )
        row.last_event_id = event.id

        db.session.commit()
        return EntitlementWriteResult(
            success=True,
            action="SUBSCRIPTION_ACTIVATED",
            profile_id=profile_id,
            previous_status=previous_status,
            new_status="ACTIVE",
            plan=plan,
            selected_segment=selected_segment,
            expires_at=expires_at,
            message=f"Subscription activated: {plan}.",
        )

    # ------------------------------------------------------------
    def renew_subscription(
        self,
        profile_id: int,
        expires_at: datetime,
        plan: Optional[str] = None,
        selected_segment: Optional[str] = None,
        transaction_reference: Optional[str] = None,
    ) -> EntitlementWriteResult:
        try:
            if expires_at is None:
                return EntitlementWriteResult(
                    success=False, action="ERROR", profile_id=profile_id,
                    message="expires_at is required.",
                )
            if plan is not None and plan not in SUBSCRIPTION_PLANS:
                return EntitlementWriteResult(
                    success=False, action="ERROR", profile_id=profile_id,
                    message=f"Unknown plan: {plan!r}",
                )

            row = CurrentEntitlement.query.filter_by(profile_id=profile_id).first()
            if row is None:
                return EntitlementWriteResult(
                    success=False,
                    action="RENEWAL_FAILED_NO_ENTITLEMENT",
                    profile_id=profile_id,
                    message="No entitlement exists to renew.",
                )

            previous_status = row.status

            # Preserve plan/selected_segment unless the caller explicitly
            # passed a new value.
            if plan is not None:
                row.plan = plan
            if selected_segment is not None:
                row.selected_segment = selected_segment

            row.status = "ACTIVE"
            row.subscription_expires_at = expires_at

            event = self._record_event(
                profile_id=profile_id,
                event_type="SUBSCRIPTION_RENEWED",
                status="ACTIVE",
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=expires_at,
                transaction_id=transaction_reference,
            )
            row.last_event_id = event.id

            db.session.commit()
            return EntitlementWriteResult(
                success=True,
                action="SUBSCRIPTION_RENEWED",
                profile_id=profile_id,
                previous_status=previous_status,
                new_status="ACTIVE",
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=expires_at,
                message="Subscription renewed.",
            )
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------
    def enter_grace(self, profile_id: int) -> EntitlementWriteResult:
        try:
            row = CurrentEntitlement.query.filter_by(profile_id=profile_id).first()
            if row is None:
                return EntitlementWriteResult(
                    success=False,
                    action="GRACE_FAILED_NO_ENTITLEMENT",
                    profile_id=profile_id,
                    message="No entitlement exists to enter grace.",
                )

            previous_status = row.status
            row.status = "GRACE"
            # plan / selected_segment / subscription_expires_at
            # intentionally left untouched -- preserved.

            event = self._record_event(
                profile_id=profile_id,
                event_type="SUBSCRIPTION_GRACE_ENTERED",
                status="GRACE",
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
            )
            row.last_event_id = event.id

            db.session.commit()
            return EntitlementWriteResult(
                success=True,
                action="GRACE_ENTERED",
                profile_id=profile_id,
                previous_status=previous_status,
                new_status="GRACE",
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
                message="Entered grace period.",
            )
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------
    def exit_grace(self, profile_id: int) -> EntitlementWriteResult:
        try:
            row = CurrentEntitlement.query.filter_by(profile_id=profile_id).first()
            if row is None:
                return EntitlementWriteResult(
                    success=False,
                    action="EXIT_GRACE_FAILED_NO_ENTITLEMENT",
                    profile_id=profile_id,
                    message="No entitlement exists.",
                )

            previous_status = row.status
            row.status = "EXPIRED"

            event = self._record_event(
                profile_id=profile_id,
                event_type="SUBSCRIPTION_EXPIRED",
                status="EXPIRED",
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
            )
            row.last_event_id = event.id

            db.session.commit()
            return EntitlementWriteResult(
                success=True,
                action="GRACE_EXITED_EXPIRED",
                profile_id=profile_id,
                previous_status=previous_status,
                new_status="EXPIRED",
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
                message="Grace period ended without renewal; subscription expired.",
            )
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------
    def cancel_subscription(self, profile_id: int) -> EntitlementWriteResult:
        """
        User-initiated cancellation. Mirrors real store semantics
        (Google Play / Apple / Stripe): cancelling stops future
        renewal but does NOT revoke access early -- the profile keeps
        whatever status/expiry it already has until
        subscription_expires_at naturally passes, at which point a
        later expire_subscription() call (e.g. a billing-cycle sweep)
        ends access as usual. This method only flips auto_renew off
        and records the cancellation; it deliberately never touches
        `status`.
        """
        try:
            row = CurrentEntitlement.query.filter_by(profile_id=profile_id).first()
            if row is None:
                return EntitlementWriteResult(
                    success=False,
                    action="CANCEL_FAILED_NO_ENTITLEMENT",
                    profile_id=profile_id,
                    message="No entitlement exists to cancel.",
                )

            previous_status = row.status
            row.auto_renew = False
            # status / plan / selected_segment / subscription_expires_at
            # intentionally left untouched -- access continues until
            # the already-paid-for period ends.

            event = self._record_event(
                profile_id=profile_id,
                event_type="SUBSCRIPTION_CANCELLED",
                status=row.status,
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
            )
            row.last_event_id = event.id

            db.session.commit()
            return EntitlementWriteResult(
                success=True,
                action="SUBSCRIPTION_CANCELLED",
                profile_id=profile_id,
                previous_status=previous_status,
                new_status=row.status,
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
                message="Auto-renew disabled; access continues until the current period ends.",
            )
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------
    def expire_subscription(self, profile_id: int) -> EntitlementWriteResult:
        try:
            row = CurrentEntitlement.query.filter_by(profile_id=profile_id).first()
            if row is None:
                return EntitlementWriteResult(
                    success=False,
                    action="EXPIRE_FAILED_NO_ENTITLEMENT",
                    profile_id=profile_id,
                    message="No entitlement exists.",
                )

            previous_status = row.status
            row.status = "EXPIRED"
            # plan / selected_segment / subscription_started_at /
            # subscription_expires_at intentionally left untouched --
            # preserved as historical record of what this profile had.

            event = self._record_event(
                profile_id=profile_id,
                event_type="SUBSCRIPTION_EXPIRED",
                status="EXPIRED",
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
            )
            row.last_event_id = event.id

            db.session.commit()
            return EntitlementWriteResult(
                success=True,
                action="SUBSCRIPTION_EXPIRED",
                profile_id=profile_id,
                previous_status=previous_status,
                new_status="EXPIRED",
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
                message="Subscription marked expired.",
            )
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------
    def record_refund(
        self, profile_id: int, transaction_reference: Optional[str] = None,
    ) -> EntitlementWriteResult:
        """
        A refund reverses payment, so -- unlike cancel_subscription --
        access is revoked immediately: status becomes REFUNDED, a
        terminal state distinct from EXPIRED so a later read can tell
        "lapsed naturally" apart from "money was returned".
        """
        try:
            row = CurrentEntitlement.query.filter_by(profile_id=profile_id).first()
            if row is None:
                return EntitlementWriteResult(
                    success=False,
                    action="REFUND_FAILED_NO_ENTITLEMENT",
                    profile_id=profile_id,
                    message="No entitlement exists to refund.",
                )

            previous_status = row.status
            row.status = "REFUNDED"
            # plan / selected_segment intentionally left untouched --
            # preserved as historical record of what was refunded.

            event = self._record_event(
                profile_id=profile_id,
                event_type="SUBSCRIPTION_REFUNDED",
                status="REFUNDED",
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
                transaction_id=transaction_reference,
            )
            row.last_event_id = event.id

            db.session.commit()
            return EntitlementWriteResult(
                success=True,
                action="SUBSCRIPTION_REFUNDED",
                profile_id=profile_id,
                previous_status=previous_status,
                new_status="REFUNDED",
                plan=row.plan,
                selected_segment=row.selected_segment,
                expires_at=row.subscription_expires_at,
                message="Subscription marked refunded; access revoked.",
            )
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------
    # Internal: the only place a SubscriptionEvent is constructed.
    # ------------------------------------------------------------
    def _record_event(
        self,
        *,
        profile_id: int,
        event_type: str,
        status: str,
        plan: Optional[str] = None,
        selected_segment: Optional[str] = None,
        starts_at: Optional[datetime] = None,
        expires_at: Optional[datetime] = None,
        store: Optional[str] = None,
        purchase_token: Optional[str] = None,
        transaction_id: Optional[str] = None,
        receipt_payload: Optional[dict] = None,
    ) -> SubscriptionEvent:
        event = SubscriptionEvent(
            profile_id=profile_id,
            event_type=event_type,
            status=status,
            plan=plan,
            selected_segment=selected_segment,
            starts_at=starts_at,
            expires_at=expires_at,
            store=store,
            purchase_token=purchase_token,
            transaction_id=transaction_id,
            receipt_payload=receipt_payload,
        )
        db.session.add(event)
        db.session.flush()  # populate event.id without committing
        return event
