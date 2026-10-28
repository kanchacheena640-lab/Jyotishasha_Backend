"""ReportReview -- one verified-purchaser review per paid order (F10-P15).

A review can only exist for an Order that was genuinely paid and whose report
PDF was actually delivered (see review_service.check_eligibility). The order
id is UNIQUE, so a buyer has exactly one review per purchase; edits update the
same row. No customer email, phone or birth data is ever copied here -- only
the public display name the buyer chose (or a privacy-safe default).
"""
from datetime import datetime

from extensions import db

STATUS_PUBLISHED = "PUBLISHED"
STATUS_PENDING = "PENDING"      # held for a human: automated content flags only, never the rating
STATUS_REJECTED = "REJECTED"    # by a moderator, with a recorded reason code
REVIEW_STATUSES = (STATUS_PUBLISHED, STATUS_PENDING, STATUS_REJECTED)


class ReportReview(db.Model):
    __tablename__ = "report_reviews"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True)
    product = db.Column(db.String(100), nullable=False, index=True)
    rating = db.Column(db.SmallInteger, nullable=False)
    body = db.Column(db.Text, nullable=False)
    display_name = db.Column(db.String(40), nullable=False)
    language = db.Column(db.String(10), nullable=False, default="en")
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING, index=True)
    # Machine flags that sent the review to PENDING (e.g. "link,phone"); never rating-based.
    auto_flags = db.Column(db.String(200), nullable=True)
    moderation_reason = db.Column(db.String(40), nullable=True)
    moderated_at = db.Column(db.DateTime, nullable=True)
    edit_count = db.Column(db.SmallInteger, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    published_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_report_reviews_rating_1_5"),
        db.CheckConstraint("status IN ('PUBLISHED','PENDING','REJECTED')", name="ck_report_reviews_status"),
        db.Index("ix_report_reviews_product_status", "product", "status"),
    )
