"""Guarded SELECT-only export. No connection without explicit --execute."""
import argparse
import hashlib
import json
import os
from pathlib import Path

try:
    from scripts.manglik_security import connect_verified, require, storage_preflight, SecurityFailure
    from scripts.compare_manglik_v2 import old_classification, validate_birth, verified_sources
except ModuleNotFoundError:
    from manglik_security import connect_verified, require, storage_preflight, SecurityFailure
    from compare_manglik_v2 import old_classification, validate_birth, verified_sources

ROOT = Path(__file__).resolve().parents[1]
KEYS = {"firebase_uid", "dob", "tob", "pob", "lat", "lng", "static_dosh"}


def validate_export_row(row):
    require(isinstance(row, dict) and set(row) == KEYS, "export_fields_invalid")
    require(row["firebase_uid"] == "linked" and row["pob"] == "present", "export_markers_invalid")
    validate_birth(row)
    value = row["static_dosh"]
    require(value is None or value == "malformed" or value == {} or value == {"manglik": None}
            or value in ({"manglik": {"severity": "Strong"}}, {"manglik": {"severity": "Partial"}}),
            "export_json_projection_invalid")
    return old_classification(row)[1]


def sql_artifacts():
    select = (ROOT / "docs/manglik_v2_snapshot_select.sql").read_text(encoding="utf-8")
    counts = (ROOT / "docs/manglik_v2_snapshot_counts.sql").read_text(encoding="utf-8")
    require(select.split("SELECT jsonb_build_object(", 1)[0] == counts.split("SELECT jsonb_build_object(", 1)[0],
            "export_selection_mismatch")
    return select, counts


def export_snapshot(conn, directory, fetch_size=100):
    # Enforce the snapshot contract here as well as at connection preflight, so
    # callers cannot accidentally export/reconcile in separate snapshots.
    require(not conn.autocommit, "export_autocommit_forbidden")
    require(1 <= fetch_size <= 1000, "export_fetch_size_invalid")
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL search_path = pg_catalog")
        cursor.execute("SELECT current_setting('transaction_read_only'), "
                       "current_setting('transaction_isolation')")
        require(cursor.fetchone() == ('on', 'repeatable read'), "export_snapshot_mode_invalid")
    select, count_sql = sql_artifacts()
    path = Path(directory) / "manglik.snapshot.part"
    counts_path = Path(directory) / "manglik.export_counts.json"
    require(not path.exists() and not counts_path.exists(), "export_output_already_exists")
    compared, missing, malformed = 0, 0, 0
    # Files inherit the verified restricted directory ACL; POSIX mode is defense in depth.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
        with conn.cursor(name="manglik_export") as cursor:
            cursor.itersize = fetch_size
            cursor.execute(select)
            for (text,) in cursor:
                row = json.loads(text)
                issue = validate_export_row(row)
                missing += issue == "missing"
                malformed += issue == "malformed"
                output.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
                compared += 1
        output.flush()
        os.fsync(output.fileno())
    with conn.cursor() as cursor:
        cursor.execute(count_sql)
        counts = json.loads(cursor.fetchone()[0])
    require(counts["eligible"] == compared and counts["old_json_missing"] == missing
            and counts["old_json_malformed"] == malformed, "export_count_mismatch")
    require(counts["database_total"] == sum(counts[k] for k in ("unlinked", "incomplete", "invalid_input", "eligible")),
            "export_census_mismatch")
    fd = os.open(counts_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(counts, output)
        output.flush()
        os.fsync(output.fileno())
    conn.rollback()  # Ends the SAME read-only snapshot; never commits or writes database state.
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"counts": counts, "snapshot_sha256": digest.hexdigest(),
            "snapshot_status": "validated_part_file; owner acceptance required"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--operation", choices=("metadata", "export"), default="metadata")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "not_executed", "connection_opened": False}))
        return 0
    conn = None
    try:
        approved = json.loads(args.authorization.read_text(encoding="utf-8"))
        require(approved["approved_operation"] == args.operation and bool(approved["approval_reference"]), "authorization_mismatch")
        sources, commit = verified_sources()
        directory = storage_preflight(approved["storage_directory"])
        require(args.authorization.resolve().parent == directory, "authorization_not_in_protected_storage")
        conn = connect_verified(approved, readonly=True)
        report = export_snapshot(conn, directory) if args.operation == "export" else {"metadata_preflight_pass": True}
        report["source_commit"] = commit
        print(json.dumps(report, indent=2))
        return 0
    except SecurityFailure as exc:
        print(json.dumps({"status": "failed", "guard_code": str(exc), "quarantine_partial_outputs": True}))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "error": "Preflight/export failed; no exception text disclosed; quarantine partial outputs"}))
        return 1
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
