# modules/payments/report_product_registry.py

"""
Paid Report Platform v1.0 -- R1 (Schema Foundation).

ReportProduct is the future single source of truth for which
report_slug values may be purchased, and which generator/prompt/model
produce them (see the Paid Report Platform v1.0 design doc, section 4:
Report/Product Registry). R1 adds ONLY the model/table -- no lookup
helper, no route, and no caller anywhere in this codebase reads from
this table yet. config/pricing.py::PRODUCT_PRICES remains the
exclusive, unmodified source of truth for pricing/validity until R2
seeds this table from it and R6 switches app.py to read from here
instead.

`model` is deliberately nullable, with no default, and no code
anywhere sets or reads it in R1. Jyotishasha's paid reports currently
generate via Luna, selected entirely inside tasks.py/
love_premium_task.py's own existing, hardcoded logic -- this column
must never be treated as "the configured model" until a later,
explicit phase deliberately wires it up; a NULL value here carries no
meaning today beyond "not yet configured."

`generator` is a small, closed dispatch-key vocabulary (see the design
doc's Generation Dispatch Registry, section 7) -- e.g. "standard_v1"
(tasks.py's existing pipeline) or "love_premium_v1"
(modules/love/love_report_router.py). No dispatcher reads this column
yet; R1 only reserves the column.
"""

from __future__ import annotations

from extensions import db


class ReportProduct(db.Model):
    __tablename__ = "report_products"

    report_slug = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(10), nullable=False, default="INR")
    active = db.Column(db.Boolean, nullable=False, default=True)
    generator = db.Column(db.String(50), nullable=False)
    prompt_template_id = db.Column(db.String(100), nullable=False)
    # Nullable/config-driven on purpose -- see module docstring. Must
    # never change or imply a change to the currently configured Luna
    # model selection in tasks.py/love_premium_task.py.
    model = db.Column(db.String(50), nullable=True)
    delivery_type = db.Column(db.String(30), nullable=False, default="EMAIL_PDF")
    required_input_schema = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.TIMESTAMP, nullable=False, default=db.func.now())

    def to_dict(self) -> dict:
        return {
            "report_slug": self.report_slug,
            "name": self.name,
            "price": self.price,
            "currency": self.currency,
            "active": self.active,
            "generator": self.generator,
            "prompt_template_id": self.prompt_template_id,
            "model": self.model,
            "delivery_type": self.delivery_type,
            "required_input_schema": self.required_input_schema,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<ReportProduct report_slug={self.report_slug!r} active={self.active}>"
