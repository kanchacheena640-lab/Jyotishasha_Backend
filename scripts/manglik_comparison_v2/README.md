# Manglik comparison V2

Offline comparison only. No database adapter, application startup, ORM, write
mode, snapshot application, migrations or version bump. All unrelated astrology
fields remain untouched. No complete Kundali or Yog/Kaal Sarp evaluation runs.

## Source isolation

`provenance.json` identifies production commit `94e6741` by full commit ID and
SHA-256 hashes. `manglik.py`, `birth_timezone.py`, and `lahiri.py` are byte-for-byte
copies from that commit. `positions.py` contains exact AST source segments for
the production chart functions and their constant tables. The loader verifies
hashes before execution and injects only their pinned dependencies. It never
imports the working tree's `full_kundali_api`, `services`, or application modules.
Tests verify the copies directly against Git, including chart function ASTs.

Swiss Ephemeris uses its normal runtime configuration as in the production
entry point. Before interpreting real-data comparisons, match production's
Python dependencies, Swiss Ephemeris version and ephemeris assets/configuration.
Source equivalence alone does not establish runtime asset equivalence.

## Input and command

Use an owner-approved, protected JSONL snapshot containing one unique profile
per line. Required keys are `firebase_uid`, `dob`, `tob`, `pob`, `lat`, `lng`, and
`static_dosh`. Replace Firebase identities with opaque linkage markers; preserve
NULL for unlinked rows. Omit names, email, phone and credentials. `id` is optional
and never reported. Do not alter required astronomical inputs if the purpose is
to measure actual impact: deidentified birth data still requires restricted
handling. This tool does not obtain or authorize snapshots.

```powershell
.\venv\Scripts\python.exe -B scripts/compare_manglik_v2.py --sanitized-snapshot <approved-jsonl-path>
.\venv\Scripts\python.exe -B -m unittest test_manglik_comparison_v2 -v
```

The tool reads the file and prints aggregate JSON to stdout. It creates no
output files. Exceptions and calculator stdout/stderr are suppressed so malformed
inputs are not echoed. Missing dependencies, bad manifests or unreadable input
fail startup with a generic error and nonzero exit status. Per-profile failures
are counted and processing continues; inspect counts even if exit status is zero.
Run as a dedicated fresh process, not inside an existing application worker.

## Selection and counters

All linked, complete profiles supplied in the snapshot are considered regardless
of global static astrology version. The frozen completeness contract requires
non-NULL/non-empty DOB, TOB, POB, latitude and longitude. Missing fields skip;
invalid date/time formats, dates, coordinates and whitespace POB count invalid.
Coordinate zero is valid. Timezone resolution failures count invalid separately.

- `total_eligible`: complete, locally validated profiles attempted by the engine.
- `successfully_compared = changed + unchanged + unknown_comparisons`.
- `total_eligible = successfully_compared + failed + invalid_birth_resolution`.
- `total_profiles = skipped + invalid_input + total_eligible`.
- `invalid = invalid_input + invalid_birth_resolution`.

Old JSON counts cover all supplied dictionary profiles, including skipped rows.
Missing/NULL JSON is unknown; non-object JSON or an invalid Manglik entry is
malformed. A valid object without a Manglik key is Absent. Unrelated JSON entries
are not interpreted or modified. Old Strong/Partial entries are compared only
by their severity, not metadata.

Changed/unchanged apply only where the old classification is known. Unknown
comparisons are reported separately, with unknown-to-membership counts, rather
than fabricated historical transitions. Stored transitions normalize new None
and Cancelled to Absent; a separate matrix retains the new engine's exact
severity. Old Absent cannot distinguish historical None from Cancelled.

Illustrative synthetic transition fixture (not production statistics): three
profiles, Strong to Cancelled, Absent to Strong, Partial to Strong. The result is
3 eligible, 3 compared, 3 changed, 0 unchanged, 0 skipped/invalid/failed,
1 Manglik-to-Non-Manglik and 1 Non-Manglik-to-Manglik. Stored transitions are
Strong to Absent, Absent to Strong, and Partial to Strong, each with count 1.

## Version recommendation and future permissions

Prefer separate Manglik provenance, such as a nullable
`manglik_calculation_version` plus `manglik_calculated_at`, after a separately
reviewed schema change. The future targeted writer should update only the
Manglik JSON member and Manglik provenance atomically, preserving every other
`static_dosh` member and all other astrology columns. Do not advance the global
version/timestamp to imply a whole snapshot recalculation.

Existing rows should initially have unknown Manglik provenance. Do not infer
provenance from global version 1 or a result that happens to match. A future
version-selected writer can select unknown/stale Manglik versions, validate
birth inputs and compare state before writing. A verified unchanged Manglik
result can receive only Manglik provenance. Missing/malformed old JSON needs an
explicit repair policy; this comparator does not reconstruct unrelated facts.

Until schema approval, use a protected external comparison manifest tied to
source/runtime provenance and a snapshot identifier; it is comparison evidence,
not proof that production was updated. This implementation creates no manifest
of user data and changes no version constants.

Next stage requires approval for an authorized read-only export or SELECT-only
connection, protected snapshot handling, scope, and matched production runtime.
This tool has no live database connection path. A production write would require
separate schema/writer, backup/rollback and operational approvals. Production
backfill remains NO-GO; approved offline comparison is GO.
