from extensions import db
from datetime import datetime

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    product = db.Column(db.String(100), nullable=False)
    dob = db.Column(db.String(20))
    tob = db.Column(db.String(20))
    pob = db.Column(db.String(100))
    status = db.Column(db.String(20), default="PENDING")
    created_at = db.Column(db.DateTime, default=datetime.now)
    language = db.Column(db.String(10), default="en")
    report_stage = db.Column(db.String(50), default="Pending")  # Pending, Processing, Ready, Failed -- see tasks.py / modules/love/love_premium_task.py
    # Set whenever report_stage becomes "Processing" (initial dispatch or a
    # Failed/abandoned-Processing resume) -- Payment Hardening Blocker 02:
    # the only signal that lets ReconciliationService tell a genuinely
    # in-flight report apart from one abandoned by a crashed/restarted
    # process. See modules/payments/reconciliation_service.py.
    processing_started_at = db.Column(db.DateTime, nullable=True)
    pdf_url = db.Column(db.String(255))
    latitude = db.Column(db.String)
    longitude = db.Column(db.String)
    partner_payload = db.Column(db.JSON, nullable=True)

    # Task 17B -- email delivery-ATTEMPT truth, deliberately separate from
    # report_stage (which only ever means "was the PDF generated"). Values:
    # NOT_ATTEMPTED (default -- no SMTP attempt has completed yet, whether
    # because the report isn't Ready yet or the attempt hasn't run),
    # SENT (smtplib's send_message() returned without raising -- our own
    # SMTP interaction with Gmail completed; this is NOT inbox-delivery or
    # open confirmation, which this integration has no way to know), FAILED
    # (the SMTP attempt raised), SENDING (an admin retry atomically owns the
    # delivery). See email_utils.py::send_email() and
    # tasks.py's own dedicated try/except around the email step for where
    # these are set -- never inferred from report_stage.
    email_status = db.Column(db.String(20), nullable=False, default="NOT_ATTEMPTED")
    # Set immediately before each SMTP attempt (fresh vs resend alike) --
    # always reflects the most recent attempt, whatever its outcome.
    email_last_attempt_at = db.Column(db.DateTime, nullable=True)
    # Set only on a successful attempt (email_status == "SENT"). Left
    # unchanged by a later failed resend attempt -- a subsequent FAILED
    # attempt does not erase the record of when a prior send last
    # genuinely succeeded.
    email_sent_at = db.Column(db.DateTime, nullable=True)
    # Bounded, sanitized failure detail for the most recent FAILED attempt
    # only (cleared on a later SENT). Never the SMTP password/credentials
    # (smtplib's own exception text never contains them); str(exc) is
    # truncated defensively regardless, since this column's only job is
    # "give an operator a clue," not "reproduce the full traceback."
    email_error = db.Column(db.String(500), nullable=True)

    # Paid Report Platform v1.0 -- R1 (Schema Foundation). Purely
    # additive; no existing column above is touched, and nothing yet
    # reads or writes these three columns (that begins at R3+ -- see
    # migrations/versions/7064abce6f23_r1_add_report_products_table_
    # and_order_.py for the full rationale, including how historical
    # rows were backfilled). `product` remains the physical, canonical
    # report_slug column for backward compatibility -- no new
    # report_slug column is introduced here.
    #
    # razorpay_order_id: the future reconciliation key an Order will be
    # looked up by (once R6 creates the Order BEFORE calling Razorpay,
    # instead of today's after-the-fact OrderService.
    # create_paid_report_order()). Unique when set -- one Order maps to
    # at most one Razorpay order. NULL for every historical row (no
    # existing code path has ever recorded this value anywhere).
    razorpay_order_id = db.Column(db.String(64), nullable=True)
    # Denormalized for observability/admin debugging once populated;
    # modules/models_processed_payments.py::ProcessedPayment remains the
    # actual idempotency ledger keyed on this value -- this column is a
    # convenience mirror, never a second source of truth.
    razorpay_payment_id = db.Column(db.String(64), nullable=True)
    # CREATED / PAYMENT_PENDING / PAID / PAYMENT_FAILED -- distinct from
    # the legacy `status` column above, which is left completely
    # untouched (still set to "PAID" by the current, unmodified
    # OrderService) for backward compatibility with every existing
    # reader of `.status`. Historical rows were backfilled to "PAID"
    # wherever status == "PAID" (see the migration's own docstring for
    # why this is safe); the "CREATED" default only applies going
    # forward, and until R3-R6 wire the new pre-payment order-creation
    # flow, every NEW Order the current, unmodified code creates will
    # still show payment_status="CREATED" alongside status="PAID" -- a
    # known, deliberate, temporary inconsistency for the R1-R6
    # transition window, not a bug.
    payment_status = db.Column(db.String(20), nullable=False, default="CREATED")

    # Paid Report Platform v1.0 -- R4. Immutable expected-price snapshot
    # in paise (never a float -- see migrations/versions/0518660f81fc's
    # own docstring for why no float/rupee representation is used).
    # NULL for every historical, pre-R4 Order (no safe backfill exists);
    # always populated by OrderService.create_pending_order() (R3,
    # updated in R4) as ReportProduct.price * 100 for every NEW-platform
    # Order. Once set, no payment callback may ever change it --
    # PaymentFinalizationService (R4) only ever reads it for comparison
    # against a payment's own captured amount.
    amount_paise = db.Column(db.Integer, nullable=True)

class AstroEvent(db.Model):
    __tablename__ = "astro_events"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, nullable=False)
    date = db.Column(db.Date, nullable=False)
    type = db.Column(db.Text)
    priority = db.Column(db.Integer, default=1)
    notify_before_days = db.Column(db.Integer, default=0)
    notify_same_day = db.Column(db.Boolean, default=True)
    notify_time = db.Column(db.Time)
    meta = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.now)
