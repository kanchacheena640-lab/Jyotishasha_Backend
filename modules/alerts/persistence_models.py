# modules/alerts/persistence_models.py

"""
Alerts Engine -- Database Persistence (Phase 1).

Adds the ONLY database table the Micro Event Engine uses. This file is
new and additive -- it is not imported by, and does not import, any of
the existing detection files (rule_interface.py, rule_evaluator.py,
confidence_engine.py, event_registry.py, micro_event_engine.py,
planning_window_engine.py, event_state.py) or the Premium Generators /
AI Report Engine. Those files remain exactly as the read-only audit
found them.

Identity: `profile_id` is a real foreign key to `app_users.id`, the
same convention modules/models_ai_reports.py::AIReport already uses
for the same reason (no dedicated Profile table exists yet in this
backend; AppUser already carries the kundali/birth data every
detection run needs).

Cache-row model, NOT an append-only history table: exactly ONE row per
(profile_id, event_id), enforced by a database-level UNIQUE constraint,
upserted in place across repeated detection runs. See
persistence_repository.py's module docstring for the full reasoning on
why (profile_id, event_id) -- and NOT (profile_id, event_id,
active_from) -- is the safe identity key, verified directly from
event_state.summarize()'s actual behavior.

Explicitly NOT stored here (per this phase's scope): birth data, natal
chart, full kundali JSON, question text, prompt content, or any
natural-language/AI-generated text. This table exists only to make
detection results profile-scoped, persistent, and idempotent -- content
generation is a later, separate phase.
"""

from __future__ import annotations

from datetime import datetime
from extensions import db

# Plain constants (matching this project's existing style -- e.g.
# modules/models_ai_reports.py's AI_REPORT_STATUSES -- rather than a
# native SQLAlchemy/DB enum type, which is not used anywhere else in
# this codebase). Mirrors modules/alerts/planning_models.py::EventState
# member names exactly (NEW / ACTIVE / EXPIRED), without importing that
# enum -- this file must not import anything from the detection layer.
# Phase 1 never writes "EXPIRED" itself (the engine never returns an
# expired event to persist); the value is reserved here for a future
# detection-service phase that may explicitly close out a row once the
# engine stops reporting it.
ALERT_MICRO_EVENT_STATES = ("NEW", "ACTIVE", "EXPIRED")


class AlertMicroEvent(db.Model):
    __tablename__ = "alert_micro_events"

    id = db.Column(db.Integer, primary_key=True)

    # Existing AppUser.id stands in as the profile identifier -- same
    # convention as modules/models_ai_reports.py::AIReport.profile_id.
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("app_users.id"),
        nullable=False,
    )

    # The catalog's fixed event_id (modules/alerts/config/micro_events.json),
    # e.g. "financial_gain_opportunity". Longest current catalog id is 33
    # chars ("good_time_to_start_something_new"); sized with headroom.
    event_id = db.Column(db.String(64), nullable=False)

    # Denormalized copy of the catalog event's category (e.g.
    # "financial", "relationship") -- avoids re-reading
    # config/micro_events.json just to filter/display by category.
    category = db.Column(db.String(32), nullable=False)

    state = db.Column(db.String(10), nullable=False)      # ALERT_MICRO_EVENT_STATES
    priority = db.Column(db.String(10), nullable=False)   # "high" / "medium" / "low"
    confidence = db.Column(db.Float, nullable=False)       # 0.0-1.0, from confidence_engine.score()

    # Phase 4 addition -- LOW/MEDIUM/HIGH/CRITICAL (see
    # modules/alerts/severity_cooldown_registry.py::SEVERITY_LEVELS),
    # config-driven per event_id, never derived from confidence.
    # Nullable ONLY so a Phase 1/2/3-era row (created before this
    # column existed) never becomes invalid; every row written by
    # ProfileDetectionService from Phase 4 onward always sets this.
    severity = db.Column(db.String(10), nullable=True)

    # AI-Written Personalized Alert Content addition -- plain-English
    # facts (e.g. "Jupiter is currently transiting house 10") derived
    # from this event's actual triggered_rules + natal/transit/dasha
    # context (modules/alerts/alert_ai_content_service.py::
    # describe_triggered_facts()) -- computed and persisted for EVERY
    # detected event at detection time (cheap, no OpenAI call), NOT
    # gated on selection. This is what makes it possible to generate
    # AI content LATER, only for the final selected alert(s), without
    # needing to re-run detection/kundali calculation at that later
    # point (the live PlannedMicroEvent/EvaluationContext only exist
    # in-memory during one ProfileDetectionService.evaluate_profile()
    # call). NULL/empty means nothing describable fired for this row.
    triggered_facts = db.Column(db.JSON, nullable=True)

    # AI-Written Personalized Alert Content addition -- generated ONLY
    # for the FINAL, already-selected alert(s)
    # (modules/alerts/alert_ai_content_service.py::
    # ensure_ai_content_for_selected_rows(), called from the single
    # selection authority both alerts_scheduler.py and
    # routes_alerts_dashboard.py share -- see that function's own
    # docstring for the architectural gate this enforces: detection ->
    # selection -> THEN generation, never the reverse). NULL means "not
    # yet generated" (a brand-new/not-yet-selected row, or a generation
    # attempt that failed) -- modules/alerts/notification_content_adapter.py
    # falls back to the existing deterministic per-category template
    # whenever either is NULL, so a failed/never-run generation never
    # breaks delivery. Never touched by synchronize_profile_events() on
    # an ordinary continuing/"updated" row -- only set once, when
    # generation actually runs, and never re-generated for a row that
    # already has it (see ensure_ai_content_for_selected_rows()'s own
    # idempotency gate).
    ai_insight = db.Column(db.Text, nullable=True)   # SIGNAL -> real-life implication paragraph
    ai_action = db.Column(db.Text, nullable=True)     # -> practical action sentence
    ai_generated_at = db.Column(db.DateTime, nullable=True)

    # Phase 4 addition -- set ONLY by a future Phase 5 delivery adapter
    # after a CONFIRMED successful FCM send; NEVER written by anything
    # in Phase 1-4 (detection/lifecycle sync never touches this column
    # -- see persistence_repository.py::synchronize_profile_events()'s
    # own docstring). NULL means "never delivered".
    last_delivered_at = db.Column(db.DateTime, nullable=True)

    # Current/most recent detected window (ISO dates). Mutable -- see
    # persistence_repository.py for why these are updated in place
    # rather than used as part of the row's identity.
    active_from = db.Column(db.Date, nullable=False)
    active_until = db.Column(db.Date, nullable=False)

    # Set ONCE, at first insert, and never touched again -- the
    # permanent historical anchor of when this (profile, event) pair
    # was first ever detected.
    first_detected_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Bumped by the repository on EVERY persist/update call, regardless
    # of whether any other field actually changed -- "the engine last
    # confirmed this event was still relevant". Deliberately a plain
    # column (no ORM onupdate=) so only the repository, never an
    # incidental unrelated field edit, controls this value.
    last_evaluated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Generic row bookkeeping -- same convention as
    # modules/models_premium_subscription.py's CurrentEntitlement.
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )

    profile = db.relationship("AppUser", backref="alert_micro_events")

    __table_args__ = (
        # THE idempotency guarantee (see persistence_repository.py for
        # the full "why not active_from" reasoning) -- enforced by
        # Postgres itself, not just application code. Its own backing
        # index also serves per-profile lookups (profile_id is the
        # leading column), so no separate single-column profile_id
        # index is added -- same reasoning
        # modules/models_ai_reports.py::AIReport already documents for
        # its own composite unique constraint.
        db.UniqueConstraint(
            "profile_id", "event_id",
            name="uq_alert_micro_events_profile_event",
        ),
        # Metadata-only correction (Phase 2 Database Drift Blocker
        # Verification, Event Tracking project): this index has existed
        # live since this table's own creation (migrations/versions/
        # 5e64a21e77aa_...) and is actively used today --
        # persistence_repository.py orders by last_evaluated_at, and
        # `state` is filtered throughout this module -- but was never
        # declared here. No later migration ever dropped it (60982e2e358a
        # explicitly says it "does NOT touch... any index"). Declaring
        # it now makes this model describe the schema that already
        # exists; no DB change, no alert behavior change.
        db.Index(
            "ix_alert_micro_events_state_last_evaluated_at",
            "state", "last_evaluated_at",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "event_id": self.event_id,
            "category": self.category,
            "state": self.state,
            "priority": self.priority,
            "confidence": self.confidence,
            "severity": self.severity,
            "triggered_facts": self.triggered_facts,
            "ai_insight": self.ai_insight,
            "ai_action": self.ai_action,
            "ai_generated_at": self.ai_generated_at.isoformat() if self.ai_generated_at else None,
            "last_delivered_at": self.last_delivered_at.isoformat() if self.last_delivered_at else None,
            "active_from": self.active_from.isoformat() if self.active_from else None,
            "active_until": self.active_until.isoformat() if self.active_until else None,
            "first_detected_at": self.first_detected_at.isoformat() if self.first_detected_at else None,
            "last_evaluated_at": self.last_evaluated_at.isoformat() if self.last_evaluated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<AlertMicroEvent id={self.id} profile_id={self.profile_id} "
            f"event_id={self.event_id!r} state={self.state} "
            f"priority={self.priority} confidence={self.confidence}>"
        )
