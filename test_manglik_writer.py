"""Synthetic writer tests with an in-memory CAS store and encrypted local journal."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from cryptography.fernet import Fernet
from scripts.manglik_writer import ManglikWriter, RecoveryJournal, state, merge_member, BIRTH_FIELDS, PROVENANCE_FIELDS

ROOT = Path(__file__).resolve().parent


def row(profile_id=1, old=None, **changes):
    data = dict(id=profile_id, firebase_uid="synthetic", dob="1990-06-15", tob="12:00", pob="synthetic",
                lat=28.6139, lng=77.2090, static_dosh=deepcopy(old if old is not None else {"kaal_sarp": {"preserve": True}, "other": [1, 2]}),
                static_yog={"keep": {}}, lagna="old", moon_sign="old", nakshatra="old", nakshatra_pada=1,
                static_astrology_version=1, static_astrology_calculated_at="old")
    data.update({f: None for f in PROVENANCE_FIELDS})
    data.update(changes)
    return data


class MemoryRepository:
    def __init__(self, rows):
        self.rows = {r["id"]: deepcopy(r) for r in rows}
        self.writes = 0
        self.before_patch = None

    def upper_id(self):
        return max(self.rows, default=0)

    def get(self, profile_id):
        return deepcopy(self.rows.get(profile_id))

    def page(self, after, upper, size):
        return [self.get(i) for i in sorted(self.rows) if after < i <= upper][:size]

    def patch(self, snapshot, expected, desired):
        if self.before_patch:
            callback, self.before_patch = self.before_patch, None
            callback(self.rows[snapshot["id"]])
        current = self.rows[snapshot["id"]]
        if not isinstance(current["static_dosh"], dict) or state(current) != expected:
            return False
        if any(current.get(f) != snapshot.get(f) for f in BIRTH_FIELDS + ("firebase_uid",)):
            return False
        current["static_dosh"] = merge_member(current["static_dosh"], desired)
        current.update(desired["provenance"])
        self.writes += 1
        return True


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.path = Path(self.directory.name) / "recovery.enc"
        self.encryption_key, self.hmac_key = Fernet.generate_key(), b"synthetic-hmac-key-at-least-32-bytes"

    def tearDown(self):
        self.directory.cleanup()

    def run_writer(self, repository, calculator, **bounds):
        with RecoveryJournal(self.path, self.encryption_key) as journal:
            return ManglikWriter(repository, journal, calculator, self.hmac_key).run(**bounds)

    def test_transitions_preserve_all_unrelated_fields(self):
        for old in (None, "Strong", "Partial"):
            for new in ("Strong", "Partial", "None", "Cancelled"):
                with self.subTest(old=old, new=new):
                    source = row()
                    if old:
                        source["static_dosh"]["manglik"] = {"severity": old}
                    repo = MemoryRepository([source])
                    self.path = Path(self.directory.name) / f"{old}-{new}.enc"
                    self.run_writer(repo, lambda _: new)
                    actual = repo.rows[1]
                    for field in source:
                        if field not in PROVENANCE_FIELDS + ("static_dosh",):
                            self.assertEqual(actual[field], source[field])
                    self.assertEqual({k:v for k,v in actual["static_dosh"].items() if k != "manglik"},
                                     {k:v for k,v in source["static_dosh"].items() if k != "manglik"})
                    self.assertEqual(actual["static_dosh"].get("manglik"), {"severity": new} if new in ("Strong", "Partial") else None)

    def test_missing_malformed_and_incomplete_never_write(self):
        rows = [row(1, tob=None), row(2, dob="broken"), row(3, lat=None),
                row(4, static_dosh=None), row(5, static_dosh=[]), row(6, lng=float("nan"))]
        repo = MemoryRepository(rows)
        counts = self.run_writer(repo, lambda _: "Strong")
        self.assertEqual(repo.writes, 0)
        self.assertEqual(counts, {"incomplete": 2, "invalid": 2, "unknown_json_root": 2})

    def test_concurrent_birth_change_and_retry(self):
        repo = MemoryRepository([row()])
        repo.before_patch = lambda r: r.update(tob="13:00")
        self.assertEqual(self.run_writer(repo, lambda _: "Strong"), {"conflict": 1})
        self.assertEqual(repo.writes, 0)
        self.assertEqual(self.run_writer(repo, lambda _: "Partial"), {"applied": 1})
        self.assertEqual(repo.rows[1]["static_dosh"]["manglik"], {"severity": "Partial"})

    def test_concurrent_other_json_is_merged(self):
        repo = MemoryRepository([row()])
        repo.before_patch = lambda r: r["static_dosh"].update(kaal_sarp={"new": True}, added="keep")
        self.run_writer(repo, lambda _: "Strong")
        self.assertEqual(repo.rows[1]["static_dosh"]["kaal_sarp"], {"new": True})
        self.assertEqual(repo.rows[1]["static_dosh"]["added"], "keep")

    def test_failure_retry_resume_and_fixed_upper_bound(self):
        repo = MemoryRepository([row(i) for i in range(1, 5)])
        def fail(_): raise RuntimeError("synthetic private input not logged")
        self.assertEqual(self.run_writer(repo, fail, batch_size=1, max_batches=1), {"failed": 1})
        repo.rows[5] = row(5)
        self.run_writer(repo, lambda _: "Strong", batch_size=1, max_batches=1)
        self.assertEqual(repo.writes, 2)
        self.run_writer(repo, lambda _: "Strong", batch_size=2, max_batches=2)
        self.assertEqual(repo.writes, 4)
        self.assertNotIn("manglik", repo.rows[5]["static_dosh"])

    def test_backup_is_encrypted_before_write(self):
        repo = MemoryRepository([row()])
        def check(_):
            raw = self.path.read_bytes()
            self.assertNotIn(b"1990-06-15", raw)
            self.assertNotIn(b"severity", raw)
            events = [json_event for token in raw.splitlines()
                      for json_event in [__import__('json').loads(Fernet(self.encryption_key).decrypt(token))]]
            self.assertEqual(events[-1]["type"], "prepared")
            self.assertNotIn("dob", str(events))
        repo.before_patch = check
        self.run_writer(repo, lambda _: "Strong")

    def test_conditional_rollback_preserves_later_unrelated_json(self):
        repo = MemoryRepository([row()])
        self.run_writer(repo, lambda _: "Strong")
        repo.rows[1]["static_dosh"]["kaal_sarp"] = {"later": True}
        with RecoveryJournal(self.path, self.encryption_key) as journal:
            writer = ManglikWriter(repo, journal, lambda _: "Strong", self.hmac_key)
            self.assertEqual(writer.rollback(), {"rolled_back": 1})
            writer.rollback()
        self.assertEqual(repo.writes, 2)
        self.assertNotIn("manglik", repo.rows[1]["static_dosh"])
        self.assertEqual(repo.rows[1]["static_dosh"]["kaal_sarp"], {"later": True})
        self.assertTrue(all(repo.rows[1][f] is None for f in PROVENANCE_FIELDS))

    def test_rollback_refuses_new_birth_or_manglik_result(self):
        for change in (lambda r: r.update(tob="13:00"), lambda r: r["static_dosh"].update(manglik={"severity":"Partial"})):
            self.path = Path(self.directory.name) / (str(id(change)) + ".enc")
            repo = MemoryRepository([row()])
            self.run_writer(repo, lambda _: "Strong")
            change(repo.rows[1])
            with RecoveryJournal(self.path, self.encryption_key) as journal:
                result = ManglikWriter(repo, journal, lambda _: "Strong", self.hmac_key).rollback()
            self.assertEqual(result, {"rollback_conflict": 1})
            self.assertEqual(repo.writes, 1)

    def test_idempotent_new_run_and_changed_birth_rechecked(self):
        repo = MemoryRepository([row()])
        self.run_writer(repo, lambda _: "Strong")
        self.path = Path(self.directory.name) / "second.enc"
        self.assertEqual(self.run_writer(repo, lambda _: "Strong"), {"already_current": 1})
        self.assertEqual(repo.writes, 1)
        repo.rows[1]["tob"] = "13:00"
        self.path = Path(self.directory.name) / "third.enc"
        self.run_writer(repo, lambda _: "Partial")
        self.assertEqual(repo.writes, 2)

    def test_commit_crash_recovered_without_second_write(self):
        repo = MemoryRepository([row()])
        with RecoveryJournal(self.path, self.encryption_key) as journal:
            writer = ManglikWriter(repo, journal, lambda _: "Strong", self.hmac_key)
            writer.outcome = lambda *args: (_ for _ in ()).throw(SystemExit("simulated crash"))
            with self.assertRaises(SystemExit): writer.process(repo.get(1))
        self.assertEqual(repo.writes, 1)
        self.assertEqual(self.run_writer(repo, lambda _: "Strong"), {"applied_recovered": 1})
        self.assertEqual(repo.writes, 1)

    def test_tampered_journal_fails_closed(self):
        repo = MemoryRepository([row()])
        self.run_writer(repo, lambda _: "Strong")
        self.path.write_bytes(self.path.read_bytes() + b"tampered\n")
        with self.assertRaises(Exception): self.run_writer(repo, lambda _: "Strong")
        self.assertEqual(repo.writes, 1)

    def test_full_snapshot_invalidates_targeted_provenance(self):
        from modules.services.static_astrology_extractor import apply_snapshot_to_app_user, build_not_calculated_snapshot
        user = SimpleNamespace(**row())
        user.manglik_calculation_version = 2
        apply_snapshot_to_app_user(user, build_not_calculated_snapshot())
        self.assertTrue(all(getattr(user, f) is None for f in PROVENANCE_FIELDS))

    def test_pinned_engine_cancellation_flows_through_writer(self):
        from scripts.compare_manglik_v2 import ProductionCalculator
        repo = MemoryRepository([row(old={"manglik":{"severity":"Strong"},"kaal_sarp":{}},dob="1980-02-15")])
        self.run_writer(repo, ProductionCalculator())
        self.assertNotIn("manglik", repo.rows[1]["static_dosh"])
        self.assertEqual(repo.rows[1]["static_dosh"]["kaal_sarp"], {})

    def test_rollback_conflict_does_not_block_later_bounded_pages(self):
        repo = MemoryRepository([row(1),row(2)])
        self.run_writer(repo, lambda _: "Strong")
        repo.rows[1]["tob"] = "13:00"
        with RecoveryJournal(self.path,self.encryption_key) as journal:
            writer = ManglikWriter(repo,journal,lambda _: "Strong",self.hmac_key)
            writer.rollback(limit=1)
            writer.rollback(limit=1)
        self.assertNotIn("manglik",repo.rows[2]["static_dosh"])
        self.assertIn("manglik",repo.rows[1]["static_dosh"])


if __name__ == "__main__":
    unittest.main()
