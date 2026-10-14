# Marriage astrology local closure

This is a locally implemented, tested change set. Nothing has been connected to
production, exported from production, migrated, pushed or deployed. The original
local closure was uncommitted; the subsequent selective commit is local only.
The separate existing Manglik/runtime/parity evidence remains valid
for production 94e6741. All integration records below are synthetic TEMP-table data
on explicitly verified localhost jyotishasha_local, never production or app rows.

## Mangal calculation and export readiness

The finalized production Manglik evaluator is unchanged and remains pinned to
94e6741728b2f234ab46dcb36063611172ed4547. Lagna+Moon, Jupiter-only support,
Kendra/dignity cancellation, sparse Strong/Partial membership and Hindi results
retain the completed 25/25 production evidence. Runtime versions/Moshier and 18/18
synthetic behavior parity are established; raw floating-point longitude equality
is not required. There is no repeat calculation audit or new public diagnostic API.

`manglik_export.py` is now the execution runner for the two existing SELECT files.
It defaults to a no-op and requires --execute plus an owner-reviewed operation
authorization before any connection. Its metadata gate validates exact libpq host,
port, database and role; verify-full; approved CA path and SHA-256; negotiated TLS;
transaction isolation/read-only mode; search_path=pg_catalog; role attributes,
ownership/reachable roles; DDL/TEMP, table/column rights, and executable routines.
It denies callable non-system/SECURITY DEFINER routines and known side-effecting
built-ins, rather than invoking routines or trusting declared volatility.

Important: PUBLIC function/TEMP grants can defeat a nominal SELECT-only role.
The guard will block such configurations. A DBA must review actual effective
grants and any PUBLIC changes and their impact on other roles; this change set
does not issue CREATE ROLE/GRANT/REVOKE or silently weaken that requirement.
Read-only transactions complement least privilege; they are not proof of it.
RLS-enabled/non-table app_users or expanded privilege scope also fail closed.

Storage preflight is implemented for the current Windows workstation: fully
encrypted BitLocker volume with Protection On; protected directory ACL owned by
the operator; only operator/SYSTEM/Administrators allow entries; inherited file
rights; no reparse points, repositories, known OneDrive/temp folders, nested
directories, unsafe file owners/ACLs. It performs checks only, never changes ACLs
or enables encryption. Missing cmdlet/permissions/unverified encryption fails.
Other OS storage needs a separately reviewed encryption adapter, not a boolean
override. No actual export directory has been approved or provisioned here.

The seven-key projection and constant linkage/birthplace markers are unchanged.
Export streams and counts share one read-only repeatable-read transaction. Row
projection validation, count reconciliation, exclusive output creation, fsync and
streaming SHA-256 are implemented. Failed/partial output is quarantined. No DB
objects are created, no DB transaction committed. Offline comparator CLI now also
blocks socket operations, subprocess execution and DB/application imports through
a Python audit hook; run it standalone with -B on a machine with egress disabled
for additional enforcement. No real data is used in tests.

## Targeted writer and recovery

`manglik_writer.py` uses the same pinned engine and only this mutation:

```sql
static_dosh = (static_dosh - 'manglik') || :new_manglik_entry
```

The database update is atomic and also sets ONLY four new provenance columns:
`manglik_calculation_version`, `manglik_calculated_at`, `manglik_input_digest`,
`manglik_correction_run_id`. The standalone Manglik version is 2; global
STATIC_ASTROLOGY_VERSION remains 1 and its timestamp remains untouched.
Model and migration f18b2c7d903a declare those columns nullable with no defaults;
the migration does not calculate or backfill and has NOT been applied.

Selection scans linked profiles in keyset pages, with an immutable upper ID
captured in the encrypted journal. A run handles at most batch_size retry rows
plus batch_size*max_batches newly scanned rows. Resume uses the same journal and
keys; it retries failures/conflicts below the cursor. New IDs are excluded from
an existing run. Unlinked/incomplete/invalid rows and non-object or missing JSON
roots are left untouched. Missing/malformed roots need an owner-approved repair
policy; reconstructing unrelated Kaal Sarp/Yog is intentionally not attempted.
Malformed Manglik members inside an otherwise valid object can be corrected
without disturbing its other entries. Valid unchanged results receive only
Manglik provenance (the JSON member merge preserves all other fields).

The CAS checks all five birth fields, linkage, current Manglik presence/value and
the four previous provenance values. Concurrent unrelated JSON is merged and
preserved. Changed birth/Manglik/provenance causes no write and a retryable conflict.
A fresh run recalculates/validates the actual current result even for version 2;
matching keyed input fingerprint and membership make it idempotent. Ordinary full
snapshot application now clears targeted provenance, including invalidation and
account deletion paths, so it never claims a prior correction describes later facts.

Before each possible write, a Fernet-authenticated encrypted recovery entry is
fsynced. It contains profile ID, old/new Manglik member and provenance, run identity
and a keyed input fingerprint, never names, contacts, raw birth values, full dosh
or Yog. Journal sequence/run identity is verified. An OS lock prevents duplicate
processes on one journal; each successful row commits independently. A durable
prepared entry can recover a commit whose completion event was lost, without
writing again. Invalid/truncated/tampered journals fail closed; retain them for
controlled recovery rather than ignoring damaged records. Do not lose the keys.

Conditional rollback restores only the original Manglik member and its four
provenance values if current birth fingerprint, member and written provenance
still match. Later unrelated JSON remains intact. Later birth or Manglik edits,
full recalculations and deletion prevent restoration. Rollback is bounded,
resumable and idempotent; conflicts are retained for review and do not starve later
records. Journals that contain such conflicts cannot claim complete rollback.

The persistent input HMAC key is separate from the recovery encryption key;
key changes invalidate fingerprint-based resume/idempotency. Keep the keys inside
the verified directory with operator-only ACLs. Recovery records and encryption
keys must survive the approved rollback window; proposed window is 30 days after
acceptance, subject to owner approval. Raw comparison snapshots/partials/logs
retain the shorter existing 24-hour-after-acceptance / seven-day maximum policy.
Keep the input HMAC key for future targeted runs or perform an approved rotation;
do not destroy keys required by an outstanding recovery journal.

## Ashtakoot closure

Source of truth is modules/love/ashtakoot_love.py. Exact tables/conventions:

| Koota | Maximum | Implementation |
|---|---:|---|
| Varna | 1 | RASHI_TO_VARNA / VARNA_ORDER; groom rank >= bride |
| Vashya | 2 | RASHI_TO_VASHYA / VASHYA_SCORE_MATRIX; Sagittarius and Capricorn split at 15 degrees |
| Tara | 3 | NAKSHATRAS_27 / NAK_INDEX; inclusive bidirectional counts; bad remainders 3,5,7; each direction contributes 1.5 |
| Yoni | 4 | FEMALE_NAK_TO_YONI / MALE_NAK_TO_YONI, YONI_SWORN_ENEMIES, _YONI_OTHER_PAIRS / YONI_RELATION; unspecified pairs default 2 |
| Graha Maitri | 5 | RASHI_LORD / FRIEND / ENEMY; same or mutual-friend 5, friend-neutral 4, neutral-neutral 3, one-enemy 1, mutual-enemy 0 |
| Gana | 6 | NAKSHATRA_TO_GANA / GANA_SCORE; equal 6, Deva-Manushya 5, Manushya-Rakshasa 3, Deva-Rakshasa 1 |
| Bhakoot | 7 | RASHI_INDEX / _pos / _lords_friendly; 1/1,7/7,3/11,4/10 auspicious; 2/12,5/9,6/8 dosha with same-lord/mutual-friend cancellation |
| Nadi | 8 | NAKSHATRA_TO_NADI / RASHI_LORD; different Nadi 8; same Nadi 0 unless same sign/lord convention cancels |

Disputed conventions already identified in existing 39 audit fixtures remain
unchanged: Vashya/Gana score tables, Yoni non-enemy defaults, Maitri neutral-enemy
value and Bhakoot/Nadi cancellations. Matching another application's total is not
a scoring specification. The external 18.5 vs 15 discrepancy is UNVERIFIED: its
eight-koota breakdown, matched Moon facts and role/convention inputs are absent.
Do not attribute a 3.5-point difference to any individual koota without that evidence.

One definite invalid-input defect was fixed: unknown Rashi names could compare
as None==None in the lord lookup and falsely cancel same-Nadi dosha. They now
return invalid/0 instead. This cannot explain a valid-chart 18.5 vs 15 mismatch.
Engine version is ashtakoot-2026.10-p1.1. The existing 108-pada fixture domain is
reused to verify all 11,664 valid ordered Moon pairs against approved 94e6741:
all koota details/scores and totals remain identical. No disputed convention or
valid-chart score is changed. No reports or PDFs were regenerated.

## Prepared commands and approvals

No-op commands are safe to run locally and never connect:

```powershell
.\venv\Scripts\python.exe -B scripts/manglik_export.py
.\venv\Scripts\python.exe -B scripts/manglik_writer.py apply
```

Owner-reviewed authorization JSON belongs inside the verified restricted directory.
It contains NO passwords/URLs; use an existing approved libpq service/credential
facility. Values below are placeholders requiring actual approved evidence:

```json
{
  "approved_operation": "metadata",
  "approval_reference": "OWNER-APPROVAL-REFERENCE",
  "service": "jyotishasha_manglik_readonly",
  "host": "OWNER-APPROVED-TLS-HOSTNAME",
  "port": "5432",
  "dbname": "OWNER-APPROVED-DATABASE",
  "user": "OWNER-APPROVED-ROLE",
  "sslrootcert": "C:/OWNER-APPROVED-CA.pem",
  "sslrootcert_sha256": "OWNER-VERIFIED-CA-SHA256",
  "storage_directory": "C:/OWNER-APPROVED-ENCRYPTED-DIRECTORY",
  "journal_name": "manglik-run-001.enc"
}
```

Export authorization uses approved_operation=export and a SELECT-only role with
SELECT on exactly the seven source columns, no table-wide SELECT. Writer/rollback
uses its separately approved service/role with SELECT on id, firebase_uid, the
five birth fields, static_dosh and four new provenance fields, UPDATE on only
static_dosh and those four fields, no table-level UPDATE, INSERT, DELETE, TRUNCATE,
DDL/TEMP or callable unsafe routines. Do not use application credentials.

Prepared execution commands (NOT run):

```powershell
.\venv\Scripts\python.exe -B scripts/manglik_export.py --operation metadata --execute --authorization "<restricted-dir>/metadata-approval.json"
.\venv\Scripts\python.exe -B scripts/manglik_export.py --operation export --execute --authorization "<restricted-dir>/export-approval.json"
.\venv\Scripts\python.exe -B scripts/compare_manglik_v2.py --sanitized-snapshot "<restricted-dir>/manglik.snapshot.jsonl"
.\venv\Scripts\python.exe -B scripts/manglik_writer.py apply --execute --authorization "<restricted-dir>/write-approval.json" --batch-size 50 --max-batches 10
.\venv\Scripts\python.exe -B scripts/manglik_writer.py rollback --execute --authorization "<restricted-dir>/rollback-approval.json" --batch-size 50
```

Require explicit owner approval for: metadata-only connection/role evidence;
encrypted destination/CA/retention configuration; secure export and offline
comparison; reviewed migration deployment before the changed model is loaded;
targeted writer scope/canary/batch bounds and recovery window; and any rollback.
Migration operator must verify production's actual Alembic head and authorize
only the reviewed pending revision, not inadvertently run unrelated ancestor
migrations. No migration command has been executed locally or on production.

Local engineering is complete. Live privileges/TLS/storage and owner authorization
remain operational prerequisites. Production execution remains NO-GO until those
are satisfied; no additional calculation audit is required by this change set.

## Final local execution record — 2026-10-15

The existing implementation was retained and verified in place. This closure
execution changed `scripts/manglik_export.py` (independent transaction-mode and
fetch-bound guards), `test_manglik_security.py` (snapshot rejection regression and
corrected metadata mock), and `docs/manglik_runtime_diagnostic.md` (completed
baseline status). It created `scripts/manglik_operator_requirements.txt` to pin
the locally tested authenticated encryption dependency, cryptography 50.0.0,
for a dedicated operator environment. No dependencies were installed here.
This report was also updated. All unrelated working-tree changes were preserved.

The finalized change set already present at execution start consists of:
`scripts/manglik_security.py`, `scripts/manglik_storage_preflight.ps1`,
`scripts/manglik_export.py`, `scripts/manglik_writer.py`,
`migrations/versions/f18b2c7d903a_add_manglik_provenance.py`,
`modules/models_user.py`, `modules/services/static_astrology_extractor.py`,
`modules/love/ashtakoot_love.py`, `test_manglik_security.py`,
`test_manglik_writer.py`, `test_manglik_postgres_local.py`, and
`test_ashtakoot_final_closure.py`. Existing comparator, runtime diagnostic,
snapshot SQL/procedure and scoring fixtures were reused.

Focused closure verification: 27/27 PASS (security, writer, synthetic local
PostgreSQL and Ashtakoot closure). Local PostgreSQL: 5/5 PASS with verified
loopback database identity and session TEMP tables only; no migration applied.
Broader regression command: 117/117 PASS across security, writer, comparator,
runtime diagnostic, Ashtakoot closure/Phase 1, and Mangal P0/cancellation tests.
The earlier run failed one synthetic metadata mock; its query discriminator was
corrected, then the complete command passed. Existing fixture logging and
ResourceWarnings did not fail tests. `git diff --check` passed; both operator
CLI defaults returned `connection_opened: false`.
The valid-chart Ashtakoot fixture domain remains 11,664/11,664 identical in
all eight details/scores and totals to the approved baseline. This establishes
regression parity, not universal agreement across scoring traditions.

The only outstanding execution prerequisites are owner-approved exact production
connection identity/CA, DBA-verified effective role privileges, protected encrypted
storage and retention/key custody, reviewed migration deployment, export approval,
and writer/canary/batch/recovery authorization. Conditional rollback requires its
own operation approval. The external scoring discrepancy remains unverified
pending the other application's eight-koota breakdown and matched chart inputs;
it does not block the local implementation or justify changing valid scores.

## Selective local release commit

The release includes the fifteen owner-approved closure files plus these direct
runtime dependencies: `scripts/compare_manglik_v2.py`,
`scripts/manglik_comparison_v2/birth_timezone.py`,
`scripts/manglik_comparison_v2/lahiri.py`,
`scripts/manglik_comparison_v2/positions.py`,
`scripts/manglik_comparison_v2/manglik.py`,
`scripts/manglik_comparison_v2/provenance.json`,
`scripts/manglik_comparison_v2/README.md`,
`scripts/manglik_comparison_v2/.gitattributes`,
`docs/manglik_v2_snapshot_select.sql`, and `docs/manglik_v2_snapshot_counts.sql`.
No comparison snapshots, credentials, PDFs or unrelated backfill scripts are included.

The PostgreSQL tests now use an explicit `MANGLIK_LOCAL_TEST_DSN` environment
variable, reject destinations other than localhost/jyotishasha_local before
connecting, and verify loopback server identity before creating TEMP fixtures.
They skip when no local DSN is supplied. No untracked test or hardcoded credential
is required by the release. Synthetic test temporary directories are created
directly under the repository so an untracked `tmp` directory is not required.
The operator dependency file is separate from the production application runtime.
The scoped `.gitattributes` disables newline conversion for the pinned Python
sources, preserving manifest hashes on Windows and Linux checkouts.
Selective-commit validation: 72/72 focused tests passed, including all five
synthetic localhost PostgreSQL tests, the comparator, and Ashtakoot Phase 1 and
closure fixtures. The 22 tests requiring only committed closure files also passed.
The valid Moon-pair comparison remains 11,664/11,664 unchanged. No migrations
were executed and no production database was accessed.

The commit is ready for separate deployment review, contingent on the documented
migration ordering and live security prerequisites. It does not authorize a
deployment, production connection, migration, export, correction or rollback.
