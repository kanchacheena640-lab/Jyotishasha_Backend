# Subscription Migration — Phase 0: Identity Mapping & Data Audit

Status: read-only audit, completed 2026-07-30. No subscription records were modified, no dual-write enabled, no routes changed, no legacy code removed, Payment untouched.

This document is the artifact required by Phase 0 of the approved [Subscription Migration Plan](../../.) (see the Migration Planning review): the identity mapping strategy, the read-only audit result, and any unmappable/ambiguous records found. It is meant to be referenced by whoever implements Phase 1 (dual-write) and Phase 2 (backfill) next — it is not itself an implementation.

## 1. Identity mapping strategy

Systems A (`modules/subscription/models.py::Subscription`) and B (`modules/models_subscription.py::SubscriptionOrder`) key on `user_id`, a foreign key (declared or implicit) into `users.id` (`modules/auth/models.py::User`). System C (`modules/models_premium_subscription.py::CurrentEntitlement`) keys on `profile_id`, a foreign key into `app_users.id` (`modules/models_user.py::AppUser`). These are two different tables with no direct foreign key between them — the only link is the `firebase_uid` string both `User` and `AppUser` carry.

**Resolution path, in order:**

```
Subscription.user_id / SubscriptionOrder.user_id
        │
        ▼
users.id  →  users.firebase_uid          (User.firebase_uid is UNIQUE, indexed)
        │
        ▼
app_users.firebase_uid  →  app_users.id  (profile_id)
```

This is the same lookup `modules/user_service.py::get_or_create_app_user()` already performs — the mapping strategy is "reuse the existing identity resolver's join," not a new one.

**Known structural risk in this path:** `AppUser.firebase_uid` has **no database-level unique constraint** (unlike `User.firebase_uid`, which is `unique=True`). In principle this allows more than one `AppUser` row to share the same `firebase_uid`, which would make the last step of the resolution ambiguous (which `profile_id` does this `user_id` really mean?). Section 3 below reports whether this has actually happened.

**Per-`user_id` classification used by the audit** (five buckets, mutually exclusive):

| Bucket | Meaning |
|---|---|
| Mapped | Exactly one `AppUser` row found via `firebase_uid` — safe to migrate. |
| No `users.id` row | The legacy row's `user_id` doesn't correspond to any real `User` — orphaned at the source. |
| No `firebase_uid` on `User` | The `User` row exists but was never linked to Firebase — cannot resolve further. |
| No matching `AppUser` | The `firebase_uid` is real but no profile was ever created for it. |
| Ambiguous | The `firebase_uid` matches more than one `AppUser` row — cannot pick one automatically. |

## 2. Audit result (read-only, run 2026-07-30)

### Raw counts

| Table | Total rows | Detail |
|---|---|---|
| `subscriptions` (System A) | **0** | Empty. Nothing to migrate from this table today. |
| `subscription_orders` (System B) | **2** | 1 `pending`, 1 `success`; both `plan_type = "monthly"`. |
| `current_entitlements` (System C) | **0** | Empty — see note below. |
| `app_users.subscription` distribution | 548 rows | **All 548 are `"free"`.** Zero non-free. |

**Note on System C being empty:** `provision_trial_for_new_profile()` is wired into three call sites in the current working tree (`modules/user_service.py`, `routes/routes_profile_bootstrap.py`, `modules/auth/routes_profile.py`), but those changes are uncommitted local edits, not yet deployed — consistent with zero `current_entitlements` rows existing in the live database despite the wiring existing in code. This means System C currently has no real production data to protect during migration; the risk profile for Phases 1-3 is lower than a populated system would carry.

### Identity resolution result

| Source | Distinct `user_id`s | Mapped | No `users.id` | No `firebase_uid` | No `AppUser` | Ambiguous |
|---|---|---|---|---|---|---|
| System A (`subscriptions`) | 0 | — | — | — | — | — |
| System B (`subscription_orders`) | 1 | **1** | 0 | 0 | 0 | 0 |

The single real `user_id` in System B resolved cleanly to exactly one `profile_id`. Cross-checked against System C: that profile does **not** yet have a `CurrentEntitlement` row (consistent with System C being empty).

### `AppUser.firebase_uid` uniqueness check

374 distinct non-null `firebase_uid` values across 548 `AppUser` rows (174 `AppUser` rows have a null `firebase_uid` — not relevant to this migration's direction, since nothing needs to map *from* a profile back to a legacy `user_id`). **Zero** `firebase_uid` values matched more than one `AppUser` row — the theoretical ambiguity the missing unique constraint allows has not actually occurred in this data. This should be re-checked before Phase 2 backfill executes, since it is a live possibility, not a structural impossibility, until that constraint is added (out of scope for this migration).

## 3. Unmappable or ambiguous records

**None found.** With only 2 real rows across both legacy systems today, and the one real `user_id` mapping cleanly, there is currently no unmappable or ambiguous data to resolve. This is expected to change as real usage grows — this audit script should be re-run immediately before Phase 2 executes, not assumed still valid from this one run.

## 4. A finding outside this document's original scope, surfaced because Phase 0 asked "can every existing subscription be mapped safely"

While tracing every store of subscription-like state to answer that question, this audit found a **fourth** location holding subscription state that neither the forensic audit nor the consolidation review had previously identified: `AppUser.subscription` (`modules/models_user.py`), a plain string column, default `"free"`.

- **Read** by `notifications/notification_service.py` to target notification sends by subscription tier — a real, live consumer.
- **Written** by `modules/services/subscription_service.py::verify_subscription_payment()` (System B's payment-verification step) — this corrects an error in the earlier forensic audit, which assumed this write target was the auth `User` model (no such column) and concluded the write silently failed. It does not: `get_user_by_id()` (imported from `modules.user_service`) returns an **`AppUser`**, which *does* have a real `subscription` column — so System B's grant step does persist, just onto this fourth field, not onto System C.
- **Also written directly from raw, unvalidated client input**: `POST /users/register-or-update` (`routes/routes_user.py`, no authentication decorator at all) passes `data.get("subscription", ...)` straight through to `AppUser.subscription` with no validation against any plan list and no relationship to payment or entitlement state. Any caller who knows or guesses a `firebase_uid` can set that profile's subscription tier to any string, with no purchase involved.

Current production impact is limited only by the fact that nothing has exploited this yet (all 548 rows are still `"free"`), not by anything preventing it. This is a live, currently-unauthenticated write path directly into a field a live feature (notifications) already trusts — flagged here, per this task's read-only scope, for the migration plan to explicitly account for (a fourth data source to reconcile against System C, not three), and for a follow-up decision on remediation. No code was changed to address it as part of this Phase 0 task.

## 5. PASS / FAIL

**PASS.** Every existing legacy subscription record (2 rows, System B only — System A is empty) was resolved to its `profile_id` cleanly, with no ambiguous or orphaned mappings found. The identity mapping strategy itself is proven correct against real data, not just designed on paper. The one substantive risk this audit adds to the migration plan is not about mapping feasibility — it's the newly-found fourth subscription-state field and its unauthenticated write path, which should be added to the plan's risk register before Phase 1 begins.
