"""Verified-purchaser review rules (F10-P15).

Eligibility: the order behind a signed review token must have a Razorpay-
verified payment_status == "PAID", its report
generated (report_stage == "Ready") AND its PDF email actually SENT. One review
per order (UNIQUE order_id); buyers may edit it a limited number of times.

Moderation is content-based only and NEVER rating-based:
  * A review is auto-PUBLISHED unless automated checks find a link, email
    address, phone number or HTML markup -- then it is held PENDING for a
    human. A 1-star review is published exactly like a 5-star one.
  * A moderator may reject only with a fixed reason code (spam, abuse,
    personal data, off-topic, not a review). "Negative" is not a reason.
  * Deletion (F10-P17) is the privacy-request path: when the buyer asks, an
    admin removes the row entirely -- no copy or tombstone is kept.
Text is stored as plain text and must be rendered escaped by clients.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from extensions import db
from models import Order
from modules.payments.report_product_registry import ReportProduct
from modules.reviews.models import (
    STATUS_PENDING, STATUS_PUBLISHED, STATUS_REJECTED, ReportReview,
)
from modules.reviews.review_tokens import ReviewTokenError, email_matches, read_review_token

BODY_MIN, BODY_MAX = 20, 2000
DISPLAY_NAME_MAX = 40
MAX_EDITS = 3
PUBLIC_LIST_LIMIT = 20
REJECT_REASONS = ("SPAM", "ABUSIVE", "PERSONAL_DATA", "OFF_TOPIC", "NOT_A_REVIEW")

_LINK = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|in|net|org|io|co|me|info|xyz)\b)", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(?:\+?\d[\s-]?){7,}")
_HTML = re.compile(r"<\s*/?\s*[a-z!][^>]*>", re.I)
_NAME_OK = re.compile(r"^[^\W\d_]+(?:[ .'\-][^\W\d_]+)*\.?$", re.UNICODE)


class ReviewError(Exception):
    """`.code` and `.http_status` are safe to return to clients."""

    def __init__(self, code: str, http_status: int = 400):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


@dataclass
class EligibleOrder:
    order: Order
    product: ReportProduct


# ---------------------------------------------------------------- eligibility
def check_eligibility(token: str) -> EligibleOrder:
    try:
        order_id, email_hash = read_review_token(token)
    except ReviewTokenError as exc:
        raise ReviewError(exc.code, 503 if exc.code == "reviews_disabled" else 403)
    order = Order.query.get(order_id)
    if order is None or not email_matches(order.email, email_hash):
        raise ReviewError("invalid_token", 403)
    # payment_status is set to PAID only by Razorpay-verified finalization.
    if order.payment_status != "PAID":
        raise ReviewError("not_paid", 403)
    if order.report_stage != "Ready" or order.email_status != "SENT":
        raise ReviewError("not_delivered", 403)
    product = ReportProduct.query.get(order.product)
    if product is None:
        raise ReviewError("unknown_product", 404)
    return EligibleOrder(order=order, product=product)


def default_display_name(full_name: str | None) -> str:
    """'Ravi Kumar Sharma' -> 'Ravi S.' ; never the full name, never the email."""
    parts = [p for p in re.split(r"\s+", (full_name or "").strip()) if p]
    if not parts:
        return "Verified buyer"
    first = parts[0][:24]
    if len(parts) > 1 and parts[-1][:1].isalpha():
        return f"{first} {parts[-1][0].upper()}."
    return first


# ----------------------------------------------------------------- validation
def _clean_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    value = "".join(ch for ch in value if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def validate_submission(rating, body, display_name) -> tuple[int, str, str | None]:
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ReviewError("invalid_rating")
    if not isinstance(body, str):
        raise ReviewError("invalid_body")
    body = _clean_text(body)
    if not BODY_MIN <= len(body) <= BODY_MAX:
        raise ReviewError("invalid_body_length")
    name = None
    if display_name not in (None, ""):
        if not isinstance(display_name, str):
            raise ReviewError("invalid_display_name")
        name = _clean_text(display_name)
        if not name or len(name) > DISPLAY_NAME_MAX or not _NAME_OK.match(name):
            raise ReviewError("invalid_display_name")
    return rating, body, name


def content_flags(body: str, name: str | None = None) -> list[str]:
    text = f"{body}\n{name or ''}"
    flags = []
    if _LINK.search(text):
        flags.append("link")
    if _EMAIL.search(text):
        flags.append("email")
    if _PHONE.search(text):
        flags.append("phone")
    if _HTML.search(text):
        flags.append("html")
    return flags


# --------------------------------------------------------------------- submit
def public_review(review: ReportReview) -> dict:
    return {
        "id": review.id,
        "rating": review.rating,
        "body": review.body,
        "display_name": review.display_name,
        "language": review.language,
        "date": (review.published_at or review.created_at).strftime("%Y-%m-%d"),
    }


def own_review(review: ReportReview | None) -> dict | None:
    if review is None:
        return None
    return {
        "rating": review.rating,
        "body": review.body,
        "display_name": review.display_name,
        "status": review.status,
        "edits_left": max(0, MAX_EDITS - review.edit_count),
    }


def eligibility_payload(token: str) -> dict:
    eligible = check_eligibility(token)
    existing = ReportReview.query.filter_by(order_id=eligible.order.id).first()
    return {
        "eligible": True,
        "product": eligible.product.report_slug,
        "product_name": eligible.product.name,
        "language": eligible.order.language or "en",
        "default_display_name": default_display_name(eligible.order.name),
        "review": own_review(existing),
    }


def submit_review(token: str, rating, body, display_name=None) -> dict:
    eligible = check_eligibility(token)
    rating, body, name = validate_submission(rating, body, display_name)
    name = name or default_display_name(eligible.order.name)
    flags = content_flags(body, name)
    status = STATUS_PENDING if flags else STATUS_PUBLISHED
    now = datetime.utcnow()

    review = ReportReview.query.filter_by(order_id=eligible.order.id).with_for_update().first()
    if review is None:
        review = ReportReview(
            order_id=eligible.order.id, product=eligible.product.report_slug,
            language=(eligible.order.language or "en")[:10], edit_count=0, created_at=now,
        )
        db.session.add(review)
    else:
        if review.edit_count >= MAX_EDITS:
            raise ReviewError("edit_limit_reached", 409)
        review.edit_count += 1
        # An edit must not undo a moderator's rejection: it goes back to the queue.
        if review.status == STATUS_REJECTED:
            status = STATUS_PENDING
        review.moderation_reason = None
        review.moderated_at = None
    review.rating = rating
    review.body = body
    review.display_name = name
    review.status = status
    review.auto_flags = ",".join(flags) or None
    review.updated_at = now
    if status == STATUS_PUBLISHED and review.published_at is None:
        review.published_at = now
    db.session.commit()
    return own_review(review)


# --------------------------------------------------------------------- public
def product_summary(product_slug: str) -> dict:
    if ReportProduct.query.get(product_slug) is None:
        raise ReviewError("unknown_product", 404)
    published = ReportReview.query.filter_by(product=product_slug, status=STATUS_PUBLISHED)
    rows = published.with_entities(ReportReview.rating).all()
    count = len(rows)
    distribution = {str(star): 0 for star in range(1, 6)}
    for (rating,) in rows:
        distribution[str(rating)] += 1
    average = None
    if count:
        average = float((Decimal(sum(r for (r,) in rows)) / Decimal(count)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    latest = published.order_by(ReportReview.published_at.desc(), ReportReview.id.desc()).limit(PUBLIC_LIST_LIMIT).all()
    return {
        "product": product_slug,
        "review_count": count,
        "average_rating": average,
        "distribution": distribution,
        "reviews": [public_review(r) for r in latest],
    }


def product_availability() -> dict:
    """Public, minimal: which registry products are currently purchasable."""
    return {p.report_slug: bool(p.active) for p in ReportProduct.query.all()}


# ----------------------------------------------------------------- moderation
def list_for_moderation(status: str = STATUS_PENDING, limit: int = 100, order_id: int | None = None) -> list[dict]:
    """Admin queue. With `order_id` (to find a buyer's review for a privacy
    request), every status is searched and `status` is ignored."""
    query = ReportReview.query
    if order_id is not None:
        query = query.filter_by(order_id=order_id)
    else:
        if status not in (STATUS_PENDING, STATUS_PUBLISHED, STATUS_REJECTED):
            raise ReviewError("invalid_status")
        query = query.filter_by(status=status)
    rows = query.order_by(ReportReview.updated_at.desc()).limit(min(limit, 200)).all()
    return [
        {**public_review(r), "order_id": r.order_id, "product": r.product, "status": r.status, "auto_flags": r.auto_flags,
         "moderation_reason": r.moderation_reason, "edit_count": r.edit_count}
        for r in rows
    ]


def moderate(review_id: int, action: str, reason: str | None = None) -> dict:
    review = ReportReview.query.get(review_id)
    if review is None:
        raise ReviewError("not_found", 404)
    now = datetime.utcnow()
    if action == "delete":
        db.session.delete(review)
        db.session.commit()
        return {"id": review_id, "status": "DELETED", "moderation_reason": None}
    if action == "publish":
        review.status = STATUS_PUBLISHED
        review.moderation_reason = None
        if review.published_at is None:
            review.published_at = now
    elif action == "reject":
        if reason not in REJECT_REASONS:
            raise ReviewError("reject_reason_required")
        review.status = STATUS_REJECTED
        review.moderation_reason = reason
    else:
        raise ReviewError("invalid_action")
    review.moderated_at = now
    db.session.commit()
    return {"id": review.id, "status": review.status, "moderation_reason": review.moderation_reason}
