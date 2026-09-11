"""N6 -- unified Bell read/write API. Campaign C (ADMIN_CAMPAIGN) items
live in the isolated notification_campaign_bell_items table (see
campaign_bell_models.py's docstring for the proven isolation reasons);
this module is the ONLY place that merges C with A/B's existing
UserNotification rows, and it does so strictly at READ time, for
presentation only. It never writes into, deletes from, or queries
UserNotification for selection/dedupe/cooldown/budget purposes -- it
only reads rows A/B's own existing code already produced, unmodified,
and applies the exact same visibility filters that
notifications/user_notification_routes.py already used before this file
existed (is_read/expires_at), now plus dismissed_at (new, additive,
touched by nothing in services/attention_policy.py or
services/event_scheduler.py).

Composite item ids ("ab:<int>" / "cc:<uuid>") let one mark-read/dismiss
call address either source without the two tables sharing a key space.

No "mark unread" exists here or anywhere else in this module, by design
(N6 v1 contract).
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from extensions import db
from notifications.notification_models import UserNotification
from notifications.campaign_bell_models import NotificationCampaignBellItem

BELL_ITEM_DEFAULT_EXPIRY = timedelta(days=7)
UNREAD_LOOKBACK = timedelta(hours=5)  # matches user_notification_routes.py's existing cutoff


def _is_syntactically_valid_uuid(raw_id):
    """A "cc:<raw_id>" id's raw_id must be a well-formed UUID string before
    it is ever used in a WHERE id = :raw_id query -- NotificationCampaignBellItem.id
    is a Postgres UUID column, and handing it a non-UUID string (a
    malformed/hand-typed/foreign-format item_id) makes psycopg2 raise
    InvalidTextRepresentation, an unhandled 500 rather than the safe "not
    found" every other malformed/foreign id already gets here (an unknown
    source prefix, an out-of-range int for "ab:", ...). Structural check
    only, same "reject cleanly, never let a bad id reach SQL" posture as
    db_safety.py's own parse-before-trust approach."""
    try:
        uuid.UUID(raw_id)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def create_bell_items_for_targets(execution, resolution, now):
    """Called from campaign_execution_service._freeze_targets() -- the
    ONE place delivery rows are ever created (send_now, reconfirm, and
    N5's scheduled dispatch all funnel through it) -- so a Bell item is
    guaranteed to exist for every frozen delivery target, created in the
    SAME transaction, independent of whatever the transport attempt
    later does or does not achieve (mirrors how A/B's own Bell rows are
    written regardless of push outcome). Writes ONLY to the isolated
    notification_campaign_bell_items table."""
    # NotificationCampaignDelivery.user_id is the AUTH User.id (see
    # saved_audience_recipient_resolver.py's Recipient dataclass);
    # UserNotification.user_id -- the id space every existing Bell query
    # (services/attention_policy.py, user_notification_routes.py's own
    # get_app_user_id()) actually filters by -- is the AppUser.id
    # ("profile_id" in the resolver). This Bell table's own `user_id`
    # column is therefore intentionally the AppUser id, matching
    # UserNotification's convention so the unified read layer addresses
    # both tables in the same identity space; `app_user_id` mirrors it
    # for symmetry with NotificationCampaignDelivery's own two columns.
    expires_at = execution.expires_at or (now + BELL_ITEM_DEFAULT_EXPIRY)
    for recipient in resolution.recipients:
        db.session.add(NotificationCampaignBellItem(
            execution_id=execution.id, campaign_id=execution.campaign_id,
            user_id=recipient.app_user_id, app_user_id=recipient.app_user_id,
            title=execution.approved_title, body=execution.approved_body, action=execution.approved_action,
            created_at=now, expires_at=expires_at,
        ))


def _ab_query(user_id, now):
    return (
        UserNotification.query
        .filter(UserNotification.user_id == user_id)
        .filter(UserNotification.dismissed_at.is_(None))
        .filter(or_(UserNotification.expires_at.is_(None), UserNotification.expires_at > now))
    )


def _cc_query(user_id, now):
    return (
        NotificationCampaignBellItem.query
        .filter(NotificationCampaignBellItem.user_id == user_id)
        .filter(NotificationCampaignBellItem.dismissed_at.is_(None))
        .filter(or_(NotificationCampaignBellItem.expires_at.is_(None), NotificationCampaignBellItem.expires_at > now))
    )


def _serialize_ab(row):
    return {
        "id": f"ab:{row.id}", "source": "AB", "title": row.title, "body": row.body,
        "data": row.data, "is_read": row.is_read,
        "created_at": row.created_at.astimezone(timezone.utc).isoformat() if row.created_at else None,
        "read_at": row.read_at.astimezone(timezone.utc).isoformat() if row.read_at else None,
    }


def _serialize_cc(row):
    # Deliberately NOT "data.action" or "action" -- A/B's own `data` dict
    # already uses "action" for a free-text AI-written string
    # (notification_content_adapter.py); reusing that key for Campaign
    # C's structured {type,target} navigation object would silently
    # collide two different meanings under one client-visible key.
    return {
        "id": f"cc:{row.id}", "source": "ADMIN_CAMPAIGN", "title": row.title, "body": row.body,
        "campaign_action": row.action, "is_read": row.is_read,
        # N6 Flutter finalization -- durable correlation identity for a
        # BELL tap's own notification_opened/destination_opened emission
        # (a push tap already gets these from the FCM data payload,
        # campaign_worker.py::_build_message(), untouched). Additive only:
        # no existing field renamed/removed, no existing test asserted
        # their absence.
        "campaign_id": row.campaign_id, "execution_id": row.execution_id,
        "created_at": row.created_at.astimezone(timezone.utc).isoformat() if row.created_at else None,
        "read_at": row.read_at.astimezone(timezone.utc).isoformat() if row.read_at else None,
    }


def list_unified_bell(user_id, now=None, limit=10):
    now = now or datetime.now(timezone.utc)
    cutoff = now - UNREAD_LOOKBACK
    ab_rows = _ab_query(user_id, now).filter(
        or_(UserNotification.is_read.is_(False), UserNotification.created_at > cutoff)
    ).order_by(UserNotification.created_at.desc()).limit(limit).all()
    cc_rows = _cc_query(user_id, now).filter(
        or_(NotificationCampaignBellItem.is_read.is_(False), NotificationCampaignBellItem.created_at > cutoff)
    ).order_by(NotificationCampaignBellItem.created_at.desc()).limit(limit).all()

    merged = [_serialize_ab(r) for r in ab_rows] + [_serialize_cc(r) for r in cc_rows]
    merged.sort(key=lambda item: item["created_at"] or "", reverse=True)
    return merged[:limit]


def unread_count(user_id, now=None):
    now = now or datetime.now(timezone.utc)
    ab_count = _ab_query(user_id, now).filter(UserNotification.is_read.is_(False)).count()
    cc_count = _cc_query(user_id, now).filter(NotificationCampaignBellItem.is_read.is_(False)).count()
    return ab_count + cc_count


def mark_read(user_id, item_id, now=None):
    now = now or datetime.now(timezone.utc)
    source, _, raw_id = item_id.partition(":")
    if source == "ab":
        if not raw_id.isdigit():
            return False
        row = UserNotification.query.filter_by(id=int(raw_id), user_id=user_id).first()
        if row is None:
            return False
        row.is_read = True
        row.read_at = now
    elif source == "cc":
        if not _is_syntactically_valid_uuid(raw_id):
            return False
        row = NotificationCampaignBellItem.query.filter_by(id=raw_id, user_id=user_id).first()
        if row is None:
            return False
        row.is_read = True
        row.read_at = now
    else:
        return False
    db.session.commit()
    return True


def mark_all_read(user_id, now=None):
    now = now or datetime.now(timezone.utc)
    UserNotification.query.filter_by(user_id=user_id, is_read=False).update(
        {"is_read": True, "read_at": now}, synchronize_session=False)
    NotificationCampaignBellItem.query.filter_by(user_id=user_id, is_read=False).update(
        {"is_read": True, "read_at": now}, synchronize_session=False)
    db.session.commit()


def dismiss_one(user_id, item_id, now=None):
    """Presentation-only removal from the tray. Never touches
    campaign/execution/delivery/attempt/attribution history -- for a
    Campaign C item this sets dismissed_at only on the Bell row; the
    NotificationCampaignDelivery/Attempt rows for the same recipient are
    completely untouched."""
    now = now or datetime.now(timezone.utc)
    source, _, raw_id = item_id.partition(":")
    if source == "ab" and raw_id.isdigit():
        row = UserNotification.query.filter_by(id=int(raw_id), user_id=user_id).first()
    elif source == "cc" and _is_syntactically_valid_uuid(raw_id):
        row = NotificationCampaignBellItem.query.filter_by(id=raw_id, user_id=user_id).first()
    else:
        row = None
    if row is None:
        return False
    row.dismissed_at = now
    db.session.commit()
    return True


def clear_all(user_id, now=None):
    """Presentation-only: dismisses every currently-visible item (both
    sources) for this user. Never deletes a row, never touches is_read,
    never touches any operational history table."""
    now = now or datetime.now(timezone.utc)
    _ab_query(user_id, now).update({"dismissed_at": now}, synchronize_session=False)
    _cc_query(user_id, now).update({"dismissed_at": now}, synchronize_session=False)
    db.session.commit()


def dismiss_bell_items_for_execution(execution_id, now=None):
    """P4.5 -- called from campaign_schedule_service.py's post-freeze
    cancellation of a provably-unsent FROZEN execution: presentation-
    only removal of every Bell row created for that execution's targets
    at freeze time (create_bell_items_for_targets()), exactly like an
    individual user's own dismiss_one()/clear_all() above -- sets
    dismissed_at only, never deletes a row, never touches is_read, never
    touches campaign/execution/delivery/attempt history. A user who
    already read/opened the item before cancellation keeps that read
    receipt; only future visibility in the Bell list changes.

    Deliberately does NOT call db.session.commit() itself, unlike
    dismiss_one()/clear_all() above -- the caller (_cancel_unsent_frozen())
    folds this into the SAME single commit as the execution/campaign/
    delivery state changes, so a crash between them can never leave a
    cancelled execution with a still-visible Bell item (or vice versa).

    Returns the number of rows dismissed (0 if none exist or all were
    already dismissed)."""
    now = now or datetime.now(timezone.utc)
    return (
        NotificationCampaignBellItem.query
        .filter_by(execution_id=execution_id)
        .filter(NotificationCampaignBellItem.dismissed_at.is_(None))
        .update({"dismissed_at": now}, synchronize_session=False)
    )
