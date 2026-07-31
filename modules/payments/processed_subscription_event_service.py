# modules/payments/processed_subscription_event_service.py

"""
ProcessedSubscriptionEventService -- Subscription Purchase System, S5.

The duplicate-event-protection architecture approved in the earlier
design review, now actually built: an atomic claim-then-finalize
ledger over modules/models_processed_subscription_events.py::
ProcessedSubscriptionEvent, keyed on (store, transaction_id) --
mirroring modules/payments/payment_service.py's own
_find_processed_payment/_try_claim/_finalize_claim trio exactly in
shape, for a store-agnostic subscription event instead of a one-time
Razorpay payment.

DELIBERATELY NOT WIRED to anything yet -- this phase builds the
ledger itself, standalone and independently testable, and does not
call it from PaymentService, GooglePlayProvider, AppleProvider, or any
webhook (none of which exist yet for subscriptions). A later phase
connects this to a real event-processing entry point once one exists.

    caller -> claim(store, transaction_id, event_type, profile_id)
                  |
                  |-- CLAIMED             -- caller now owns processing
                  |-- ALREADY_FINALIZED   -- return the stored result, do nothing
                  '-- ALREADY_IN_PROGRESS -- concurrent claim OR a previously
                                             failed, never-finalized attempt --
                                             do nothing either way

Both "genuinely still being processed right now" and "failed last
time and was left unfinished" produce the identical
ALREADY_IN_PROGRESS outcome, on purpose: this ledger cannot tell them
apart from stored state alone (there is no heartbeat/timestamp-based
staleness detection here, unlike the report-purchase pipeline's
Processing-abandonment heuristic -- building that is a distinct,
separate hardening concern, out of scope for this phase), and treating
both as "do not reprocess automatically" is the same conservative
choice already validated for report purchases: automatic reprocessing
of something that might still be running is never safe, so both cases
default to refusing rather than guessing which one this is.

Idempotency key -- store + the store's own PER-EVENT identifier:
    Google Play -- the specific orderId for one charge (never the
                   linked/original purchase token, which is stable
                   across a subscription's entire lifetime and would
                   make every renewal collide with the first purchase)
    Apple       -- transactionId for one transaction (never
                   originalTransactionId, same reasoning)
Enforced by this table's own UNIQUE(store, transaction_id) constraint
-- the actual mechanism, not just this class's discipline about which
field it reads.

Failure handling: claim() only ever creates an unfinished row
(response_payload=None). finalize() is the only method that ever fills
it in, and only the caller who received CLAIMED should ever call it.
If the caller's own business processing raises before calling
finalize(), the claim is left exactly as-is -- there is no
release()/delete() method in this file at all. A future retry for the
same (store, transaction_id) will correctly see ALREADY_IN_PROGRESS and
refuse, exactly like ProcessedPayment's own claim is deliberately left
unfinished on failure (see PaymentService's Phase 4 self-correction)
rather than being auto-released for an unprotected retry to redo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.models_processed_subscription_events import ProcessedSubscriptionEvent


class SubscriptionEventClaimOutcome:
    CLAIMED = "CLAIMED"
    ALREADY_FINALIZED = "ALREADY_FINALIZED"
    ALREADY_IN_PROGRESS = "ALREADY_IN_PROGRESS"


@dataclass
class SubscriptionEventClaimResult:
    outcome: str  # SubscriptionEventClaimOutcome
    store: str
    transaction_id: str
    stored_response: Optional[Dict[str, Any]] = None  # populated only for ALREADY_FINALIZED


class ProcessedSubscriptionEventService:
    # ------------------------------------------------------------
    # Public entry point -- claim-then-finalize, packaged as one call
    # so a future caller doesn't need to re-derive the
    # find-then-try-then-recheck sequence PaymentService already
    # proved correct for report purchases.
    # ------------------------------------------------------------
    def claim(
        self,
        *,
        store: str,
        transaction_id: str,
        event_type: Optional[str] = None,
        profile_id: Optional[int] = None,
    ) -> SubscriptionEventClaimResult:
        existing = self.find_existing(store, transaction_id)
        if existing is not None:
            return self._outcome_for_existing(existing, store, transaction_id)

        if self._try_insert_claim(
            store=store, transaction_id=transaction_id,
            event_type=event_type, profile_id=profile_id,
        ):
            return SubscriptionEventClaimResult(
                outcome=SubscriptionEventClaimOutcome.CLAIMED,
                store=store, transaction_id=transaction_id,
            )

        # Lost the atomic race -- some other caller's INSERT won
        # between our find_existing() read above and our own INSERT
        # attempt (the UNIQUE constraint is what actually decided
        # this, not this line). Re-check to report an accurate
        # outcome rather than a generic refusal.
        existing_after_race = self.find_existing(store, transaction_id)
        if existing_after_race is not None:
            return self._outcome_for_existing(existing_after_race, store, transaction_id)

        # Should not be reachable (a failed insert always means a row
        # now exists), but never guess -- fail closed.
        return SubscriptionEventClaimResult(
            outcome=SubscriptionEventClaimOutcome.ALREADY_IN_PROGRESS,
            store=store, transaction_id=transaction_id,
        )

    def finalize(
        self,
        *,
        store: str,
        transaction_id: str,
        response_payload: Dict[str, Any],
        profile_id: Optional[int] = None,
    ) -> None:
        """Only the caller that received CLAIMED from claim() should
        ever call this. Silently a no-op if the row somehow doesn't
        exist (it always should, if this is called correctly) --
        finalize() never creates a claim, only completes one."""
        claim_row = self.find_existing(store, transaction_id)
        if claim_row is None:
            return
        claim_row.response_payload = response_payload
        if profile_id is not None:
            claim_row.profile_id = profile_id
        db.session.commit()

    # ------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------
    def find_existing(self, store: str, transaction_id: str) -> Optional[ProcessedSubscriptionEvent]:
        if not transaction_id:
            return None
        return ProcessedSubscriptionEvent.query.filter_by(
            store=store, transaction_id=transaction_id,
        ).first()

    def _try_insert_claim(
        self, *, store: str, transaction_id: str,
        event_type: Optional[str], profile_id: Optional[int],
    ) -> bool:
        row = ProcessedSubscriptionEvent(
            store=store, transaction_id=transaction_id,
            event_type=event_type, profile_id=profile_id,
        )
        db.session.add(row)
        try:
            db.session.commit()
            return True
        except IntegrityError:
            db.session.rollback()
            return False

    @staticmethod
    def _outcome_for_existing(
        existing: ProcessedSubscriptionEvent, store: str, transaction_id: str,
    ) -> SubscriptionEventClaimResult:
        if existing.response_payload is not None:
            return SubscriptionEventClaimResult(
                outcome=SubscriptionEventClaimOutcome.ALREADY_FINALIZED,
                store=store, transaction_id=transaction_id,
                stored_response=existing.response_payload,
            )
        # Unfinished -- either genuinely still being processed right
        # now, or a previous attempt failed and was correctly left
        # unfinished (never auto-released). Both refuse identically --
        # see module docstring for why that's the safe default.
        return SubscriptionEventClaimResult(
            outcome=SubscriptionEventClaimOutcome.ALREADY_IN_PROGRESS,
            store=store, transaction_id=transaction_id,
        )
