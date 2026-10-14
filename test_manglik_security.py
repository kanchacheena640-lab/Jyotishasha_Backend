import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from scripts.manglik_security import verify_connection, SecurityFailure, storage_preflight
from scripts.manglik_export import main as export_main, validate_export_row, export_snapshot
from scripts.manglik_writer import main as writer_main

ROOT = Path(__file__).resolve().parent


class Cursor:
    def __init__(self, failures): self.failures=failures; self.sql=""
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,sql,params=()): self.sql=sql
    def fetchone(self):
        if "current_setting('transaction_read_only')" in self.sql:
            return ("approved_db","approved_reader","on","repeatable read",not self.failures.get("tls"),False)
        if "relkind,c.relrowsecurity" in self.sql: return ('r',False)
        if "has_function_privilege" in self.sql:return (int(self.failures.get("functions",False)),)
        if "has_table_privilege" in self.sql:return (int(self.failures.get("writes",False)),)
        return (0,)
    def fetchall(self):
        if "'UPDATE'" in self.sql:return []
        return [("public","app_users",f) for f in ("firebase_uid","dob","tob","pob","lat","lng","static_dosh")]


class Connection:
    def __init__(self,params,failures=None):self.params=params;self.failures=failures or {}
    def get_dsn_parameters(self):return self.params
    def cursor(self):return Cursor(self.failures)


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=ROOT)
        ca=Path(self.directory.name)/"synthetic-ca.crt";ca.write_bytes(b"synthetic-only")
        self.approved={"host":"approved-host","port":"5432","dbname":"approved_db","user":"approved_reader",
                       "sslrootcert":str(ca),"sslrootcert_sha256":hashlib.sha256(ca.read_bytes()).hexdigest()}
        self.params=dict(self.approved,sslmode="verify-full")
    def tearDown(self):self.directory.cleanup()
    def test_metadata_gate_success_with_synthetic_evidence(self):
        self.assertTrue(verify_connection(Connection(self.params),self.approved))
    def test_identity_tls_write_function_and_ca_mismatches_fail(self):
        for key,value in (("host","wrong"),("dbname","wrong"),("user","wrong"),("sslmode","require")):
            with self.subTest(key=key),self.assertRaises(SecurityFailure):
                verify_connection(Connection(dict(self.params,**{key:value})),self.approved)
        for failure in ("tls","writes","functions"):
            with self.subTest(failure=failure),self.assertRaises(SecurityFailure):
                verify_connection(Connection(self.params,{failure:True}),self.approved)
        changed=dict(self.approved,sslrootcert_sha256="bad")
        with self.assertRaises(SecurityFailure):verify_connection(Connection(self.params),changed)
    def test_no_connection_without_explicit_execution(self):
        with patch("scripts.manglik_export.connect_verified",side_effect=AssertionError("no connection")),redirect_stdout(io.StringIO()):
            self.assertEqual(export_main([]),0)
        with patch("scripts.manglik_writer.connect_verified",side_effect=AssertionError("no connection")),redirect_stdout(io.StringIO()):
            self.assertEqual(writer_main(["apply"]),0)
    def test_storage_rejects_repository(self):
        with self.assertRaises(SecurityFailure):storage_preflight(ROOT)
    def test_export_rejects_autocommit_and_wrong_snapshot_before_output(self):
        from unittest.mock import MagicMock
        conn = MagicMock()
        conn.autocommit = True
        with self.assertRaisesRegex(SecurityFailure, "export_autocommit_forbidden"):
            export_snapshot(conn, self.directory.name)
        conn.cursor.assert_not_called()
        conn.autocommit = False
        cursor = conn.cursor.return_value.__enter__.return_value
        for mode in (("off", "repeatable read"), ("on", "read committed")):
            cursor.fetchone.return_value = mode
            with self.assertRaisesRegex(SecurityFailure, "export_snapshot_mode_invalid"):
                export_snapshot(conn, self.directory.name)
        self.assertFalse((Path(self.directory.name) / "manglik.snapshot.part").exists())
    def test_projected_export_rejects_identifiers_and_extra_keys(self):
        row={"firebase_uid":"linked","pob":"present","dob":"1990-06-15","tob":"12:00","lat":28.6139,"lng":77.209,"static_dosh":{}}
        self.assertIsNone(validate_export_row(row))
        for changes in ({"firebase_uid":"actual-id"},{"pob":"actual birthplace"},{"name":"unexpected"}):
            with self.assertRaises(SecurityFailure):validate_export_row(dict(row,**changes))


if __name__ == "__main__":unittest.main()
