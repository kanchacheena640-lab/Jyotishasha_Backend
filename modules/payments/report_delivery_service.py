"""Truthful, temporary-file delivery for generated paid-report PDFs."""

from __future__ import annotations

import os
from datetime import datetime

from email_utils import send_email
from extensions import db
from models import Order


def pdf_artifact_is_usable(pdf_path: str | None) -> bool:
    """Return True only for a readable, non-empty PDF artifact."""
    if not pdf_path or not os.path.isfile(pdf_path):
        return False
    try:
        with open(pdf_path, "rb") as artifact:
            return artifact.read(5) == b"%PDF-" and bool(artifact.read(1))
    except OSError:
        return False


def delivery_message(order: Order) -> tuple[str, str]:
    if order.product == "relationship_future_report":
        return (
            "Your Love & Marriage Life Report",
            f"Hello {order.name},\n\nYour Love & Relationship report is ready.",
        )
    product_name = (order.product or "report").replace("_", " ").replace("-", " ").title()
    return (
        f"Your {product_name} Report",
        f"Hello {order.name},\n\nPlease find attached your personalized astrology report.\n\nRegards,\nTeam Jyotishasha",
    )


def deliver_generated_report(order_id: int, pdf_path: str, *, send_email_fn=send_email) -> None:
    """Send one generated PDF and durably record the actual SMTP outcome.

    The file is temporary. On success the database pointer is cleared before
    best-effort cleanup, so a Ready/SENT order never advertises a dead path.
    On failure the path is retained when present, allowing an email-only retry.
    """
    order = Order.query.get(order_id)
    if order is None:
        raise RuntimeError(f"Order {order_id} not found during report delivery")

    attempt_at = datetime.utcnow()
    order.email_last_attempt_at = attempt_at
    db.session.commit()

    subject, body = delivery_message(order)
    try:
        send_email_fn(order.email, subject, body, pdf_path)
    except Exception as exc:
        db.session.rollback()
        failed_order = Order.query.get(order_id)
        if failed_order is not None:
            failed_order.email_status = "FAILED"
            failed_order.email_last_attempt_at = attempt_at
            failed_order.email_error = str(exc)[:500]
            db.session.commit()
        raise

    sent_order = Order.query.get(order_id)
    if sent_order is None:
        raise RuntimeError(f"Order {order_id} disappeared after report delivery")
    sent_order.email_status = "SENT"
    sent_order.email_last_attempt_at = attempt_at
    sent_order.email_sent_at = attempt_at
    sent_order.email_error = None
    if sent_order.pdf_url == pdf_path:
        sent_order.pdf_url = None
    db.session.commit()

    try:
        os.remove(pdf_path)
    except FileNotFoundError:
        pass
    except OSError:
        # Delivery is already confirmed and the DB no longer advertises this
        # temporary path. A cleanup failure must not falsify delivery state.
        pass
