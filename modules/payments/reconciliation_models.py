# modules/payments/reconciliation_models.py

"""
Plain constants and dataclasses for the Admin Reconciliation Foundation
(Payment Hardening Phase 7). Same role as payment_models.py: this file
only defines the shape everything else agrees on, no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class ReconciliationAction:
    """
    What a human (or a future admin tool) should be told about a stuck
    or otherwise notable Order, and what ReconciliationService.resume()
    will actually do about it:
        NO_ACTION          -- report_stage is "Pending"; the pipeline
                              was never dispatched (or hasn't reached
                              its first checkpoint yet). Not stuck --
                              nothing to reconcile.
        RESUME_ALLOWED     -- report_stage is "Failed"; the pipeline
                              definitively finished failing. Safe to
                              resume for the existing Order.
        ALREADY_RUNNING    -- report_stage is "Processing"; the
                              pipeline is actively running right now.
                              Never resume -- doing so risks a
                              duplicate GPT call/PDF write/email send.
        ALREADY_COMPLETED  -- report_stage is "Ready"; the pipeline
                              already fully succeeded. Nothing to do.
        INVALID_STATE      -- no Order exists for the given id, or its
                              report_stage is not one of the four
                              recognized values (e.g. missing, or the
                              legacy "Regenerating" value written by
                              routes/admin_orders.py's older resend
                              endpoint). Refuse to guess a safe action.
    """
    NO_ACTION = "NO_ACTION"
    RESUME_ALLOWED = "RESUME_ALLOWED"
    ALREADY_RUNNING = "ALREADY_RUNNING"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    INVALID_STATE = "INVALID_STATE"


@dataclass
class ReconciliationDecision:
    """Structured, read-only classification of one Order's recovery
    state -- never a raw ORM model or a bare string across this
    boundary, matching this codebase's existing house style."""
    order_id: Optional[int]
    report_stage: Optional[str]
    action: str       # ReconciliationAction
    reason: str


@dataclass
class ReconciliationResumeResult:
    """Outcome of actually attempting a resume. resumed=False covers
    every non-action case (already running/completed/invalid state, or
    a concurrent request already won ownership) -- the decision field
    always explains why."""
    order_id: Optional[int]
    resumed: bool
    decision: ReconciliationDecision
    task_id: Optional[str] = None
