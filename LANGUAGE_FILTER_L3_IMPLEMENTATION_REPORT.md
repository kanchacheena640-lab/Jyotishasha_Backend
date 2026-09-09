# LANGUAGE FILTER L3 IMPLEMENTATION REPORT

Date: 2026-09-08. Frozen authority: `LANGUAGE_FILTER_L2_CONTRACT.md`. Local implementation and verification only.

## 1. Executive Verdict

**PASS.** Resumed the existing implementation without resetting or replacing completed work. Completed account-race fixes, compile fixes, preference isolation verification, shared membership parity, regression tests, and actual Admin visual inspection. Notifications N2 was not started.

## 2. Files Changed

Paths below are relative to the named repository and identify L3 work, including work already present when this session resumed. Other existing changes remain untouched.

| Repository | File | L3 purpose |
|---|---|---|
| Backend | `modules/services/language_preference_service.py` | Canonical language validation, profile integrity lookup, read/write helpers |
| Backend | `routes/routes_user.py` | Authenticated language GET/PATCH |
| Backend | `routes/routes_profile_bootstrap.py` | Canonical/legacy rendering keys; remove preference side effect |
| Backend | `modules/user_service.py` | Remove generic profile language preference writes |
| Backend | `modules/models_user.py` | Correct language-authority comment; no column/schema change |
| Backend | `modules/services/admin_users_service.py` | One guarded SQL language predicate shared by list and ID resolution |
| Backend | `routes/routes_admin_users.py` | Strict language query parsing |
| Backend | `modules/services/saved_audience_criteria.py` | Additive v1 language criterion and canonical set serialization |
| Backend | `notifications/notification_service.py` | Correct legacy recipient attribute to `lang` |
| Backend | `test_language_filter_l3.py` | Preference, validation, membership, query-count and fake-sender tests |
| Backend | `test_saved_audience.py` | Four-way language composition parity using existing fixtures/engines |
| Backend | `test_static_astrology_bootstrap_and_deletion.py` | Actual bootstrap compatibility and preference preservation checks |
| Backend | `scripts/l3_local_verify.py` | Verified-loopback DB runner; block external network, Firebase and DDL |
| Backend | `scripts/l3_admin_visual.cjs` | Local browser interaction and screenshot QA with synthetic responses |
| Backend | `LANGUAGE_FILTER_L3_IMPLEMENTATION_REPORT.md` | This report |
| Admin Frontend | `lib/admin/usersApi.ts` | Filter type/default and query serialization |
| Admin Frontend | `lib/admin/audiencesApi.ts` | Criteria mapping, validation, labels and round-trip |
| Admin Frontend | `components/admin/users/UsersFilterPanel.tsx` | English/Hindi multi-selection |
| Admin Frontend | `components/admin/users/UsersPageClient.tsx` | Independent language chips and existing Apply/Reset/Save integration |
| Admin Frontend | `lib/admin/languageL3.test.ts` | Seven focused serialization/criteria tests |
| Flutter | `lib/core/repositories/language_preference_repository.dart` | Injectable account-scoped preference interface |
| Flutter | `lib/core/repositories/implementations/http_language_preference_repository.dart` | Authenticated HTTP read/write with identity checks and acknowledgement validation |
| Flutter | `lib/core/state/language_provider.dart` | Immediate UI, persisted UID-scoped pending generation, retry and stale-response protection |
| Flutter | `lib/main.dart` | Wire repository into provider |
| Flutter | `lib/core/auth/session_cleanup.dart` | Discard account-bound pending work on logout |
| Flutter | `lib/core/state/kundali_provider.dart` | Send canonical bootstrap `lang` |
| Flutter | `lib/features/birth/birth_detail_page.dart` | Distinguish explicit app-language selection from displayed default |
| Flutter | `lib/features/profile/edit_profile_page.dart` | Remove global language write from profile edit |
| Flutter | `lib/features/profile/account_page.dart` | Display unsynchronized preference as pending |
| Flutter | `test/language_provider_l3_test.dart` | Seventeen focused lifecycle/race/producer tests |

Local diagnostic artifacts remain in Backend `.l3-*.log`, `.l3-regression-results.json`, `.l3-final-git-status.json`, and `.l3-visual/`. Frontend compiled test output is `.u6b-l3-test-out/`. No preexisting artifact was deleted. The regression JSON records the earlier 17-check bootstrap run; the final expanded bootstrap run passed 24 checks, as recorded below.

## 3. Preference API

`GET/PATCH /api/user/preferences/language` verifies a Firebase bearer token using the existing auth convention, then resolves `AppUser.firebase_uid` from its verified UID. Tests replace token verification; they never contact Firebase.

PATCH accepts exactly `{ "lang": "en" }` or `hi` after string trim/lowercase. Missing, null, unsupported, regional, non-string and extra/identity fields return 400. Missing/invalid auth returns 401. Missing profile returns 409 `profile_not_ready`; ambiguous profile ownership returns 500 `ambiguous_profile`; other storage failures return 503. It does not create a profile.

GET returns `{lang: en/hi/null, profile_ready: boolean}`. Historical unsupported values read as null without mutation. Tests verify repeated writes and compare every other AppUser column before/after: only language changes.

## 4. Flutter Synchronization

Explicit selection updates rendering immediately and creates a separately persisted `{uid, lang, generation}` pending record. SQL synchronization uses the captured account's token; identity is checked before dispatch and responses are guarded by account/generation state. Acknowledgement clears only its matching generation. Only one write per UID is in flight; newer selections are coalesced.

Login reads known server preference. Server null and bare legacy `app_lang` remain rendering fallback and never trigger upload. Offline/missing-profile failures retain explicit pending work, retrying on authenticated foreground or another explicit selection. Same-UID restart resumes pending work. Logout discards account work; another account never inherits its upload. Late reads and acknowledgements cannot overwrite a newer selection or another account. Account settings display pending synchronization. No polling framework was added.

## 5. Bootstrap/Profile Safety

Flutter now sends `lang`. Bootstrap accepts `lang`, legacy `language`, or equal normalized dual keys for rendering. Conflicts and invalid supplied values fail. Omission retains English rendering fallback without writing preference.

Generic profile registration/update no longer writes `app_users.lang`. Secondary profile editing no longer calls the global preference writer. Primary onboarding invokes it only after an explicit app-language selection and successful profile creation. Existing report/profile language fields remain. Actual local bootstrap tests prove an existing Hindi preference survives English/legacy/missing rendering inputs, and an initial generic bootstrap leaves preference null.

## 6. Shared Users Filter

`_apply_admin_users_filters()` owns the only language predicate, reused by `list_users()` and `resolve_user_ids()`. Correlated SQL uses `users.firebase_uid = app_users.firebase_uid`; numeric IDs are never compared. It requires a nonblank UID and exactly one AppUser match, then guarded EXISTS membership in the selected language set.

Stored language is normalized with PostgreSQL `lower(regexp_replace(lang, '^\s+|\s+$', '', 'g'))`. Spaces, tabs and newlines are covered. Null, blank, unsupported, missing and blank/null UID bridges are excluded. OR applies within language; AND applies across dimensions. Omission is unrestricted; both languages exclude unknowns. No Python filtering, per-user queries, schema change or backfill. Query-count testing confirms constant query count across page sizes 1/20/100.

## 7. SavedAudience Integration

Criteria remain version 1: `{"version":1,"filters":{"language":["hi"]}}`. Nonempty canonical arrays only; duplicates serialize as a sorted unique set. Malformed language fails closed. Historical criteria without language retain their behavior without migration.

Users list, direct preview, saved preview and `resolve_user_ids()` matched for English, Hindi, both and omission, including unequal numeric IDs and unknown/invalid bridges. Nonempty Hindi intersections passed for static astrology, Dasha, Sade Sati, Transit, Ask Now concern and paying/customer filters. Existing engines were reused unchanged.

## 8. Admin UI

English/Hindi controls reuse the existing multi-select design and shared Audience editor. Independent chips, Apply, Cancel, Reset, pagination, Save Audience, editor restoration, edit cancellation and save round-trip passed. Summaries display English/Hindi. Default table columns remain unchanged. Public website locale code was not changed by L3.

## 9. Legacy Sender Fix

The single recipient-language line now reads `(getattr(u, "lang", None) or "en").strip().lower()`. Existing title/body fallback and recipient/scheduling logic remain unchanged. Injected fake-transport tests verify English, Hindi and null fallback, including a deliberately wrong `language` attribute. No real send or notification row was produced by those tests.

## 10. Database Safety

Before DB-dependent suites, the runner parsed the existing local fixture URL without loading dotenv secrets and checked both configured loopback host and actual server identity:

`SELECT current_database(), inet_server_addr()::text` returned **`jyotishasha_local`, `::1/128`**. IP parsing verified loopback.

Firebase initialization/token verification/sending were blocked except explicit test mocks; external DNS/socket connections and schema DDL were prohibited. Normal app import completed with `db.create_all` forbidden. Local migration revision remains **`9f2a5c7e1b83`**. Final L3 synthetic Users, AppUsers and audiences remaining: **0, 0, 0**. No migration/backfill was created or run. No production DB/API access occurred.

## 11. Tests

Backend command for each suite below, from Backend:

```powershell
.\venv\Scripts\python.exe scripts/l3_local_verify.py <suite>
```

| Suite | Final passed | Failed |
|---|---:|---:|
| `test_language_filter_l3.py` | 12 unittest tests | 0 |
| `test_saved_audience.py` | 114 checks | 0 |
| `test_admin_users_api.py` | 136 checks | 0 |
| `test_admin_asknow_concern.py` | 72 checks | 0 |
| `test_admin_dasha_api.py` | 43 checks | 0 |
| `test_admin_sade_sati.py` | 51 checks | 0 |
| `test_admin_transit.py` | 88 checks | 0 |
| `test_db_safety.py` | 15 checks | 0 |
| `test_static_astrology_extractor.py` | 34 checks | 0 |
| `test_static_astrology_persistence.py` | 42 checks | 0 |
| `test_static_astrology_bootstrap_and_deletion.py` | 24 checks | 0 |

Backend regression total: **619 checks**, plus **12 focused unittest tests**.

Frontend commands, from Admin Frontend:

```powershell
node node_modules/typescript/bin/tsc --noEmit --incremental false --pretty false
node node_modules/typescript/bin/tsc --module commonjs --moduleResolution node --target es2021 --strict --skipLibCheck --esModuleInterop --outDir .u6b-l3-test-out lib/admin/usersApi.ts lib/admin/audiencesApi.ts lib/admin/audiencesApi.test.ts lib/admin/languageL3.test.ts
node .u6b-l3-test-out/audiencesApi.test.js
node --test .u6b-l3-test-out/languageL3.test.js
```

Both compiles passed. Existing standalone criteria assertion suite passed (it does not emit an assertion count). New Node tests: **7 passed, 0 failed**.

Flutter commands, from Flutter, using `C:\Development\Flutter\bin\flutter.bat`:

```powershell
flutter test --no-pub test/language_provider_l3_test.dart
flutter test --no-pub test/esr/profile_characterization_test.dart test/esr/user_session_profile_contracts_test.dart test/characterization/login_characterization_test.dart test/characterization/session_restore_characterization_test.dart
flutter test --no-pub test/features/profile/account_page_test.dart test/features/profile/account_page_delete_account_test.dart test/core/widgets/greeting_header_widget_test.dart
flutter analyze --no-pub lib/core/state/language_provider.dart lib/core/repositories/language_preference_repository.dart lib/core/repositories/implementations/http_language_preference_repository.dart
```

Results: **17 + 23 + 49 = 89 tests passed, 0 failed**. New sync files: **no analyzer issues**. Broader touched-file analysis also ran: existing `withOpacity` deprecations, profile `notifyListeners` access warnings and a preexisting session-cleanup async-context diagnostic remain; new L3 analyzer findings were corrected.

Browser command, from Backend: `node scripts/l3_admin_visual.cjs`: **13 checks passed, 0 failed**. `git diff --check` passed in all three repositories. Initial TypeScript failure and new analyzer findings were fixed; initial browser-script assumptions about page size and save navigation were corrected without changing application behavior.

## 12. Regression Results

Verified Admin Users, SavedAudience, static astrology, Dasha, Sade Sati, Transit, Ask Now concern, customer/payment intersections, bootstrap/static persistence/deletion, Flutter profile/session/account controls and existing language rendering. No unrelated application failure was repaired and no test was weakened. A production website build and live Firebase/mobile-device integration were not run.

## 13. Visual QA

**PASS — actual screenshots inspected.** Local pages: `http://127.0.0.1:3000/admin/users` and `/admin/audiences/901` (synthetic audience). Desktop 1365×900; mobile viewport 390×844. Inspected English, Hindi, both, applied chips, Reset, Save Audience summary, edit criteria restoration and mobile filter layout. Controls align with existing sections, footer remains usable and no page-width overflow was found for the mobile filter.

Evidence: `.l3-visual/01-language-unselected.png` through `.l3-visual/09-mobile-filter.png`, plus `.l3-visual/results.json`. Browser responses were synthetic in-memory BFF fixtures; actual PostgreSQL/API membership correctness was verified separately. This is not a claim of live Firebase or full-stack browser-to-database testing. External browser requests were blocked. The local QA server was stopped afterward. No manual visual QA remains required for this scoped change.

## 14. Remaining Risks

No known L3 blocker. Test evidence intentionally excludes live Firebase credentials/sends and physical-device integration. Browser visual checks use synthetic responses; backend tests cover real local SQL. Historical supported non-null preferences retain L2's acknowledged provenance limitation. Existing unrelated analyzer diagnostics remain. Coordinated backend/Admin delivery is still necessary before authoring the additive criterion against an older backend.

## 15. Git Status

All three working trees remain uncommitted. Backend retains its 26 previously modified tracked files and existing untracked work, with L3 tests/report/evidence added. Admin retains its 21 preexisting modified tracked files; L3 changes are within the already-untracked Admin directories. Flutter has eight modified tracked files, including the untouched preexisting `android/gradle.properties`, plus the two new repository files and focused test. Exact status snapshot: `.l3-final-git-status.json` (taken immediately before adding this report).

No reset, clean, restore, checkout, stash/rebase, commit, push or deploy. No public website locale changes by L3. L2 was not edited. Notifications N1 SHA256 remains `B338C85F609545EBC9FF0CDD9B73198C1B836B13BE93923D118ADCA5B9EC79D6`, matching the pre-L3 hash. Notifications N2 was not started.

## 16. Final Recommendation

LANGUAGE FILTER L3:
READY TO FREEZE

STOP. Notifications N2 remains unstarted.
