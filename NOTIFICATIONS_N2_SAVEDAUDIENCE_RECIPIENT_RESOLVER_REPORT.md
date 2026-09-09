# NOTIFICATIONS N2 — SAVEDAUDIENCE RECIPIENT RESOLVER REPORT

Date: 2026-09-08. Authority: frozen Notifications N1, Language Filter L2/L3 and Users v1.0.

## 1. Executive Verdict

**PASS.** Implemented an internal, read-only SavedAudience recipient resolver. Canonical membership, identity bridging, duplicate-token suppression, deterministic counts, All Users identification and the 50K safety error are tested. No sending or visible UI was introduced.

## 2. Discovery Confirmation

- `modules/auth/models.py`: canonical `User.id`, nullable unique `firebase_uid`, and an FCM mirror that N2 never uses.
- `modules/models_user.py`: `AppUser.id`, nullable UID with partial unique index `unique_app_users_firebase_uid`, and nullable `fcm_token` varchar(255). No unique token constraint.
- `modules/models_saved_audience.py`: criteria JSONB, versioned shared filters and `is_active`; no member snapshot.
- The existing canonical `resolve_user_ids()` implementation lives in `modules/services/admin_users_service.py`, as the SavedAudience model documents. There is no existing `SavedAudience.resolve_user_ids()` method. N2 calls that existing function after shared stored-criteria validation; no engine was copied or redesigned.
- `NotificationJob` has legacy JSON audience/payload and job status; `user_notifications.user_id` is the existing AppUser delivery/Bell identity. Neither model is changed or written by N2.
- Legacy `notifications/notification_service.py`, automatic `services/event_scheduler.py`, and personalized `modules/alerts/alert_delivery_service.py` use AppUser/token delivery paths. N2 imports none of those senders.
- Model/code and local schema inspection found no applicable per-account notification disablement/category opt-out source. `astro_events.notify_*` fields govern event scheduling, not account consent. No separate invalid-token registry exists; the legacy FCM path clears an unregistered token to null. N2 performs no provider validation and makes no claim that a nonblank token guarantees delivery.

No material contract contradiction was found.

## 3. Files Changed

All additions are in `C:\Project Jyotishasha\Jyotishasha_Backend`:

| File | Purpose |
|---|---|
| `notifications/saved_audience_recipient_resolver.py` | Canonical resolver, ephemeral internal targets, safe summary and failure contract |
| `test_notification_saved_audience_resolver.py` | Thirteen focused tests with local fixtures and synthetic scale/policy seams |
| `NOTIFICATIONS_N2_SAVEDAUDIENCE_RECIPIENT_RESOLVER_REPORT.md` | This report |

Local diagnostic additions: `.n2-regression-results.json` and `.n2-test_*.log`. No existing application, model, filter, test, Frontend or Flutter source was modified by N2. The existing local verification runner was reused unchanged.

## 4. Resolver Architecture

Call `resolve_saved_audience_recipients(saved_audience_id)` inside the backend Flask application context. It opens a private SQLAlchemy session through a nested app context, using PostgreSQL **REPEATABLE READ / READ ONLY**. All membership, profile and global token lookups share one committed snapshot. It neither commits nor flushes caller work; session teardown releases the transaction.

The flow is: current active SavedAudience → `validate_criteria(authoring=False)` → existing shared `resolve_user_ids(**filters)` → distinct sorted canonical IDs → User UID → AppUser → technical/policy checks → global duplicate-token ownership → result. Strict JSON integer version typing at the N2 boundary also rejects booleans/floats that Python otherwise equates to integer 1. Filter semantics remain exclusively shared.

Missing/inactive/invalid audiences, dependency failure and ambiguous profiles abort with a sanitized `RecipientResolutionError`. None falls back to empty filters, All Users, legacy filters or a successful zero result.

## 5. Eligibility Rules

Use only exact Firebase UID bridging; never compare numeric IDs or infer identity from email/name/phone. Missing/blank UID and missing profile are excluded. Profile ambiguity blocks the entire resolution per N1 section 7. Null/blank tokens are missing. Surrounding token whitespace is removed consistently for candidate/duplicate comparison.

There is no applicable current preference source, so absence alone does not suppress recipients or imply marketing consent. A bounded internal policy seam currently returns no explicit denials; synthetic tests prove explicit denial suppresses and policy read failure aborts. Any future authoritative preference source must be wired into that seam before relying on it.

Otherwise candidates are eligible only when current token ownership is unique globally and within canonical candidates. No profile is created or token updated.

## 6. Exclusion Reasons

Stable counters follow frozen N1 names and precedence:

1. `missing_identity_bridge`: absent account or null/blank UID.
2. `missing_profile`: no AppUser for UID.
3. `missing_token`: null/blank token, including tokens already cleared by existing invalid-token handling.
4. `preference_suppressed`: explicit applicable denial from the policy seam; zero with today's absent source.
5. `duplicate_target`: ambiguous ownership; all otherwise-eligible members of the group are suppressed.

Completed results enforce `matched_user_count = eligible_recipient_count + excluded_recipient_count`; exclusion counts are exclusive. Integrity/dependency failures return no partial result. The real fixture case reconciled **13 matched = 5 eligible + 8 excluded**.

## 7. Duplicate Identity/Token Safety

Multiple AppUsers for a UID raise `AMBIGUOUS_APP_USER`; no arbitrary profile is selected. The current unique UID index prevents a real duplicate fixture, so the aggregate ambiguity branch is tested with a fake.

Token-owner counts include **all AppUsers**, including profiles outside the audience and orphan profiles, rather than just one batch. The entire conflicting group is suppressed. Tests cover same-batch duplicates, whitespace variants, an outside-audience owner and a cross-batch duplicate involving candidates 1 and 1,001.

## 8. All Users + 50K Safety

Validated `filters={}` sets `is_all_users=True`; no confirmation UI is implemented. Explicit filters remain distinguishable from All Users even if they happen to match everyone.

More than 50,000 distinct matches raises `SAFETY_CEILING_EXCEEDED` with the **exact matched count** and `eligible_recipient_count=None` (not evaluated). Bridge processing does not start and no truncation occurs. Eligible count cannot exceed matched count by construction, so this also prevents any result above the eligible ceiling. Tests allow exactly 50,000 eligible synthetic candidates and reject 50,001 matches. A completed safe summary includes the ceiling and `safety_ceiling_exceeded=False`; later layers must treat the ceiling exception as a blocker, not zero recipients.

## 9. Privacy

Internal immutable recipients carry canonical User ID, AppUser ID, UID and current token only in memory. UID/token fields and recipient collections are excluded from default representations. `admin_safe()` contains counts, reasons, audience ID, All Users flag and safety/policy metadata only. It returns no recipient list, raw token or UID.

No public endpoint, serializer registration, token snapshot, persistence, analytics emission or logging call was added. Dependency errors are replaced with stable sanitized codes and suppressed underlying traceback context. Tests verify safe summaries/representations and captured ordinary logs contain no candidate tokens. Future callers must use the safe projection for Admin responses and must not serialize internal target objects.

## 10. Query/Scale Behavior

Each account-ID, profile-UID and token lookup receives at most **500** values. Profile and token-owner queries aggregate in SQL, returning bounded projections instead of full ORM profile loads. No per-recipient queries occur.

The actual 13-user fixture executes **6 statements**: transaction read-only setting, audience lookup, shared membership query, account lookup, profile aggregate and token-owner aggregate. A synthetic 1,001-candidate case performs **3 account + 3 profile + 3 token batches**. The 50,000-boundary test performs 100 account batches, with all targets retained.

The frozen shared resolver still materializes all matching integer IDs before the ceiling check. Up to 50K ephemeral candidates are also retained for global reconciliation. Token normalization has no supporting token index today and may require repeated scans per batch. These are documented scale limitations; no production throughput/SLA claim or premature schema change is made. Transport batching, durable targets and execution freeze remain later-phase work.

## 11. Tests

From Backend, every suite below used this exact command pattern:

```powershell
.\venv\Scripts\python.exe scripts/l3_local_verify.py <suite>
```

| Suite | Passed | Failed |
|---|---:|---:|
| `test_notification_saved_audience_resolver.py` | 13 tests | 0 |
| `test_language_filter_l3.py` | 12 tests | 0 |
| `test_saved_audience.py` | 114 checks | 0 |
| `test_admin_users_api.py` | 136 checks | 0 |
| `test_admin_asknow_concern.py` | 72 checks | 0 |
| `test_admin_dasha_api.py` | 43 checks | 0 |
| `test_admin_sade_sati.py` | 51 checks | 0 |
| `test_admin_transit.py` | 88 checks | 0 |
| `test_static_astrology_extractor.py` | 34 checks | 0 |
| `test_static_astrology_persistence.py` | 42 checks | 0 |
| `test_notification_activity_events.py` | 120 checks | 0 |
| `test_notification_lifecycle.py` | 25 checks | 0 |

Totals: **13 focused N2 tests, 12 L3 tests, 725 existing regression checks; zero failures.** `git diff --check` also passed. Existing SQLAlchemy legacy Query.get warnings were observed and left unchanged.

## 12. Regression

Verified Admin Users, SavedAudience, Language Filter, static astrology, Dasha, Sade Sati, Transit, Ask Now, customer/payment filtering and existing notification activity/lifecycle behavior. Legacy notification tests use fake transports and dedicated local fixtures. N2 tests prove the resolver imports no legacy sender/FCM module, adds no filter predicates, executes read-only SQL and preserves uncommitted caller work.

## 13. Database Safety

Before DB-dependent testing, the existing runner checked the configured URL host and actual server identity. `SELECT current_database(), inet_server_addr()::text` returned **`jyotishasha_local`, `::1/128`**, verified as loopback with IP parsing. Dotenv credentials were not loaded. External DNS/socket calls, Firebase initialization/sending and schema DDL were blocked by the runner.

Final schema revision remains **`9f2a5c7e1b83`**. Final N2 fixture counts: **0 Users, 0 AppUsers, 0 SavedAudiences**. No migration/backfill or production access occurred.

## 14. Scope Confirmation

No Firebase initialization, FCM/real notification send, real campaign, scheduling, public endpoint, Admin UI, Flutter or public website change. No visual QA is required because no visible surface changed. No campaign tables, approval snapshots, hashes, durable execution targets or transport batching were implemented. Notifications N3 was not started.

## 15. Git Status

The new resolver, focused test and report remain untracked/uncommitted, alongside local diagnostic evidence. The 26 preexisting modified tracked Backend files and all prior untracked work remain intact. Frontend and Flutter were not modified by N2. No reset, clean, restore, checkout, stash/rebase, commit, push or deploy occurred.

Notifications N1 remains unchanged with SHA256 `B338C85F609545EBC9FF0CDD9B73198C1B836B13BE93923D118ADCA5B9EC79D6`. Frozen Users and Language Filter implementation files were not edited.

## 16. Remaining Risks

No known N2 blocker. Candidate eligibility is a read-time technical result, not consent, approval or a delivery guarantee. Ownership can change after return; future execution must revalidate it. The current materialized-ID resolver and unindexed normalized-token ownership scans require measured scale validation before production-scale activation. The 50K test uses fakes, not a production-scale database benchmark. Future authoritative opt-out sources require explicit integration; no such source exists today.

## 17. Final Recommendation

NOTIFICATIONS N2:
READY TO FREEZE

STOP after N2. Notifications N3 remains unstarted.
