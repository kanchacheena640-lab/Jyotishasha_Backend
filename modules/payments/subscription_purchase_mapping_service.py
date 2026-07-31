# modules/payments/subscription_purchase_mapping_service.py

"""
SubscriptionPurchaseMappingService -- RTDN identity resolution
(Subscription Purchase System, S7E).

Owns every read/write of SubscriptionPurchaseMapping
(modules/models_subscription_purchase_mapping.py). Two call sites:

    PaymentService (initial purchase, modules/payments/payment_service.py)
        -> upsert()             -- record which profile this
                                    purchase_token belongs to, as soon
                                    as it's known, regardless of
                                    whether activation itself succeeds.

    RTDN endpoint (routes/routes_rtdn.py)
        -> resolve_profile_id() -- look up which profile a bare
                                    purchase_token belongs to, before
                                    calling SubscriptionService.
                                    process_webhook_event() (S7B,
                                    unmodified -- this file supplies
                                    the profile_id its payload has
                                    always accepted).

Concurrency: upsert() is race-safe for two callers upserting the same
purchase_token at once (e.g. a duplicate purchase confirmation and an
RTDN both racing) using the exact same insert-first/catch-IntegrityError/
fall-back-to-update technique already proven in
ProcessedSubscriptionEventService._try_insert_claim -- the table's own
UNIQUE(purchase_token) constraint is what actually decides the race,
not any locking in this class.

Atomicity with the entitlement write (Subscription Purchase System --
S15): upsert()'s `commit` parameter (default True, unchanged for any
standalone caller) lets PaymentService stage this write
(commit=False -- flushed, so the UNIQUE(purchase_token) race check
above still fires exactly as before, just without ending the
transaction) and have it committed together with the entitlement
write that follows, inside the SAME db.session -- both succeed or
both roll back together. See payment_service.py::
_apply_subscription_business_effect() for the actual composition.

Token replacement: resolve_profile_id() falls back to a
linked_purchase_token lookup when a direct purchase_token match
misses -- see the model's own docstring for why that's a pure
DB lookup rather than a second Google verification call.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.models_subscription_purchase_mapping import SubscriptionPurchaseMapping

_ACTIVE = "ACTIVE"
_SUPERSEDED = "SUPERSEDED"


class SubscriptionPurchaseMappingService:
    # ------------------------------------------------------------
    # Write
    # ------------------------------------------------------------
    def upsert(
        self,
        *,
        purchase_token: str,
        profile_id: int,
        provider: str,
        user_id: Optional[int] = None,
        product_id: Optional[str] = None,
        order_id: Optional[str] = None,
        linked_purchase_token: Optional[str] = None,
        status: str = _ACTIVE,
        commit: bool = True,
    ) -> SubscriptionPurchaseMapping:
        fields = dict(
            purchase_token=purchase_token, profile_id=profile_id, provider=provider,
            user_id=user_id, product_id=product_id, order_id=order_id,
            linked_purchase_token=linked_purchase_token, status=status,
        )
        row = self._upsert_row(fields, commit=commit)

        if linked_purchase_token:
            # Token replacement: the token this new row links back to
            # is no longer the operative one for this profile.
            self._mark_superseded(linked_purchase_token, commit=commit)

        return row

    def _upsert_row(self, fields: dict, *, commit: bool) -> SubscriptionPurchaseMapping:
        existing = self.find_by_purchase_token(fields["purchase_token"])
        if existing is not None:
            self._apply_fields(existing, fields)
            self._finalize(commit)
            return existing

        row = SubscriptionPurchaseMapping(**fields)
        db.session.add(row)
        try:
            self._finalize(commit)
            return row
        except IntegrityError:
            # Lost the atomic race -- some other caller's INSERT won
            # between our find_by_purchase_token() read above and this
            # INSERT attempt (the table's UNIQUE(purchase_token)
            # constraint is what actually decided this -- enforced at
            # flush time regardless of commit, so this is caught the
            # same way whether commit is True or False). Fall back to
            # updating whatever now exists rather than raising.
            db.session.rollback()
            existing = self.find_by_purchase_token(fields["purchase_token"])
            if existing is None:
                raise
            self._apply_fields(existing, fields)
            self._finalize(commit)
            return existing

    @staticmethod
    def _finalize(commit: bool) -> None:
        """commit=True (the default, used by every standalone caller
        unchanged): end the transaction here, exactly as before S15.
        commit=False: flush only -- sends the statement (so a
        UNIQUE(purchase_token) violation still raises immediately) but
        leaves the transaction open, so a caller composing this with
        another write (see PaymentService, S15) can commit both
        together, or roll both back together."""
        if commit:
            db.session.commit()
        else:
            db.session.flush()

    @staticmethod
    def _apply_fields(row: SubscriptionPurchaseMapping, fields: dict) -> None:
        row.profile_id = fields["profile_id"]
        row.provider = fields["provider"]
        if fields.get("user_id") is not None:
            row.user_id = fields["user_id"]
        if fields.get("product_id") is not None:
            row.product_id = fields["product_id"]
        if fields.get("order_id") is not None:
            row.order_id = fields["order_id"]
        if fields.get("linked_purchase_token") is not None:
            row.linked_purchase_token = fields["linked_purchase_token"]
        row.status = fields.get("status") or _ACTIVE

    def _mark_superseded(self, purchase_token: str, *, commit: bool = True) -> None:
        old_row = self.find_by_purchase_token(purchase_token)
        if old_row is not None and old_row.status != _SUPERSEDED:
            old_row.status = _SUPERSEDED
            self._finalize(commit)

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    def find_by_purchase_token(self, purchase_token: Optional[str]) -> Optional[SubscriptionPurchaseMapping]:
        if not purchase_token:
            return None
        return SubscriptionPurchaseMapping.query.filter_by(purchase_token=purchase_token).first()

    def find_by_linked_purchase_token(self, linked_purchase_token: Optional[str]) -> Optional[SubscriptionPurchaseMapping]:
        if not linked_purchase_token:
            return None
        return SubscriptionPurchaseMapping.query.filter_by(
            linked_purchase_token=linked_purchase_token,
        ).first()

    def resolve_profile_id(self, purchase_token: Optional[str]) -> Optional[int]:
        """The one call routes/routes_rtdn.py needs: resolve a bare
        RTDN purchase_token to a profile_id, or None if it genuinely
        cannot be resolved (never guessed -- the caller's own
        MISSING_PROFILE_ID reporting, S7B, handles that case)."""
        direct = self.find_by_purchase_token(purchase_token)
        if direct is not None:
            return direct.profile_id

        # Token replacement fallback: this purchase_token may be an
        # older token some other row already recorded as its own
        # linked_purchase_token at upsert time.
        superseding = self.find_by_linked_purchase_token(purchase_token)
        if superseding is not None:
            return superseding.profile_id

        return None
