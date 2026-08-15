# modules/alerts/alerts_scheduler.py

"""
Isolated Alerts Batch Scheduler (Phase 6).

`run_daily_alerts_job()` -- the single, NEW entry point that batch-
processes eligible profiles through the full Alerts pipeline already
built in Phases 1-5.1:

    Profiles -> entitlement pre-filter -> detection -> persisted active
        alerts -> delivery -> summary

Completely SEPARATE from services/event_scheduler.py::run_daily_event_job()
-- that function's body is not read, called, or modified by this file
in any way. A failure anywhere in this job (or in one profile's
processing) can never affect the generic notification pipeline, which
this file does not import at all.

==================================================
CONCURRENCY (Postgres advisory lock -- verified, not assumed)
==================================================
A single, session-scoped Postgres advisory lock
(pg_try_advisory_lock/pg_advisory_unlock), held on ONE dedicated
connection for the job's entire duration, guarantees only one
execution of this job runs at a time. Verified directly (two real,
concurrent psql sessions) before writing this file: a second session's
pg_try_advisory_lock() call returns false while a first session still
holds the same key, and both return true again once released. If a
previous run is still in progress, a new invocation returns
immediately having done zero work -- not queued, not blocked -- so a
manual rerun is always safe.

This is the smallest reliable mechanism per this phase's own
instruction: no new table, no Redis, no Celery introduced solely for
this (repo-wide search confirmed zero existing advisory-lock usage to
collide with; the transaction-scoped variant, pg_try_advisory_xact_lock,
was deliberately NOT used -- it releases at the end of the current
transaction, but this job's per-profile work commits many times over
its run, so only the session-scoped variant, explicitly held open on
its own connection until the job finishes, actually covers the whole
run).

Beyond the lock, RE-RUNNING the job sequentially (not concurrently) is
already safe by construction from earlier phases: detection
(synchronize_profile_events(), Phase 2) upserts on
(profile_id, event_id) and never duplicates a row, and delivery
(deliver_alert(), Phase 4/5) is cooldown-gated and will not resend
within an event's cooldown window. The lock's job is specifically to
prevent two overlapping executions from wastefully double-processing
the same batch of profiles at the same moment, not to provide
idempotency that already exists.

==================================================
ENTITLEMENT PRE-FILTER (before any astrology)
==================================================
Candidate profile_ids are read from current_entitlements.profile_id
(cheap, indexed, unique per profile) rather than iterating every
AppUser -- a profile with no CurrentEntitlement row at all can never be
entitled (EntitlementService.get_current_entitlement() returns an
empty/PENDING snapshot for it), so it is never even considered.
modules/alerts/entitlement_gate.py::has_alerts_access() (Phase 5,
unmodified) remains the SOLE authority on the actual yes/no decision --
this file does not filter by status/plan/trial-window itself, so no
subscription business rule is duplicated here. Entitlement is checked
BEFORE AppUser is even loaded, and definitely before
full_kundali_api.calculate_full_kundali()/ProfileDetectionService are
ever reached.

==================================================
NOT enabled for production scheduling by this phase
==================================================
No GitHub Actions workflow file is added in this phase -- Phase 6's own
scope is "build the isolated batch job... Do NOT activate production
scheduling yet." Wiring this into a schedule (workflow file, cron
entry, or otherwise) is explicitly deferred to Phase 7 ("Production
Readiness, Migration Reconciliation & Controlled Activation").
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import text

from extensions import db
from modules.models_user import AppUser
from modules.models_premium_subscription import CurrentEntitlement

from modules.entitlement.entitlement_service import EntitlementService

from modules.alerts.alert_delivery_service import deliver_alert
from modules.alerts.entitlement_gate import has_alerts_access
from modules.alerts.notification_content_adapter import AlertContentError, build_alert_notification_content
from modules.alerts.persistence_repository import AlertPersistenceRepository
from modules.alerts.profile_detection_service import (
    DetectionRunFailedError,
    ProfileDataError,
    ProfileDetectionService,
)
from modules.alerts.sunrise_boundary import SunriseResolutionError
from modules.alerts.user_alert_selection_service import get_user_facing_alerts_for_profile
from services.attention_policy import (
    DAILY_PUSH_CAP,
    count_pushes_sent_today,
    tier_for_alert_severity,
)

# Dedicated advisory lock key for THIS job only -- an arbitrary constant
# chosen once, never reused elsewhere (verified: zero other advisory
# lock usage anywhere in this codebase). The two-argument form
# (classid, objid) namespaces it further, purely for readability.
_ADVISORY_LOCK_CLASS_ID = 84331
_ADVISORY_LOCK_OBJECT_ID = 1

# Same batching convention services/event_scheduler.py's own STEP 5B
# already uses (BATCH_SIZE = 500) -- reused, not reinvented.
BATCH_SIZE = 500


@dataclass
class AlertsJobSummary:
    """Aggregate, non-sensitive counts only -- never birth data,
    Kundali data, or any other profile content. profile_id (a plain
    integer identifier) may appear in printed diagnostics; nothing
    else about a profile ever does."""

    profiles_scanned: int = 0
    entitlement_skipped: int = 0
    invalid_profile_skipped: int = 0
    missing_token_skipped: int = 0
    profiles_evaluated: int = 0
    alerts_detected: int = 0
    alerts_attempted: int = 0
    alerts_delivered: int = 0
    cooldown_or_eligibility_skipped: int = 0
    # Alerts Product Hardening addition -- otherwise-eligible alerts
    # that were NOT chosen for user-facing exposure this run (conflict/
    # similarity suppression, category-diversity exclusion, or the
    # max-2-per-alert-day cap). Distinct from
    # cooldown_or_eligibility_skipped, which counts alerts that failed
    # the PRE-EXISTING Phase 4 confidence/cooldown gate -- this counter
    # is purely about product-layer narrowing of an already-eligible
    # pool, for observability into how often/how much the selection
    # layer is actually trimming.
    selection_suppressed: int = 0
    # N4 -- Global User Attention Policy addition. Distinct from
    # selection_suppressed (Alerts' OWN local max-2/conflict narrowing,
    # unchanged): this counts an alert that PASSED Alerts' own selection
    # (i.e. Alerts wanted to send it) but was not attempted because the
    # user's GLOBAL daily push budget (shared with
    # services/event_scheduler.py's pipeline -- see
    # services/attention_policy.py) was already spent by an earlier
    # send today. Purely observability; does not change eligibility,
    # confidence, cooldown, or Alerts' own selection outcome.
    global_cap_suppressed: int = 0
    # N5 -- of the global_cap_suppressed alerts above, how many were
    # still written to Bell (via AlertPersistenceRepository.
    # record_bell_only(), never a real delivery -- see that method's own
    # docstring). Always <= global_cap_suppressed; the gap between the
    # two is alerts that were suppressed AND already had a still-active
    # bell-only row from an earlier run today (idempotent skip, not a
    # failure).
    alerts_bell_only: int = 0
    failures: int = 0
    duration_seconds: float = 0.0
    lock_acquired: bool = False

    def to_dict(self) -> dict:
        return {
            "profiles_scanned": self.profiles_scanned,
            "entitlement_skipped": self.entitlement_skipped,
            "invalid_profile_skipped": self.invalid_profile_skipped,
            "missing_token_skipped": self.missing_token_skipped,
            "profiles_evaluated": self.profiles_evaluated,
            "alerts_detected": self.alerts_detected,
            "alerts_attempted": self.alerts_attempted,
            "alerts_delivered": self.alerts_delivered,
            "cooldown_or_eligibility_skipped": self.cooldown_or_eligibility_skipped,
            "selection_suppressed": self.selection_suppressed,
            "global_cap_suppressed": self.global_cap_suppressed,
            "alerts_bell_only": self.alerts_bell_only,
            "failures": self.failures,
            "duration_seconds": round(self.duration_seconds, 3),
            "lock_acquired": self.lock_acquired,
        }


def run_daily_alerts_job(
    *,
    entitlement_service: Optional[EntitlementService] = None,
    detection_service: Optional[ProfileDetectionService] = None,
    repository: Optional[AlertPersistenceRepository] = None,
    batch_size: int = BATCH_SIZE,
    now: Optional[datetime] = None,
) -> AlertsJobSummary:
    """
    The Alerts job's single entry point. Safe to call repeatedly
    (sequential reruns) and safe to call concurrently (a second
    overlapping call returns immediately, having done nothing, if a
    first call is still running) -- see this module's own docstring
    for both guarantees.
    """
    started = time.monotonic()
    now = now or datetime.utcnow()
    summary = AlertsJobSummary()

    entitlement_service = entitlement_service or EntitlementService()
    detection_service = detection_service or ProfileDetectionService()
    repository = repository or AlertPersistenceRepository()

    lock_conn = db.engine.connect()
    try:
        got_lock = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(:classid, :objid)"),
            {"classid": _ADVISORY_LOCK_CLASS_ID, "objid": _ADVISORY_LOCK_OBJECT_ID},
        ).scalar()
        summary.lock_acquired = bool(got_lock)

        if not summary.lock_acquired:
            print("Alerts job: another execution is already in progress -- skipping this run.")
            summary.duration_seconds = time.monotonic() - started
            return summary

        offset = 0
        while True:
            profile_ids = _fetch_candidate_profile_ids(batch_size=batch_size, offset=offset)
            if not profile_ids:
                break

            for profile_id in profile_ids:
                summary.profiles_scanned += 1
                _process_one_profile(
                    profile_id=profile_id,
                    now=now,
                    entitlement_service=entitlement_service,
                    detection_service=detection_service,
                    repository=repository,
                    summary=summary,
                )

            offset += batch_size
    finally:
        if summary.lock_acquired:
            lock_conn.execute(
                text("SELECT pg_advisory_unlock(:classid, :objid)"),
                {"classid": _ADVISORY_LOCK_CLASS_ID, "objid": _ADVISORY_LOCK_OBJECT_ID},
            )
        lock_conn.close()

    summary.duration_seconds = time.monotonic() - started
    print(f"Alerts job summary: {summary.to_dict()}")
    return summary


def _fetch_candidate_profile_ids(*, batch_size: int, offset: int) -> List[int]:
    """
    Bounded, paginated read -- never loads the entire user base into
    memory. Reads ONLY current_entitlements.profile_id (a cheap,
    unique-indexed column); see this module's own "ENTITLEMENT
    PRE-FILTER" docstring section for why this table, and why no
    status/plan/trial filtering happens in this query itself.
    """
    rows = (
        db.session.query(CurrentEntitlement.profile_id)
        .order_by(CurrentEntitlement.profile_id)
        .limit(batch_size)
        .offset(offset)
        .all()
    )
    return [r[0] for r in rows]


def _process_one_profile(
    *,
    profile_id: int,
    now: datetime,
    entitlement_service: EntitlementService,
    detection_service: ProfileDetectionService,
    repository: AlertPersistenceRepository,
    summary: AlertsJobSummary,
) -> None:
    """
    Steps 1-7 of this phase's Per-Profile Flow. Isolated: any
    unexpected exception here is caught, the DB session is rolled back
    (mirroring services/event_scheduler.py's own STEP 5B
    try/except+rollback-per-user convention, reused rather than
    reinvented), and processing continues with the next profile --
    this profile's failure can never roll back or interrupt another
    profile's already-completed work, since each profile's actual
    persistence (detection sync, delivery finalization) already commits
    independently in earlier phases.
    """
    try:
        # ---- 1. Entitlement gate -- BEFORE any astrology or even
        # loading the AppUser row. ----
        entitlement = has_alerts_access(profile_id, entitlement_service=entitlement_service)
        if not entitlement.entitled:
            summary.entitlement_skipped += 1
            return

        # ---- 2/3. Cheap profile checks BEFORE expensive astrology ----
        user = AppUser.query.get(profile_id)
        if user is None:
            summary.invalid_profile_skipped += 1
            return

        fcm_token = getattr(user, "fcm_token", None)
        if not fcm_token:
            summary.missing_token_skipped += 1
            return

        # ---- 4. Detection (ProfileDetectionService, unmodified) ----
        try:
            result = detection_service.evaluate_profile(profile_id)
        except ProfileDataError:
            # Missing/invalid birth data -- ProfileDetectionService's
            # own _load_birth_details() already checks this BEFORE
            # calling calculate_full_kundali(), so no expensive
            # astrology ran for this profile either way.
            summary.invalid_profile_skipped += 1
            return
        except (DetectionRunFailedError, SunriseResolutionError):
            summary.failures += 1
            return

        summary.profiles_evaluated += 1
        summary.alerts_detected += result.events_detected

        # ---- 5. Fetch persisted active alerts (Phase 1, unmodified) --
        # needed below to count alerts that fail the pre-existing
        # eligibility gate for the (unchanged-meaning)
        # cooldown_or_eligibility_skipped counter. ----
        active_alerts = repository.fetch_active_for_profile(profile_id=profile_id)

        # ---- 5b. User Alert Selection Layer (Alerts Product Hardening)
        # -- narrows the full active-alert set down to the small,
        # non-contradictory, non-redundant user-facing subset (normally
        # 1, at most MAX_USER_FACING_ALERTS) BEFORE any delivery is
        # attempted. THE SAME function a future Alerts app API endpoint
        # must also call (see user_alert_selection_service.py's own
        # docstring) -- one selection authority for both push and any
        # future in-app list. Internally reuses the EXISTING, unmodified
        # Phase 4 eligibility/cooldown gate -- this layer only narrows
        # further for product exposure, never overrides that decision.
        selection = get_user_facing_alerts_for_profile(
            profile_id, now=now, repository=repository, lat=user.lat, lon=user.lng,
        )
        selected_event_ids = {r.event_id for r in selection.selected}

        # Pre-existing meaning preserved: alerts that failed the Phase 4
        # confidence/cooldown gate entirely (never even reached
        # selection) still count here, exactly as before this change.
        summary.cooldown_or_eligibility_skipped += len(active_alerts) - selection.eligible_count
        # New: alerts that PASSED that gate but were not chosen by the
        # selection layer (conflict/similarity suppression, category
        # diversity, or the daily cap).
        summary.selection_suppressed += selection.eligible_count - len(selection.selected)

        # ---- N4 (Global User Attention Policy) -- BEFORE attempting
        # delivery, narrow Alerts' own already-selected set (at most
        # MAX_USER_FACING_ALERTS, unchanged) against the user's GLOBAL
        # remaining daily push budget, shared with
        # services/event_scheduler.py's pipeline via the same persisted
        # signal (services/attention_policy.py::count_pushes_sent_today()
        # -- re-read fresh here, every call, so this can never see a
        # stale count from an earlier run). This does NOT touch Alerts'
        # own eligibility, confidence, cooldown, or selection algorithm
        # (user_alert_selection.py, unmodified) -- it only decides, of
        # the alerts Alerts already wants to send, how many actually fit
        # in what's left of today's budget. If only one slot remains and
        # two were selected, the higher-severity one is attempted first
        # (Alerts' own config-driven severity -- see
        # severity_cooldown_registry.py -- not re-derived here).
        global_remaining = max(
            0, DAILY_PUSH_CAP - count_pushes_sent_today(profile_id, now=now)
        )
        selected_rows = sorted(
            (r for r in active_alerts if r.event_id in selected_event_ids),
            key=lambda r: tier_for_alert_severity(r.severity),
        )
        attemptable_rows = selected_rows[:global_remaining]
        bell_only_rows = selected_rows[global_remaining:]
        summary.global_cap_suppressed += len(bell_only_rows)

        # ---- N5 -- Bell-only fallback for the rest. Every row here
        # ALREADY passed Alerts' own hardened eligibility + selection
        # (user_alert_selection.py, unmodified) in this exact run -- the
        # only reason it isn't being pushed is that today's global
        # budget ran out. A genuinely useful, already-vetted Alert
        # should not vanish completely just because the push slot was
        # spent elsewhere; see persistence_repository.py::
        # record_bell_only()'s own docstring for why this can never
        # touch cooldown/dedup or be mistaken for a real delivery. Never
        # attempted for a row that failed eligibility or was excluded by
        # Alerts' own selection -- bell_only_rows is a strict suffix of
        # selected_rows, both already-vetted sets.
        for alert_row in bell_only_rows:
            try:
                content = build_alert_notification_content(
                    event_id=alert_row.event_id,
                    category=alert_row.category,
                    severity=alert_row.severity,
                )
            except AlertContentError:
                continue  # same defensive posture as deliver_alert()'s own content stage

            bell_row = repository.record_bell_only(
                profile_id=profile_id,
                event_id=alert_row.event_id,
                notification_title=content["title"],
                notification_body=content["body"],
                notification_data=content["data"],
                active_until=alert_row.active_until,
                now=now,
            )
            if bell_row is not None:
                summary.alerts_bell_only += 1

        # ---- 6/7. Deliver each SELECTED-AND-GLOBALLY-BUDGETED alert --
        # deliver_alert() (Phase 4/5, unmodified) remains the SOLE
        # eligibility/cooldown authority for the actual send; nothing
        # here re-checks or duplicates that decision, it only decides
        # WHICH event_ids reach this call at all. ----
        for alert_row in attemptable_rows:
            summary.alerts_attempted += 1
            delivery = deliver_alert(
                profile_id=profile_id,
                event_id=alert_row.event_id,
                fcm_token=fcm_token,
                now=now,
                entitlement_service=entitlement_service,
                repository=repository,
            )
            # NOTE: branch on `delivery.stage`, NOT `delivery.sent` --
            # AlertDeliveryResult.sent is True for BOTH stage=="delivered"
            # (fully successful) AND stage=="finalization_failed" (FCM
            # physically succeeded, but the DB bookkeeping did not --
            # see alert_delivery_service.py's own docstring). Using
            # `sent` alone would silently miscount a finalization
            # failure as a clean delivery in this job's own operational
            # summary.
            if delivery.stage == "delivered":
                summary.alerts_delivered += 1
            elif delivery.stage == "eligibility":
                summary.cooldown_or_eligibility_skipped += 1
            elif delivery.stage in ("entitlement", "load", "content"):
                # Should be rare here (entitlement was just confirmed
                # and the row was just fetched) but is not a hard
                # failure -- simply not delivered this run.
                summary.cooldown_or_eligibility_skipped += 1
            else:  # "send" failed, or "finalization_failed"
                # A "finalization_failed" outcome means FCM already
                # succeeded -- deliver_alert() itself does not retry
                # the send (see its own docstring), and neither does
                # this loop: each active alert is attempted exactly
                # ONCE per job run, so a blind duplicate send can never
                # happen here.
                summary.failures += 1

    except Exception as exc:
        db.session.rollback()
        summary.failures += 1
        # profile_id (a plain integer) is safe to log; the exception
        # TYPE only is printed, never its message or any profile
        # content, per this phase's "do not log sensitive profile
        # content" requirement.
        print(f"Alerts job: profile_id={profile_id} failed with {type(exc).__name__} -- skipped, continuing.")
