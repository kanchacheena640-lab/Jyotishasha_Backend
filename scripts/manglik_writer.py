"""Manglik-only correction and conditional rollback; no connection on import.

CLI never connects without --execute and an operation-specific owner authorization.
Recovery records are encrypted/authenticated and fsynced BEFORE a database write.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import uuid

try:
    from scripts.compare_manglik_v2 import ProductionCalculator, InvalidBirth, validate_birth, verified_sources
    from scripts.manglik_security import connect_verified, require, storage_preflight, SecurityFailure
except ModuleNotFoundError:
    from compare_manglik_v2 import ProductionCalculator, InvalidBirth, validate_birth, verified_sources
    from manglik_security import connect_verified, require, storage_preflight, SecurityFailure

MANGLIK_CALCULATION_VERSION = 2  # Independent provenance; global static version remains 1.
BIRTH_FIELDS = ("dob", "tob", "pob", "lat", "lng")
PROVENANCE_FIELDS = ("manglik_calculation_version", "manglik_calculated_at", "manglik_input_digest", "manglik_correction_run_id")
SELECT_FIELDS = ("id", "firebase_uid") + BIRTH_FIELDS + ("static_dosh",) + PROVENANCE_FIELDS


def plain(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def birth_digest(row, key):
    payload = json.dumps({field: row.get(field) for field in BIRTH_FIELDS}, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def state(row):
    document = row["static_dosh"]
    return {"present": "manglik" in document, "member": deepcopy(document.get("manglik")),
            "provenance": {field: plain(row.get(field)) for field in PROVENANCE_FIELDS}}


def merge_member(document, desired):
    """Used by tests and recovery; never replaces unrelated JSON members."""
    require(isinstance(document, dict), "non_object_json")
    patched = deepcopy(document)
    patched.pop("manglik", None)
    if desired["present"]:
        patched["manglik"] = deepcopy(desired["member"])
    return patched


class RecoveryJournal:
    def __init__(self, path, encryption_key):
        from cryptography.fernet import Fernet
        self.path = Path(path)
        self.cipher = Fernet(encryption_key)
        self.events = []

    def __enter__(self):
        # OS lock is released on process exit. The persistent lock file holds no data.
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.lock = os.fdopen(os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600), "r+b")
        if os.fstat(self.lock.fileno()).st_size == 0:
            self.lock.write(b"0")
            self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            require(not self.path.is_symlink(), "journal_symlink")
            if self.path.exists():
                for index, token in enumerate(self.path.read_bytes().splitlines()):
                    event = json.loads(self.cipher.decrypt(token))
                    require(event["sequence"] == index, "journal_sequence_invalid")
                    require(event["journal_run_id"] == (self.events[0]["run_id"] if self.events else event["run_id"]),
                            "journal_run_identity_mismatch")
                    self.events.append(event)
            self.stream = os.fdopen(os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "ab")
            return self
        except Exception:
            self.lock.close()
            raise

    def append(self, event):
        event = dict(event, sequence=len(self.events))
        event["journal_run_id"] = self.events[0]["run_id"] if self.events else event["run_id"]
        token = self.cipher.encrypt(json.dumps(event, sort_keys=True, allow_nan=False).encode())
        self.stream.write(token + b"\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.events.append(event)

    def __exit__(self, *args):
        self.stream.close()
        self.lock.close()


class PostgresRepository:
    """Explicit schema and column scope; application ORM/factory are never used."""
    def __init__(self, conn, table="public.app_users"):
        require(table in ("public.app_users", "pg_temp.manglik_writer_test"), "table_not_allowed")
        self.conn, self.table = conn, table

    def query(self, sql, params=(), fetch=True):
        with self.conn.cursor() as cursor:
            cursor.execute("SET LOCAL search_path = pg_catalog")
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute(sql, params)
            if fetch:
                names = [column[0] for column in cursor.description]
                return [dict(zip(names, (plain(value) for value in row))) for row in cursor.fetchall()]
            return cursor.rowcount

    def upper_id(self):
        return self.query(f"SELECT COALESCE(max(id),0) AS maximum FROM {self.table} WHERE firebase_uid IS NOT NULL")[0]["maximum"]

    def page(self, after, upper, size):
        rows = self.query(f"SELECT {','.join(SELECT_FIELDS)} FROM {self.table} WHERE firebase_uid IS NOT NULL AND id > %s AND id <= %s ORDER BY id LIMIT %s", (after, upper, size))
        self.conn.rollback()  # Release read transaction before CPU-heavy calculation.
        return rows

    def get(self, profile_id):
        rows = self.query(f"SELECT {','.join(SELECT_FIELDS)} FROM {self.table} WHERE id = %s", (profile_id,))
        self.conn.rollback()
        return rows[0] if rows else None

    def patch(self, snapshot, expected, desired):
        # CAS matches ONLY the old Manglik member, provenance and birth inputs.
        # Concurrent unrelated JSON changes are preserved by server-side member merge.
        birth_guard = " AND ".join(f"{field} IS NOT DISTINCT FROM %s" for field in BIRTH_FIELDS)
        provenance_guard = " AND ".join(f"{field} IS NOT DISTINCT FROM %s" for field in PROVENANCE_FIELDS)
        update_provenance = ", ".join(f"{field} = %s" for field in PROVENANCE_FIELDS)
        entry = {"manglik": desired["member"]} if desired["present"] else {}
        sql = f"""UPDATE {self.table} SET static_dosh = (static_dosh - 'manglik') || %s::jsonb,
            {update_provenance}
            WHERE id = %s AND jsonb_typeof(static_dosh) = 'object'
              AND firebase_uid IS NOT DISTINCT FROM %s
              AND (static_dosh ? 'manglik') = %s
              AND (static_dosh -> 'manglik') IS NOT DISTINCT FROM %s::jsonb
              AND {birth_guard} AND {provenance_guard}"""
        old_member = json.dumps(expected["member"]) if expected["present"] else None
        params = (json.dumps(entry),) + tuple(desired["provenance"][f] for f in PROVENANCE_FIELDS) + (
            snapshot["id"], snapshot.get("firebase_uid"), expected["present"], old_member,
        ) + tuple(snapshot.get(f) for f in BIRTH_FIELDS) + tuple(expected["provenance"].get(f) for f in PROVENANCE_FIELDS)
        try:
            changed = self.query(sql, params, fetch=False) == 1
            if changed:
                self.conn.commit()
            else:
                self.conn.rollback()
            return changed
        except Exception:
            self.conn.rollback()
            raise


class ManglikWriter:
    def __init__(self, repository, journal, calculator, input_hmac_key):
        require(len(input_hmac_key) >= 32, "hmac_key_too_short")
        self.repo, self.journal, self.calculator, self.key = repository, journal, calculator, input_hmac_key
        source_files, commit = verified_sources()
        provenance = {"commit": commit, "source_hashes": {n: hashlib.sha256(s.encode()).hexdigest() for n, s in source_files.items()},
                      "version": MANGLIK_CALCULATION_VERSION, "hmac_key_id": hashlib.sha256(self.key).hexdigest()}
        if journal.events:
            manifest = journal.events[0]
            require(manifest["type"] == "manifest" and manifest["engine"] == provenance, "recovery_provenance_mismatch")
        else:
            manifest = {"type": "manifest", "run_id": str(uuid.uuid4()), "upper_id": repository.upper_id(), "engine": provenance}
            journal.append(manifest)
        self.manifest = manifest

    def latest(self, event_type):
        if not hasattr(self, "_indexes"):
            self._indexes, self._seen = {"prepared": {}, "outcome": {}}, 0
        for event in self.journal.events[self._seen:]:
            if event["type"] in self._indexes:
                self._indexes[event["type"]][event["id"]] = event
        self._seen = len(self.journal.events)
        return self._indexes[event_type]

    def outcome(self, profile_id, status):
        self.journal.append({"type": "outcome", "id": profile_id, "status": status})

    def process(self, snapshot):
        profile_id = snapshot["id"]
        if snapshot.get("firebase_uid") is None:
            self.outcome(profile_id, "unlinked")
            return
        if any(snapshot.get(f) in (None, "") for f in BIRTH_FIELDS):
            self.outcome(profile_id, "incomplete")
            return
        try:
            validate_birth(snapshot)
            fingerprint = birth_digest(snapshot, self.key)
        except (InvalidBirth, ValueError, TypeError):
            self.outcome(profile_id, "invalid")
            return
        if not isinstance(snapshot.get("static_dosh"), dict):
            self.outcome(profile_id, "unknown_json_root")
            return
        before = state(snapshot)
        prepared = self.latest("prepared").get(profile_id)
        if prepared and before == prepared["after"] and fingerprint == prepared["birth_digest"]:
            self.outcome(profile_id, "applied_recovered")
            return
        try:
            birth = {f: snapshot[f] for f in ("dob", "tob", "lat", "lng")}
            severity = self.calculator(birth)
            require(severity in ("Strong", "Partial", "None", "Cancelled"), "invalid_engine_output")
        except InvalidBirth:
            self.outcome(profile_id, "invalid")
            return
        except Exception:
            self.outcome(profile_id, "failed")
            return
        desired = {"present": severity in ("Strong", "Partial"),
                   "member": {"severity": severity} if severity in ("Strong", "Partial") else None}
        if before["provenance"]["manglik_calculation_version"] == MANGLIK_CALCULATION_VERSION and before["provenance"]["manglik_input_digest"] == fingerprint and all(before[k] == desired[k] for k in ("present", "member")):
            self.outcome(profile_id, "already_current")
            return
        desired["provenance"] = {"manglik_calculation_version": MANGLIK_CALCULATION_VERSION,
            "manglik_calculated_at": datetime.now(timezone.utc).isoformat(),
            "manglik_input_digest": fingerprint, "manglik_correction_run_id": self.manifest["run_id"]}
        # No names, contacts, birth values, full JSON or astrology snapshot in recovery.
        self.journal.append({"type": "prepared", "id": profile_id, "before": before,
                             "after": desired, "birth_digest": fingerprint})
        try:
            self.outcome(profile_id, "applied" if self.repo.patch(snapshot, before, desired) else "conflict")
        except Exception:
            self.outcome(profile_id, "failed")

    def run(self, batch_size=50, max_batches=10):
        require(1 <= batch_size <= 500 and max_batches >= 1, "invalid_bounds")
        outcomes = self.latest("outcome")
        # Retry failures/conflicts once per invocation, even below the durable cursor.
        retries = {i for i, e in outcomes.items() if e["status"] in ("failed", "conflict")}
        # Include prepared-but-not-recorded rows after a crash or uncertain commit.
        retries |= set(self.latest("prepared")) - set(outcomes)
        for profile_id in sorted(retries)[:batch_size]:
            row = self.repo.get(profile_id)
            if row:
                self.process(row)
            else:
                self.outcome(profile_id, "deleted")
        cursor = max((e["cursor"] for e in self.journal.events if e["type"] == "checkpoint"), default=0)
        for _ in range(max_batches):
            page = self.repo.page(cursor, self.manifest["upper_id"], batch_size)
            if not page:
                self.journal.append({"type": "checkpoint", "cursor": cursor, "exhausted": True})
                break
            for row in page:
                prior = self.latest("outcome").get(row["id"])
                if not prior or prior["status"] not in ("applied", "applied_recovered", "already_current", "rolled_back"):
                    self.process(row)
                cursor = row["id"]
                self.journal.append({"type": "checkpoint", "cursor": cursor, "exhausted": False})
        return dict(Counter(e["status"] for e in self.latest("outcome").values()))

    def rollback(self, limit=100):
        require(1 <= limit <= 500, "invalid_rollback_bound")
        attempted = 0
        for profile_id, prepared in sorted(self.latest("prepared").items()):
            prior = self.latest("outcome").get(profile_id)
            if prior and prior["status"] in ("rolled_back", "rollback_conflict", "deleted"):
                continue
            if attempted >= limit:
                break
            attempted += 1
            row = self.repo.get(profile_id)
            if row is None:
                self.outcome(profile_id, "deleted")
                continue
            try:
                fingerprint = birth_digest(row, self.key)
            except Exception:
                self.outcome(profile_id, "rollback_conflict")
                continue
            if not isinstance(row.get("static_dosh"), dict) or fingerprint != prepared["birth_digest"]:
                self.outcome(profile_id, "rollback_conflict")
                continue
            current = state(row)
            # Recover a rollback committed before its final journal event.
            if current == prepared["before"]:
                self.outcome(profile_id, "rolled_back")
                continue
            if current != prepared["after"]:
                self.outcome(profile_id, "rollback_conflict")
                continue
            try:
                restored = self.repo.patch(row, prepared["after"], prepared["before"])
                self.outcome(profile_id, "rolled_back" if restored else "rollback_conflict")
            except Exception:
                self.outcome(profile_id, "rollback_failed")
        return dict(Counter(e["status"] for e in self.latest("outcome").values()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("apply", "rollback"))
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-batches", type=int, default=10)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "not_executed", "connection_opened": False}))
        return 0
    conn = None
    try:
        approved = json.loads(args.authorization.read_text(encoding="utf-8"))
        require(approved["approved_operation"] == args.operation and bool(approved["approval_reference"]), "authorization_mismatch")
        directory = storage_preflight(approved["storage_directory"])
        require(args.authorization.resolve().parent == directory, "authorization_not_in_protected_storage")
        require(Path(approved["journal_name"]).name == approved["journal_name"], "journal_name_invalid")
        require(approved["journal_name"] not in ("recovery.key", "input-hmac.key"), "journal_name_reserved")
        if args.operation == "rollback":
            require((directory / approved["journal_name"]).is_file(), "rollback_journal_missing")
        encryption_key = (directory / "recovery.key").read_bytes().strip()
        hmac_key = (directory / "input-hmac.key").read_bytes()
        # Full source verification and synthetic-only runtime gate happen before connecting.
        calculator = ProductionCalculator()
        import swisseph as swe
        import importlib.metadata
        import sys
        require(sys.version_info[:3] == (3, 11, 9), "python_runtime_mismatch")
        require(swe.version == "2.10.03", "native_runtime_mismatch")
        for package, version in {"pyswisseph": "2.10.3.2", "pytz": "2025.2", "timezonefinder": "6.5.2"}.items():
            require(importlib.metadata.version(package) == version, "package_runtime_mismatch")
        calculator.positions.ensure_lahiri_mode()
        for year in (1900, 1950, 2000, 2050):
            for body in (swe.SUN, swe.MOON, swe.MARS, swe.JUPITER):
                _, flags = swe.calc(swe.julday(year, 1, 15, 12.0), body, swe.FLG_SIDEREAL | swe.FLG_SWIEPH)
                require(bool(flags & swe.FLG_MOSEPH) and bool(flags & swe.FLG_SIDEREAL), "effective_backend_mismatch")
        conn = connect_verified(approved, readonly=False)
        with RecoveryJournal(directory / approved["journal_name"], encryption_key) as journal:
            writer = ManglikWriter(PostgresRepository(conn), journal, calculator, hmac_key)
            counts = writer.run(args.batch_size, args.max_batches) if args.operation == "apply" else writer.rollback(args.batch_size)
        checkpoint = next((e for e in reversed(journal.events) if e["type"] == "checkpoint"), {})
        print(json.dumps({"counts": counts, "operation": args.operation, "global_static_version_changed": False,
                          "upper_id": writer.manifest["upper_id"], "cursor": checkpoint.get("cursor",0),
                          "exhausted": checkpoint.get("exhausted",False)}))
        return 2 if any(counts.get(k) for k in ("failed", "conflict", "rollback_failed", "rollback_conflict")) else 0
    except SecurityFailure as exc:
        print(json.dumps({"status": "failed", "guard_code": str(exc), "retain_recovery_files": True}))
        return 1
    except Exception:
        print(json.dumps({"status": "failed", "error": "Operation failed; details suppressed; retain recovery files"}))
        return 1
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
