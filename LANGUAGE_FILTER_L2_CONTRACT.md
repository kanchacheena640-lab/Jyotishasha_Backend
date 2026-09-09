# LANGUAGE FILTER L2 CONTRACT REPORT

Date: 2026-09-08. Basis: completed L1 discovery and the Product Owner's L2 app-user authority decision. This is the bounded language enhancement contract, not implementation authorization. Existing Users/SavedAudience semantics remain unchanged unless explicitly extended below. Notifications N1 is not modified.

## 1. Canonical Authority

**FROZEN CONTRACT.** `app_users.lang` means: **The authenticated Jyotishasha app user's current preferred Jyotishasha app/content language.** It is not the language of whichever birth profile, report, website page or notification was most recently viewed.

Canonical values are `en` (English), `hi` (Hindi), and SQL NULL (not yet reliably established/unknown). Rendering may independently fall back to English; rendering fallback must never become an implicit SQL preference or English audience membership.

The existing nullable varchar(5) field is sufficient. Do not duplicate language on SQL `users`, add a new language column, or fill NULL with English. Existing non-null values are retained; L1 did not establish their production provenance or authorize correcting them in bulk. L1's 19 NULL local profiles were fixture data, not production coverage evidence.

## 2. Scope

**IN SCOPE for the single later implementation task:** producer/key alignment; authenticated language-only synchronization/readback; account-safe local pending preference handling; one shared Users language predicate; additive SavedAudience criterion; Admin filter controls/chips/round-trip; narrowly correcting the legacy sender attribute lookup; regression/parity tests.

**OUT OF SCOPE:** website locale as preference authority, website localization changes, order/report-language inference, secondary-profile preference inference, new identity architecture, bilingual content generation, localization platform, analytics platform, production backfill, Notifications N2, real Firebase sends or deployment. Next Admin filter controls are in scope; public website locale synchronization is not.

L2 itself creates only this document. No implementation begins when this document is written.

## 3. Identity Contract

Writes require `Authorization: Bearer <Firebase ID token>` verified by the existing backend authentication mechanism. Derive the UID from the verified token, then resolve exactly one `AppUser.firebase_uid` match. Never authorize using client-supplied users.id, app_users.id, profile ID or UID. Preference API bodies reject identity selectors and unrelated profile fields.

For Admin membership, preserve `users.id → users.firebase_uid → app_users.firebase_uid → app_users.lang`. Never compare numeric IDs across the two tables. Reject null/blank authenticated UID. Missing profile on a preference write returns a structured `profile_not_ready` conflict; do not create a profile or calculate a chart merely to save language. The client can retry after the existing authenticated bootstrap creates it. Multiple UID matches are an integrity failure, not permission to choose the first row.

The read path returns `lang:null` and profile readiness explicitly when no profile exists, without mutation. Invalid authentication fails before lookup/write. Production token verification is not invoked by local tests; use the project's isolated authentication test seam.

## 4. Producer Contract

SQL is authoritative for the last successfully synchronized account preference; device state represents UI language plus any explicit unsynchronized choice. An unacknowledged local switch does not change audience membership yet.

| Situation | Required future behavior |
|---|---|
| Initial primary-user onboarding | An explicit app-language choice may initialize SQL through the language-only writer after the authenticated profile exists. A displayed English default alone is not an explicit choice. Initial selection UI must distinguish user-confirmed preference from fallback |
| Existing-user login/bootstrap | Read the authenticated account's stored preference. Apply known en/hi unless this same signed-in session has a newer explicit pending choice. Missing language input and rendering defaults never overwrite SQL |
| Manual authenticated app switch | Change UI/local app preference immediately, queue the chosen canonical value for that authenticated UID, and synchronize via the narrow preference API |
| Logout | Preserve generic device UI preference for usability, but cancel/discard account-bound pending sync and ignore late responses from the old auth generation. Do not write NULL or English to the old account |
| Login to another account | Fetch that account's value; never upload the prior account's/device's cached app_lang as the new account's preference. An unknown server value may use local UI fallback without persistence until explicit selection |
| Reinstall/new device | Read the authenticated server preference. Without one, use rendering fallback and allow explicit choice; no default-value upload. Reinstall is not a consent/preference inference |
| Offline switch/backend failure | Keep UI usable and retain the latest pending explicit choice scoped to UID. Retry on next authenticated foreground/reconnect or explicit switch; no background polling platform. Report sync as pending, not successful |
| Unsupported input | Return validation error and do not change SQL; supported UI controls emit only en/hi |
| Missing input | Bootstrap leaves SQL unchanged. Dedicated preference write rejects missing value; it must not default to English |
| Profile/report language edit | Affects that profile/report only. Does not update the account app preference or call its synchronization API |

Use a small persisted pending record containing UID, canonical value and local generation, separate from generic app_lang. Coalesce repeated offline changes to the latest choice. At most one preference request is in flight for a UID in the client; after it settles, send the newer queued value if necessary. Repeated same-value requests are idempotent assignments. Check current UID/auth generation before dispatch and before applying responses. Never replay A's pending preference with B's credentials. Logout discards queued work; an already dispatched authenticated request may complete only for its original account, and its response must not change B's UI.

Same-UID app restart may resume an explicitly recorded pending choice after identity verification; a bare legacy app_lang value lacks that provenance and is never automatically uploaded. A late login read cannot overwrite a newer local explicit switch. Successful acknowledgement clears only the matching pending generation. Across devices, the last successfully accepted explicit preference write is authoritative; v1 adds no device registry or globally ordered synchronization platform.

## 5. API Key Contract

Canonical preference request/response key: **`lang`**. Values are strings, trimmed and lowercased, and must then be exactly en or hi. Reject null, blank, booleans, numbers, arrays, English/Hindi labels and regional tags such as en-IN. No evidence requires those aliases. No API action clears an established preference to NULL in this v1 contract.

Future narrow surface: authenticated `GET /api/user/preferences/language` and `PATCH /api/user/preferences/language`. PATCH body is `{ "lang": "hi" }`; successful response returns the acknowledged canonical `lang`. GET returns canonical en/hi/null plus profile readiness. Historical unsupported stored values read as unknown for targeting/readback without rewriting the row. This contract does not add a general profile/preferences endpoint.

PATCH accepts only the canonical key; missing or unsupported input returns a validation error. Authentication errors are 401; missing profile is 409 profile_not_ready; identity ambiguity is a structured server integrity failure. No birth fields, profile editing, Kundali generation, entitlement change, FCM operation or unrelated ORM update may be a side effect. Repeated identical updates produce the same stored result and need no new idempotency table.

**Bootstrap compatibility:** future updated app bootstrap uses `lang` for requested content rendering. Temporarily accept legacy `language` on existing bootstrap because L1 found active clients sending it. Normalize/validate each supplied value. If both keys are present and normalize equally, use canonical lang; if they conflict or either is invalid, reject rather than silently prefer one. If neither is supplied, existing English rendering fallback may remain, but SQL language is unchanged. Alternate-key removal is deferred until supported-client compatibility is demonstrated; no arbitrary retirement date is assumed.

**Authority separation is mandatory:** bootstrap/profile content keys, whether lang or language, do not themselves authorize changing the account preference. L1 found secondary-profile creation using the same bootstrap helper. Therefore remove automatic language persistence from generic bootstrap and generic profile register/update paths in the future bounded implementation. Explicit primary onboarding and manual app switches use the authenticated preference writer separately. This preserves legacy rendering compatibility without treating another person's chart language as account preference. Generic profile operations must not invoke a hidden preference synchronization side effect. Existing clients may continue rendering with language while lacking the new synchronization capability; do not invent reliable preference from their payload.

## 6. Multiple Profile Safety

Application preference belongs to the authenticated account. Firestore profile language belongs to the selected birth/profile document. Order/report language belongs to that requested deliverable. They may legitimately differ.

Adding/editing/activating another person's profile cannot call the account-language writer, overwrite app_users.lang or silently change the global app preference. Existing profile edit code that calls LanguageProvider.setLanguage must be separated from explicit app-language controls. Main-user onboarding may offer an explicitly identified app-preference selection; do not infer ownership merely because a Firestore profile is active or first in a list.

Do not redesign profile identity or repair unrelated birth-profile synchronization in this task. Protect account language at the write boundary independently of those existing profile behaviors.

## 7. Website Exclusion

Website locale does not define, write, override, supply fallback for, or otherwise influence app_users.lang. It is not used in Users or SavedAudience language membership. Website traffic/acquisition attribution remains separate. No website language detection, cookie/localStorage bridge, authenticated website preference writer or locale migration is required.

Likewise, do not infer app preference from orders.language, report choice, viewed content, names, country, astrology data or notification interaction. No query-time fallback to any such source is permitted.

## 8. Shared Filter Contract

Optional SavedAudience shape, remaining criteria **version 1**:

```json
{"version": 1, "filters": {"language": ["hi"]}}
```

Allowed nonempty selections: en, hi, or both. OR within language; AND across dimensions. Omitted language means no language restriction. `["en","hi"]` matches known supported language only and excludes unknowns; it is not equivalent to omission. No selectable UNKNOWN/UNSET in initial v1.

Criteria validation accepts only canonical lowercase strings in a nonempty array; reject null/scalar/empty array/unknown values rather than silently broadening to All Users. Duplicate valid selections have set semantics and serialize uniquely. UI no-selection omits the key. HTTP Users query uses `language=en,hi`; present-but-empty/malformed input is invalid, not omission. Do not normalize invalid criteria by dropping entries.

For historical stored values, the single shared SQL expression trims surrounding whitespace and lowercases, then matches only en/hi. NULL, blank, unsupported values and missing bridge/profile do not match. Do not translate English/Hindi names or infer regional tags. Query-time normalization is read-only; canonical writes prevent new variation. Apply the same explicit whitespace policy in tests for spaces/tabs/newlines; do not assume SQL's default btrim handles every whitespace character like application trim.

Use the canonical UID bridge with non-null/nonblank UIDs, and guard ambiguous profile matches rather than selecting an arbitrary row. Missing/ambiguous bridge does not match a selected language; preserve existing no-language behavior unchanged. Implement the language predicate once inside `_apply_admin_users_filters` and thread its argument through both `list_users` and `resolve_user_ids`. Reuse existing SQL filtering infrastructure; no per-user astrology calculations or notification-only predicate.

Extend `_FILTER_VALIDATORS`/canonical keys, Admin API parsing and frontend type/serialization maps together. `preview_criteria` and `preview_audience` already call the shared list service; saved resolution uses the same validated criteria and ID resolver. Existing audiences without language retain identical meaning and need no rewrite/migration. An optional additive v1 key is safe with coordinated backend/frontend delivery; old clients may reject unfamiliar criteria and must not silently erase the field. New criteria authoring must not be enabled against a backend that lacks the key.

Default Users table columns and all unrelated filtering semantics remain unchanged. Hindi + Saturn Mahadasha, English + Sade Sati, Hindi + Ask Now concern and language + paying-user criteria all use the same AND composition. N2 later consumes returned users.id values, with no separate language membership implementation.

## 9. Existing Defects To Correct During Implementation

1. Bootstrap producer sends language but backend reads lang and defaults missing input to en. Align canonical key and rendering compatibility; missing/default input must not persist preference.
2. LanguageProvider.setLanguage currently updates device storage/UI only. Add account-safe authenticated synchronization for explicit app preference changes.
3. Generic bootstrap/profile writers can mistake content language for account preference; profile edit currently also changes global app language. Separate these behaviors as sections 5–6 require.
4. AppUser.to_dict omits lang. The narrow GET/PATCH response must provide explicit preference readback; adding a column to the default Admin table or broad serializer changes is unnecessary.
5. Admin Job sender reads `getattr(u, "language", "en")` although recipients are AppUser with lang and no alias. Correct that attribute lookup narrowly in the later implementation, with an isolated injected-sender test. Preserve existing content fallback/selection and do not add new automatic bilingual generation, change scheduling or invoke FCM. NULL rendering fallback remains separate from filter membership.

The legacy Job resolver is never reused as the language audience resolver. Existing automatic event/alert selection and timing stay untouched.

## 10. Bounded Implementation Scope

**One next task: LANGUAGE FILTER L3 — APP PREFERENCE SYNC + SHARED USERS/SAVEDAUDIENCE LANGUAGE FILTER.** Requires separate authorization; do not begin now.

| Component | Exact bounded surface |
|---|---|
| Backend producer/preferences | A small language preference service and authenticated GET/PATCH route; wire registration using current conventions; align routes/routes_profile_bootstrap.py and modules/user_service.py so content/profile writes do not redefine app preference |
| Shared Users | modules/services/admin_users_service.py language expression/shared predicate and list/resolve arguments; routes/routes_admin_users.py strict query parsing |
| SavedAudience | modules/services/saved_audience_criteria.py optional v1 key; existing preview/service delegation retained |
| Flutter | lib/core/state/language_provider.dart plus narrow preference repository/client; explicit app controls and startup/auth lifecycle; lib/core/state/kundali_provider.dart key alignment; birth/add/edit-profile callers distinguish app intent from profile content |
| Next Admin only | lib/admin/usersApi.ts defaults/types/buildUsersQuery; lib/admin/audiencesApi.ts typed mapping/round-trip/summary; UsersFilterPanel.tsx controls; UsersPageClient.tsx chips/reset/save. Reuse AudienceEditor; no public website locale changes |
| Legacy sender | notifications/notification_service.py attribute correction only; no audience engine changes |
| Database | Existing app_users.lang; no new column, duplicate users field, migration or backfill expected. Measure query performance before proposing an index |

Required tests within L3:

- Authenticated read/write, forged body identities, missing/ambiguous profile, no profile creation and no Firebase network calls in local tests.
- Canonical/legacy bootstrap keys, equal/conflicting dual keys, unsupported/missing/null/blank input and normalized en/hi. Prove rendering fallback never writes English implicitly.
- Primary explicit selection versus secondary profile/report edits; language-only sync does not change birth data or invoke astrology computation.
- Login reconciliation, local default not uploaded, newer explicit switch wins over late read, same-UID restart retry, logout cancellation, account switching, offline failure and repeated assignment.
- Four-way parity: Users list, direct preview, SavedAudience preview and resolve_user_ids; language alone and with static astrology, Dasha, Sade Sati, Transit, Ask Now and customer/payment dimensions.
- NULL/invalid/whitespace/case values, missing/ambiguous UID bridge, unequal numeric User/AppUser IDs, both-versus-omitted language and historical audience parity.
- Frontend apply/cancel/reset/chips/pagination, Save Audience and edit round-trip, explicit false booleans retained, malformed criteria fail closed, unchanged default table.
- Sender lang lookup with en/hi/NULL and a fake transport only; automated pipeline behavior remains unchanged.

Extend existing test_admin_users_api.py, test_saved_audience.py, scoped bootstrap/profile tests, lib/admin/audiencesApi.test.ts and add focused preference-client/service tests where necessary. Do not run fixture-writing legacy suites against an unverified database. Later local DB tests must first verify loopback and current_database()=jyotishasha_local, with no production URL or app startup merely for inspection.

## 11. Deferred / Out of Scope

Website localization and preference synchronization; language inference/backfill; production data repair; new user/profile identity architecture; globally ordered multi-device sync; language timestamps/provenance analytics platform; selectable UNKNOWN; additional locales/historical-name aliases; automatic bilingual notification generation; general localization/content engine; notification membership filtering outside Users; Notifications N2; Firebase sending/deployment.

A valid persisted en/hi value can still have historical producer provenance limitations. Preserve it until explicit app choice updates it; do not pretend L2 establishes production data quality. A future evidence-backed repair is separate. No unresolved product question is created by deferring unsupported expansion.

## 12. Product Owner Decisions Required

**NONE.** The Product Owner's authenticated app-user authority decision and L1 evidence resolve material scope choices. Canonical lang, narrow authenticated sync, bootstrap rendering compatibility, secondary-profile protection, website exclusion and additive shared criteria are concretely defined above. Technical implementation choices must preserve this contract; they are not open-ended product approval requests.

## 13. Final Status

LANGUAGE FILTER L2 CONTRACT:
READY TO FREEZE

This is a contract/design deliverable. It does not mean the producer, filter or UI is implemented, and does not authorize starting L3 or Notifications N2 automatically.

## 14. Safety Confirmation

- Documentation only: this dedicated file is the sole addition.
- No application code, backend behavior, models, APIs, frontend or Flutter changed.
- No database access/writes, migration, fixtures or backfill in L2.
- No Firebase initialization/access, production access or notification send.
- Notifications N1 remains unchanged; Notifications N2 and Language Filter implementation were not started.
- No commit, push, deploy or destructive git operation; existing uncommitted work preserved.

STOP after L2 documentation.
