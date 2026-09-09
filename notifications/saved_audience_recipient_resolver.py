"""Read-only Admin Campaign candidate resolution. No sender or campaign imports.

Uses a private REPEATABLE READ / READ ONLY transaction, so membership and global
token ownership see one committed snapshot without committing caller work.
Tokens live only in the returned internal targets; use admin_safe() for previews.
"""
from collections import Counter
from dataclasses import dataclass, field

from flask import current_app
from sqlalchemy import func, text

from extensions import db
from modules.auth.models import User
from modules.models_user import AppUser
from modules.services import admin_users_service, saved_audience_service
from modules.services.saved_audience_criteria import validate_criteria, CriteriaValidationError

DB_BATCH_SIZE = 500
ABSOLUTE_CEILING = 50_000
EXCLUSION_REASONS = (
    "missing_identity_bridge", "missing_profile", "missing_token",
    "preference_suppressed", "duplicate_target",
)


class RecipientResolutionError(RuntimeError):
    """Sanitized, machine-readable failure. Never a successful empty audience."""
    def __init__(self, code, *, matched_user_count=None):
        self.code = code
        self.matched_user_count = matched_user_count
        self.eligible_recipient_count = None  # not computed on aborted resolution
        super().__init__(code)


@dataclass(frozen=True)
class Recipient:
    user_id: int
    app_user_id: int
    firebase_uid: str = field(repr=False)
    fcm_token: str = field(repr=False)


@dataclass(frozen=True)
class RecipientResolution:
    saved_audience_id: int
    matched_user_count: int
    recipients: tuple[Recipient, ...] = field(repr=False)
    exclusion_counts: tuple[tuple[str, int], ...]
    is_all_users: bool

    @property
    def eligible_recipient_count(self):
        return len(self.recipients)

    @property
    def excluded_recipient_count(self):
        return sum(count for _, count in self.exclusion_counts)

    def admin_safe(self):
        """Counts only: no token, UID, recipient list or durable token snapshot."""
        return {
            "saved_audience_id": self.saved_audience_id,
            "matched_user_count": self.matched_user_count,
            "eligible_recipient_count": self.eligible_recipient_count,
            "excluded_recipient_count": self.excluded_recipient_count,
            "exclusion_counts": dict(self.exclusion_counts),
            "is_all_users": self.is_all_users,
            "absolute_ceiling": ABSOLUTE_CEILING,
            "safety_ceiling_exceeded": False,
            "policy_version": "N1-P1-v1",
        }


def _batches(values):
    for start in range(0, len(values), DB_BATCH_SIZE):
        yield values[start:start + DB_BATCH_SIZE]


def _load_users(ids):
    return db.session.query(User.id, User.firebase_uid).filter(User.id.in_(ids)).all()


def _load_profiles(uids):
    # Aggregate before returning rows: even corrupt duplicate profiles cannot
    # cause an unbounded ORM load or an arbitrary first-profile selection.
    return db.session.query(
        AppUser.firebase_uid, func.count(AppUser.id),
        func.min(AppUser.id), func.min(AppUser.fcm_token),
    ).filter(AppUser.firebase_uid.in_(uids)).group_by(AppUser.firebase_uid).all()


def _token_owners(tokens):
    # Global ownership, not only the matched audience or current bridge batch.
    # Treat surrounding whitespace consistently for duplicate detection.
    normalized = func.regexp_replace(AppUser.fcm_token, r"^\s+|\s+$", "", "g")
    return dict(db.session.query(normalized, func.count(AppUser.id)).filter(
        normalized.in_(tokens),
    ).group_by(normalized).all())


def _explicitly_disabled_user_ids(ids):
    """No applicable denial/category preference source exists in current SQL.

    Absence is not consent and not suppression. This bounded policy seam must
    be wired to any future authoritative source; its failures must propagate.
    Existing automatic-event switches are event scheduling, not account opt-out.
    """
    return frozenset()


def _resolve(saved_audience_id, approved_criteria=None):
    try:
        audience = saved_audience_service.get_audience(saved_audience_id)
    except saved_audience_service.AudienceNotFoundError:
        raise RecipientResolutionError("AUDIENCE_NOT_FOUND") from None
    if not audience.is_active:
        raise RecipientResolutionError("AUDIENCE_INACTIVE")
    # N5 (Section 5.36) -- an explicitly supplied approved_criteria
    # snapshot is used INSTEAD of this audience's current (possibly
    # since-edited) criteria, so a campaign approved/scheduled against
    # criteria A can never silently adopt a later edit to criteria B.
    # The audience row itself is still loaded and its is_active/existence
    # checked above -- N1's "missing/inactive audience blocks dispatch"
    # requirement is about the AUDIENCE'S OWN availability, not its
    # current filter content, and is unaffected by which criteria this
    # call resolves against. Default (None) is byte-identical to the
    # pre-N5 behavior: resolve using this audience's own current criteria.
    criteria_to_use = audience.criteria if approved_criteria is None else approved_criteria
    # JSON booleans/floats must not pass Python's True == 1 == 1.0 equality
    # at this delivery boundary. All filter validation stays in the authority.
    if not isinstance(criteria_to_use, dict) or type(criteria_to_use.get("version")) is not int:
        raise RecipientResolutionError("INVALID_AUDIENCE_CRITERIA")
    try:
        filters = validate_criteria(criteria_to_use, authoring=False)
    except CriteriaValidationError:
        raise RecipientResolutionError("INVALID_AUDIENCE_CRITERIA") from None
    # This is the frozen SavedAudience membership implementation. The existing
    # service has no audience.resolve_user_ids method; its canonical function
    # lives in admin_users_service and shares _apply_admin_users_filters.
    ids = admin_users_service.resolve_user_ids(**filters)
    if any(type(value) is not int or value <= 0 for value in ids):
        raise RecipientResolutionError("INVALID_CANONICAL_IDENTITY")
    ids = sorted(set(ids))
    matched = len(ids)
    if matched > ABSOLUTE_CEILING:
        raise RecipientResolutionError("SAFETY_CEILING_EXCEEDED", matched_user_count=matched)

    excluded = Counter({reason: 0 for reason in EXCLUSION_REASONS})
    candidates = []
    for batch in _batches(ids):
        accounts = dict(_load_users(batch))
        uids = sorted({uid for uid in accounts.values() if uid and uid.strip()})
        profiles = {uid: (count, profile_id, token) for uid, count, profile_id, token in _load_profiles(uids)} if uids else {}
        if any(count != 1 for count, _, _ in profiles.values()):
            raise RecipientResolutionError("AMBIGUOUS_APP_USER", matched_user_count=matched)
        disabled = _explicitly_disabled_user_ids(batch)
        if not isinstance(disabled, (set, frozenset)) or not disabled <= set(batch):
            raise RecipientResolutionError("INVALID_POLICY_RESULT", matched_user_count=matched)
        for user_id in batch:
            uid = accounts.get(user_id)
            if not uid or not uid.strip():
                excluded["missing_identity_bridge"] += 1
            elif uid not in profiles:
                excluded["missing_profile"] += 1
            else:
                _, profile_id, token = profiles[uid]
                if not token or not token.strip():
                    excluded["missing_token"] += 1
                elif user_id in disabled:
                    excluded["preference_suppressed"] += 1
                else:
                    candidates.append(Recipient(user_id, profile_id, uid, token.strip()))

    local_owners = Counter(target.fcm_token for target in candidates)
    eligible = []
    for batch in _batches(candidates):
        owners = _token_owners(sorted({target.fcm_token for target in batch}))
        for target in batch:
            if owners.get(target.fcm_token) != 1 or local_owners[target.fcm_token] != 1:
                excluded["duplicate_target"] += 1
            else:
                eligible.append(target)
    # eligible <= matched by construction. Never truncate either count.
    result = RecipientResolution(saved_audience_id, matched, tuple(eligible),
                                 tuple((key, excluded[key]) for key in EXCLUSION_REASONS), not filters)
    if matched != result.eligible_recipient_count + result.excluded_recipient_count:
        raise RecipientResolutionError("COUNT_INTEGRITY_ERROR")
    return result


def resolve_saved_audience_recipients(saved_audience_id, *, approved_criteria=None):
    """Resolve current committed state. Returns internal, ephemeral candidates.

    Above 50k raises SAFETY_CEILING_EXCEEDED with the exact matched count and
    eligible count unknown. No bridge processing or silent truncation follows.
    Future execution must revalidate ownership; this result is not approval.

    `approved_criteria` (N5, keyword-only, default None): when provided,
    membership is resolved against THIS exact criteria snapshot rather
    than the SavedAudience row's own current (possibly since-edited)
    criteria -- the narrow, backward-compatible extension N5's dispatch
    path requires to honor "approved definition immutable, membership
    live" without duplicating _apply_admin_users_filters()/resolve_user_ids()
    anywhere. Every existing caller (all of N4, and any call that omits
    this argument) is completely unaffected: omitting it resolves against
    the audience's current criteria exactly as before N5.
    """
    if type(saved_audience_id) is not int or saved_audience_id <= 0:
        raise RecipientResolutionError("INVALID_AUDIENCE_ID")
    if approved_criteria is not None and not isinstance(approved_criteria, dict):
        raise RecipientResolutionError("INVALID_AUDIENCE_CRITERIA")
    try:
        with current_app._get_current_object().app_context():
            db.session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            db.session.execute(text("SET TRANSACTION READ ONLY"))
            return _resolve(saved_audience_id, approved_criteria)
    except RecipientResolutionError:
        raise
    except Exception:
        # Database/dependency diagnostics can contain query parameters/tokens.
        # Do not attach or log those as ordinary resolver error diagnostics.
        raise RecipientResolutionError("RESOLUTION_UNAVAILABLE") from None
