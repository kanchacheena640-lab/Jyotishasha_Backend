# modules/models_ai_reports.py

"""
AI Report Engine - Database Foundation (Phase 1)

Generic, reusable cache table for all Premium AI Insight modules
(Love, Career, Finance, Health, Family). Each segment produces the same
three report types (DNA, CURRENT_PHASE, DAILY_INSIGHT); rather than one
table per segment, this single table is shaped so future segments/
report types never require a schema change -- only new values for
`segment` / `report_type`.

Note: "Alerts" is NOT one of these segments. The Micro Event Engine
(modules/alerts/) is a separate, independent system -- rule-based, not
AI-generated, not cached here, not subscription/entitlement-gated the
same way these five are. It was previously listed as a placeholder 6th
segment below; that placeholder is removed to avoid the two being
confused with one another.

Identity: no dedicated Profile model exists yet in this backend, so
`profile_id` is a real foreign key to `app_users.id` (AppUser is the
existing model that already carries kundali/birth data). If a
dedicated Profile table is introduced later, this column is the one
that migrates.

Cache model: "generate once, read many, overwrite only when regeneration
is required." This is a CACHE, not a history/audit table -- there is
exactly ONE row per (profile_id, segment, report_type, language),
enforced by a database-level UNIQUE constraint. Regeneration UPDATEs
that same row in place; it never inserts a new one. `model_version` /
`prompt_version` / `generator_version` describe only the most recent
generation that produced the row's current `content_json`, not a history of
past generations.

This file introduces NO new business logic, no service, and no API. It
only defines the table.
"""

from datetime import datetime
from extensions import db


# ---------------------------------------------------------------
# Allowed values (plain constants, matching this project's existing
# style -- e.g. PLAN_PRICES / PRIORITY dicts elsewhere -- rather than
# native SQLAlchemy/DB enum types, which are not used anywhere else in
# this codebase).
# ---------------------------------------------------------------
AI_REPORT_SEGMENTS = (
    "LOVE",
    "CAREER",
    "FINANCE",
    "HEALTH",
    "FAMILY",
)

AI_REPORT_TYPES = (
    "DNA",
    "CURRENT_PHASE",
    "DAILY_INSIGHT",
    # CURRENT_TIMING -- the third report in the DNA -> CURRENT_PHASE ->
    # CURRENT_TIMING flow. A very short (2-3 sentence + Quick Tip)
    # continuation of CURRENT_PHASE, driven by fast-moving transits
    # only. Uses its own expiry policy (earliest of: a relevant
    # fast-moving planet's sign change, or 24 hours) rather than either
    # of the other two policies below -- see
    # services/ai_prediction_lab/current_timing_expiry.py. Purely
    # additive: DNA and CURRENT_PHASE's own values/behaviour above are
    # unchanged.
    "CURRENT_TIMING",
)

AI_REPORT_STATUSES = (
    # Generation state only -- staleness/servability is a separate
    # question, answered entirely by `expires_at` (see below). "EXPIRED"
    # is deliberately NOT a status: a row does not change status when it
    # expires, its expiry is just a timestamp comparison at read time.
    "PENDING",   # row exists as a placeholder; no completed generation yet
    "READY",     # last generation attempt succeeded; `content_json` is servable
    "FAILED",    # last generation attempt failed
)


class AIReport(db.Model):
    __tablename__ = "ai_reports"

    id = db.Column(db.Integer, primary_key=True)

    # Existing AppUser.id stands in as the profile identifier -- no
    # Profile model exists yet (see module docstring).
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey("app_users.id"),
        nullable=False,
        index=True,
    )

    # Which product vertical and which of the three report types.
    segment = db.Column(db.String(20), nullable=False, index=True)       # AI_REPORT_SEGMENTS
    report_type = db.Column(db.String(30), nullable=False, index=True)   # AI_REPORT_TYPES

    language = db.Column(db.String(10), nullable=False, default="en")

    # Cached AI output, stored as structured JSON (not raw text) so the
    # frontend can consume it directly, mirroring the AI Prediction
    # Lab's own report envelope shape (version / language / sections /
    # metadata).
    content_json = db.Column(db.JSON, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="PENDING")  # AI_REPORT_STATUSES

    # Provenance for whichever AI call most recently produced this row's
    # `content_json` -- lets a future Lifecycle Manager decide "does this
    # cached row need to be regenerated because the prompt/model/
    # generator pipeline changed," without needing to implement that
    # decision now. These are overwritten in place on every regeneration,
    # same as `content_json` -- they describe the current row, not a log.
    model_version = db.Column(db.String(50), nullable=True)
    prompt_version = db.Column(db.String(50), nullable=True)
    # Tracks which version of the context/prompt-building CODE PIPELINE
    # (as opposed to the .txt prompt template itself, or the OpenAI
    # model) produced this row. Justified because this exact backend has
    # already shown, within a single engagement, that its context
    # builders (e.g. adding 7th house / Moon / Mercury fields) evolve
    # independently of prompt wording -- a cache invalidation decision
    # keyed only on model_version/prompt_version would miss a
    # generator-side change that silently makes a cached content_json stale.
    generator_version = db.Column(db.String(50), nullable=True)

    generated_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    profile = db.relationship("AppUser", backref="ai_reports")

    __table_args__ = (
        # Enforces the cache invariant at the database level: exactly
        # ONE row per (profile_id, segment, report_type, language).
        # Regeneration must UPDATE this row, never INSERT a second one --
        # the database will reject any attempt to violate that. This
        # constraint's own backing index also serves as the fast
        # "find the cached report for this profile" lookup, so no
        # separate composite index is needed alongside it.
        db.UniqueConstraint(
            "profile_id", "segment", "report_type", "language",
            name="uq_ai_reports_profile_segment_type_language",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "segment": self.segment,
            "report_type": self.report_type,
            "language": self.language,
            "content_json": self.content_json,
            "status": self.status,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "generator_version": self.generator_version,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<AIReport id={self.id} profile_id={self.profile_id} "
            f"segment={self.segment} type={self.report_type} "
            f"lang={self.language} status={self.status}>"
        )
