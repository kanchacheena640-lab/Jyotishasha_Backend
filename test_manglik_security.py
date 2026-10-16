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


class RecordingCursor(Cursor):
    """Records every guard query with its parameters; optional per-check results."""
    def __init__(self, failures, log): super().__init__(failures); self.log = log; self.params = ()
    def execute(self, sql, params=()): self.sql = sql; self.params = params; self.log.append((sql, params))
    def fetchone(self):
        if "has_sequence_privilege" in self.sql: return (int(self.failures.get("sequences", False)),)
        if "has_database_privilege" in self.sql: return (int(self.failures.get("temp", False)),)
        if self.failures.get("writer") and "current_setting('transaction_read_only')" in self.sql:
            return ("approved_db", "approved_reader", "off", "read committed", True, False)
        return super().fetchone()


class RecordingConnection(Connection):
    def __init__(self, params, failures=None): super().__init__(params, failures); self.log = []
    def cursor(self): return RecordingCursor(self.failures, self.log)


class PublicDefaultBuiltinTests(unittest.TestCase):
    """Guard correction: PostgreSQL's PUBLIC-default EXECUTE on side-effecting built-ins (and default TEMP)
    no longer rejects a read-only role; explicit grants, writer mode and sequence access still fail closed."""
    setUp = SecurityTests.setUp
    tearDown = SecurityTests.tearDown

    def routine_call(self, conn):
        return next((sql, p) for sql, p in conn.log if "has_function_privilege" in sql)

    def test_readonly_passes_the_public_default_exception(self):
        from scripts.manglik_security import PUBLIC_DEFAULT_BUILTINS, PRIVILEGE_GATED_BUILTINS
        conn = RecordingConnection(self.params)
        self.assertTrue(verify_connection(conn, self.approved, readonly=True))
        sql, params = self.routine_call(conn)
        self.assertEqual(params, (True, list(PUBLIC_DEFAULT_BUILTINS), list(PRIVILEGE_GATED_BUILTINS)))
        self.assertIn("r.rolreplication OR r.rolsuper", sql)    # gated built-ins excused only without REPLICATION
        self.assertIn("a.grantee <> 0", sql)                    # only PUBLIC (grantee 0) is excused
        self.assertIn("NOT p.prosecdef", sql)                   # security-definer routines never excused
        self.assertIn("n.nspname = 'pg_catalog'", sql)          # only catalog built-ins
        db_sql, db_params = next((s, p) for s, p in conn.log if "has_database_privilege" in s)
        self.assertEqual(db_params, (True,))
        self.assertIn("'CREATE'", db_sql)                       # CREATE is never excused

    def test_exception_list_is_narrow(self):
        from scripts.manglik_security import PUBLIC_DEFAULT_BUILTINS, PRIVILEGE_GATED_BUILTINS
        excused = PUBLIC_DEFAULT_BUILTINS + PRIVILEGE_GATED_BUILTINS
        for forbidden in ("lo_import", "lo_export", "pg_read_file", "pg_write_file",
                          "pg_reload_conf", "pg_promote", "pg_switch_wal", "pg_create_restore_point", "dblink_exec",
                          "pg_replication_slot_advance", "pg_copy_physical_replication_slot"):
            self.assertNotIn(forbidden, excused)
        self.assertEqual(len(excused), len(set(excused)))
        # The WAL-message exception is owner-approved and gated; it is never an ungated PUBLIC default.
        self.assertNotIn("pg_logical_emit_message", PUBLIC_DEFAULT_BUILTINS)
        self.assertEqual(set(PRIVILEGE_GATED_BUILTINS), {"pg_create_physical_replication_slot",
                                                         "pg_create_logical_replication_slot",
                                                         "pg_drop_replication_slot", "pg_logical_emit_message"})

    def test_writer_mode_gets_no_exception(self):
        conn = RecordingConnection(self.params, {"writer": True})
        with self.assertRaises(SecurityFailure):  # the mock grants no writer UPDATE scope; only the call matters
            verify_connection(conn, self.approved, readonly=False)
        self.assertEqual(self.routine_call(conn)[1][0], False)
        self.assertEqual(next(p for s, p in conn.log if "has_database_privilege" in s), (False,))

    def test_sequence_privilege_and_non_public_temp_still_fail_closed(self):
        with self.assertRaisesRegex(SecurityFailure, "sequence_privilege"):
            verify_connection(RecordingConnection(self.params, {"sequences": True}), self.approved)
        with self.assertRaisesRegex(SecurityFailure, "database_create_or_temp_privilege"):
            verify_connection(RecordingConnection(self.params, {"temp": True}), self.approved)
        with self.assertRaisesRegex(SecurityFailure, "executable_unreviewed_or_side_effecting_routines"):
            verify_connection(RecordingConnection(self.params, {"functions": True}), self.approved)


if __name__ == "__main__":unittest.main()
