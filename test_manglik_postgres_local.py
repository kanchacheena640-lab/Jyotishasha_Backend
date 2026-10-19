"""Local-only PostgreSQL integration. All records live in a session TEMP table."""
import ipaddress
import json
import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlparse
from unittest.mock import patch
import psycopg2
from scripts.manglik_writer import PostgresRepository, PROVENANCE_FIELDS, state
from scripts.manglik_export import export_snapshot, sql_artifacts
from test_manglik_writer import row

ROOT = Path(__file__).resolve().parent


class LocalGuardPrivilegeTests(unittest.TestCase):
    """Runs the guard's exact privilege SQL against a real local PostgreSQL as a throwaway role that holds
    nothing but PostgreSQL's PUBLIC defaults. One transaction, always rolled back: the role and every grant
    disappear. Needs a local superuser DSN in MANGLIK_LOCAL_TEST_DSN (localhost/jyotishasha_local)."""

    def setUp(self):
        url = os.environ.get("MANGLIK_LOCAL_TEST_DSN")
        if not url:
            self.skipTest("Set MANGLIK_LOCAL_TEST_DSN for localhost/jyotishasha_local guard privilege tests")
        parsed = urlparse(url)
        assert parsed.hostname == "localhost" and parsed.path == "/jyotishasha_local"
        try:
            self.conn = psycopg2.connect(url, connect_timeout=3)
        except Exception:
            raise RuntimeError("Local test connection failed; connection details suppressed") from None
        self.addCleanup(self.conn.close)
        with self.conn.cursor() as cur:
            cur.execute("SELECT current_database(), inet_server_addr()::text")
            database, address = cur.fetchone()
            assert database == "jyotishasha_local" and ipaddress.ip_interface(address).ip.is_loopback
        self.conn.rollback()
        self.addCleanup(self.conn.rollback)  # never commit: role and grants vanish with the transaction

    def as_role(self, cur, sql, params=()):
        cur.execute("SET LOCAL ROLE manglik_guard_probe")
        cur.execute(sql, params)
        value = cur.fetchone()[0]
        cur.execute("RESET ROLE")
        return value

    def remaining(self, cur, params):
        """Names of the routines the guard's routine check still counts for the probe role."""
        from scripts.manglik_security import ROUTINE_CHECK_SQL
        listing = ROUTINE_CHECK_SQL.replace("SELECT count(*) FROM", "SELECT p.proname FROM", 1)
        cur.execute("SET LOCAL ROLE manglik_guard_probe")
        cur.execute(listing, params)
        names = sorted(name for (name,) in cur.fetchall())
        cur.execute("RESET ROLE")
        return names

    def refused_as_role(self, cur, sql, readonly=True):
        """Runs sql as the probe role (READ ONLY scope unless readonly=False, as the writer runs); returns the
        SQLSTATE, or None if it ran. Always rolled back to a savepoint."""
        cur.execute("SAVEPOINT probe_call")
        try:
            cur.execute("SET LOCAL ROLE manglik_guard_probe")
            if readonly:
                cur.execute("SET LOCAL transaction_read_only = on")
            cur.execute(sql)
            return None
        except psycopg2.Error as exc:
            return exc.pgcode
        finally:
            cur.execute("ROLLBACK TO SAVEPOINT probe_call")

    def test_public_defaults_accepted_only_for_readonly_and_explicit_grants_rejected(self):
        from scripts.manglik_security import (ROUTINE_CHECK_SQL, DATABASE_CHECK_SQL, SEQUENCE_CHECK_SQL,
                                              PUBLIC_DEFAULT_BUILTINS, REPLICATION_SLOT_BUILTINS,
                                              PRIVILEGE_GATED_BUILTINS)
        builtins, gated, slots = list(PUBLIC_DEFAULT_BUILTINS), list(PRIVILEGE_GATED_BUILTINS), list(REPLICATION_SLOT_BUILTINS)
        readonly, strict = (True, builtins, gated), (False, builtins, gated)
        wal = ["pg_logical_emit_message", "pg_logical_emit_message"]  # text and bytea variants
        variants = ("pg_catalog.pg_logical_emit_message(boolean, text, text, boolean)",
                    "pg_catalog.pg_logical_emit_message(boolean, text, bytea, boolean)")
        with self.conn.cursor() as cur:
            cur.execute("CREATE ROLE manglik_guard_probe NOLOGIN NOINHERIT")
            # The defect: with only PUBLIC defaults, the old (strict) routine and TEMP checks reject the role.
            strict_names = self.remaining(cur, strict)
            self.assertEqual(strict_names.count("pg_logical_emit_message"), 2)  # writer mode never excuses it
            self.assertTrue(set(slots) <= set(strict_names))
            self.assertEqual(self.as_role(cur, DATABASE_CHECK_SQL, (False,)), 1)
            # The fix: the same role passes in read-only mode, both WAL-message variants included.
            self.assertEqual(self.remaining(cur, readonly), [])
            self.assertEqual(self.as_role(cur, ROUTINE_CHECK_SQL, readonly), 0)
            self.assertEqual(self.as_role(cur, DATABASE_CHECK_SQL, (True,)), 0)
            self.assertEqual(self.as_role(cur, SEQUENCE_CHECK_SQL), 0)
            # Table writes: PostgreSQL's PUBLIC UPDATE on pg_catalog.pg_settings (== SET) is the only excuse.
            from scripts.manglik_security import TABLE_WRITE_CHECK_SQL
            self.assertEqual(self.as_role(cur, "SELECT has_table_privilege(current_user, "
                                               "'pg_catalog.pg_settings', 'UPDATE')::integer"), 1)
            self.assertEqual(self.as_role(cur, TABLE_WRITE_CHECK_SQL), 0)
            cur.execute("GRANT UPDATE ON pg_catalog.pg_settings TO manglik_guard_probe")
            self.assertEqual(self.as_role(cur, TABLE_WRITE_CHECK_SQL), 1)          # explicit grant never excused
            cur.execute("REVOKE UPDATE ON pg_catalog.pg_settings FROM manglik_guard_probe")
            cur.execute("CREATE TABLE public.manglik_guard_probe_w (id int, note text)")
            cur.execute("GRANT UPDATE (note) ON public.manglik_guard_probe_w TO manglik_guard_probe")
            self.assertEqual(self.as_role(cur, TABLE_WRITE_CHECK_SQL), 0)          # column scope: separate check
            for grant in ("UPDATE", "INSERT", "DELETE", "TRUNCATE", "INSERT (note)"):
                cur.execute(f"GRANT {grant} ON public.manglik_guard_probe_w TO manglik_guard_probe")
                self.assertEqual(self.as_role(cur, TABLE_WRITE_CHECK_SQL), 1, grant)
                cur.execute(f"REVOKE {grant} ON public.manglik_guard_probe_w FROM manglik_guard_probe")
            cur.execute("GRANT UPDATE (note) ON public.manglik_guard_probe_w TO manglik_guard_probe")
            self.assertEqual(self.as_role(cur, TABLE_WRITE_CHECK_SQL), 0)
            # UPDATE-column scope: pg_settings' PUBLIC default is excluded; any grant beyond PUBLIC is visible.
            from scripts.manglik_security import UPDATE_COLUMNS_SQL

            def update_columns():
                cur.execute("SET LOCAL ROLE manglik_guard_probe")
                cur.execute(UPDATE_COLUMNS_SQL)
                found = sorted(cur.fetchall())
                cur.execute("RESET ROLE")
                return found
            self.assertEqual(update_columns(), [("public", "manglik_guard_probe_w", "note")])
            for grant in ("UPDATE", "UPDATE (setting)"):
                cur.execute(f"GRANT {grant} ON pg_catalog.pg_settings TO manglik_guard_probe")
                self.assertIn(("pg_catalog", "pg_settings", "setting"), update_columns(), grant)
                cur.execute(f"REVOKE {grant} ON pg_catalog.pg_settings FROM manglik_guard_probe")
            self.assertEqual(update_columns(), [("public", "manglik_guard_probe_w", "note")])
            # Writer mode (read-write transaction): the approved residual is real -- session temp tables and
            # large objects -- but PUBLIC defaults still cannot touch an application table or sequence.
            cur.execute("CREATE TABLE public.manglik_guard_probe_tbl (id int)")
            cur.execute("CREATE SEQUENCE public.manglik_guard_probe_rw_seq")
            self.assertIsNone(self.refused_as_role(cur, "CREATE TEMP TABLE manglik_guard_probe_tmp (x int)", False))
            self.assertIsNone(self.refused_as_role(cur, "SELECT pg_catalog.lo_create(0)", False))
            for call in ("INSERT INTO public.manglik_guard_probe_tbl VALUES (1)",
                         "UPDATE public.manglik_guard_probe_tbl SET id = 2",
                         "DELETE FROM public.manglik_guard_probe_tbl",
                         "SELECT pg_catalog.nextval('public.manglik_guard_probe_rw_seq')",
                         "SELECT pg_catalog.setval('public.manglik_guard_probe_rw_seq', 5)"):
                self.assertEqual(self.refused_as_role(cur, call, False), "42501", call)
            # Excused replication-slot built-ins really are refused for a role without REPLICATION
            # (temporary slots, so nothing could outlive the session even if PostgreSQL allowed it).
            for call in ("SELECT pg_catalog.pg_create_physical_replication_slot('manglik_guard_probe_p', false, true)",
                         "SELECT pg_catalog.pg_create_logical_replication_slot('manglik_guard_probe_l', 'pgoutput', true)",
                         "SELECT pg_catalog.pg_drop_replication_slot('manglik_guard_probe_absent')"):
                self.assertEqual(self.refused_as_role(cur, call), "42501", call)
            # ...and stop being excused once REPLICATION is reachable, directly or through membership.
            # Every gated built-in (slots and WAL message) is counted again once REPLICATION is reachable,
            # directly or through membership.
            cur.execute("ALTER ROLE manglik_guard_probe REPLICATION")
            self.assertEqual(self.remaining(cur, readonly), sorted(wal + slots))
            cur.execute("ALTER ROLE manglik_guard_probe NOREPLICATION")
            cur.execute("CREATE ROLE manglik_guard_probe_repl NOLOGIN REPLICATION")
            cur.execute("GRANT manglik_guard_probe_repl TO manglik_guard_probe")
            self.assertEqual(self.remaining(cur, readonly), sorted(wal + slots))
            cur.execute("REVOKE manglik_guard_probe_repl FROM manglik_guard_probe")
            self.assertEqual(self.remaining(cur, readonly), [])
            # A role-level REVOKE cannot block pg_logical_emit_message while PUBLIC holds EXECUTE (why the
            # exception exists at all).
            for variant in variants:
                cur.execute(f"REVOKE EXECUTE ON FUNCTION {variant} FROM manglik_guard_probe")
                self.assertEqual(self.as_role(cur, "SELECT has_function_privilege(current_user, %s, 'EXECUTE')::integer",
                                              (variant,)), 1)
            # Explicit grants are never excused: each WAL-message variant, directly or via a plain group role.
            for variant in variants:
                cur.execute(f"GRANT EXECUTE ON FUNCTION {variant} TO manglik_guard_probe")
                self.assertEqual(self.remaining(cur, readonly), ["pg_logical_emit_message"], variant)
                cur.execute(f"REVOKE EXECUTE ON FUNCTION {variant} FROM manglik_guard_probe")
                self.assertEqual(self.remaining(cur, readonly), [])
            cur.execute("CREATE ROLE manglik_guard_probe_group NOLOGIN")
            cur.execute("GRANT manglik_guard_probe_group TO manglik_guard_probe")
            cur.execute(f"GRANT EXECUTE ON FUNCTION {variants[1]} TO manglik_guard_probe_group")
            self.assertEqual(self.remaining(cur, readonly), ["pg_logical_emit_message"])
            cur.execute(f"REVOKE EXECUTE ON FUNCTION {variants[1]} FROM manglik_guard_probe_group")
            self.assertEqual(self.remaining(cur, readonly), [])
            cur.execute("GRANT EXECUTE ON FUNCTION pg_catalog.nextval(regclass) TO manglik_guard_probe")
            self.assertEqual(self.remaining(cur, readonly), ["nextval"])
            cur.execute("REVOKE EXECUTE ON FUNCTION pg_catalog.nextval(regclass) FROM manglik_guard_probe")
            self.assertEqual(self.remaining(cur, readonly), [])
            cur.execute("SELECT format('GRANT TEMP ON DATABASE %I TO manglik_guard_probe', current_database())")
            cur.execute(cur.fetchone()[0])
            self.assertEqual(self.as_role(cur, DATABASE_CHECK_SQL, (True,)), 1)
            cur.execute("CREATE TEMP SEQUENCE manglik_guard_probe_seq")
            cur.execute("GRANT USAGE ON SEQUENCE manglik_guard_probe_seq TO manglik_guard_probe")
            self.assertGreater(self.as_role(cur, SEQUENCE_CHECK_SQL), 0)
            # Server-side file access is never on the list, even if PUBLIC held it.
            self.assertNotIn("lo_import", builtins)


class LocalPostgresTests(unittest.TestCase):
    def setUp(self):
        url = os.environ.get("MANGLIK_LOCAL_TEST_DSN")
        if not url:
            self.skipTest("Set MANGLIK_LOCAL_TEST_DSN for localhost/jyotishasha_local TEMP-table tests")
        parsed = urlparse(url)
        assert parsed.hostname == "localhost" and parsed.path == "/jyotishasha_local"
        try:
            self.conn = psycopg2.connect(url, connect_timeout=3)
        except Exception:
            raise RuntimeError("Local test connection failed; connection details suppressed") from None
        self.addCleanup(self.conn.close)
        self.conn.set_session(readonly=True)
        with self.conn.cursor() as cur:
            cur.execute("SELECT current_database(), inet_server_addr()::text")
            database, address = cur.fetchone()
            assert database == "jyotishasha_local" and ipaddress.ip_interface(address).ip.is_loopback
        self.conn.rollback()
        self.conn.set_session(readonly=False)
        with self.conn.cursor() as cur:
            cur.execute("""CREATE TEMP TABLE manglik_writer_test (
                id integer PRIMARY KEY, firebase_uid text, dob text, tob text, pob text,
                lat double precision, lng double precision, static_dosh jsonb,
                manglik_calculation_version smallint, manglik_calculated_at timestamptz,
                manglik_input_digest varchar(64), manglik_correction_run_id uuid,
                static_yog jsonb DEFAULT '{"keep":{}}', static_astrology_version integer DEFAULT 1,
                lagna text DEFAULT 'keep') ON COMMIT PRESERVE ROWS""")
        self.conn.commit()
        self.repo = PostgresRepository(self.conn, "pg_temp.manglik_writer_test")

    def tearDown(self):
        self.conn.close()  # PostgreSQL automatically drops the TEMP table.

    def insert(self, source):
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO pg_temp.manglik_writer_test
                (id,firebase_uid,dob,tob,pob,lat,lng,static_dosh)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                tuple(source[f] for f in ("id","firebase_uid","dob","tob","pob","lat","lng")) +
                (json.dumps(source["static_dosh"]) if source["static_dosh"] is not None else None,))
        self.conn.commit()

    def desired(self, severity):
        return {"present": severity is not None, "member": {"severity":severity} if severity else None,
                "provenance": dict(zip(PROVENANCE_FIELDS, (2,"2026-10-12T00:00:00+00:00","a"*64,"00000000-0000-0000-0000-000000000002")))}

    def test_actual_jsonb_patch_and_rollback(self):
        self.insert(row())
        before = self.repo.get(1)
        desired = self.desired("Strong")
        self.assertTrue(self.repo.patch(before, state(before), desired))
        after = self.repo.get(1)
        self.assertEqual(state(after), desired)
        self.assertEqual(after["static_dosh"]["kaal_sarp"], {"preserve":True})
        with self.conn.cursor() as cur:
            cur.execute("SELECT static_yog,static_astrology_version,lagna FROM pg_temp.manglik_writer_test")
            self.assertEqual(cur.fetchone(), ({"keep":{}},1,"keep"))
        self.conn.rollback()
        self.assertTrue(self.repo.patch(after, desired, state(before)))
        self.assertEqual(self.repo.get(1)["static_dosh"], before["static_dosh"])

    def test_actual_cas_rejects_changed_birth(self):
        self.insert(row())
        before = self.repo.get(1)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE pg_temp.manglik_writer_test SET tob='13:00' WHERE id=1")
        self.conn.commit()
        self.assertFalse(self.repo.patch(before, state(before), self.desired("Strong")))
        self.assertNotIn("manglik", self.repo.get(1)["static_dosh"])

    def test_actual_patch_merges_later_other_json(self):
        self.insert(row())
        before = self.repo.get(1)
        with self.conn.cursor() as cur:
            cur.execute("UPDATE pg_temp.manglik_writer_test SET static_dosh=static_dosh || '{\"kaal_sarp\":{\"later\":true}}'::jsonb")
        self.conn.commit()
        self.assertTrue(self.repo.patch(before, state(before), self.desired("Partial")))
        self.assertEqual(self.repo.get(1)["static_dosh"]["kaal_sarp"], {"later":True})

    def test_actual_json_null_member_removal(self):
        self.insert(row(old={"manglik":None,"kaal_sarp":{}}))
        before = self.repo.get(1)
        self.assertTrue(self.repo.patch(before, state(before), self.desired(None)))
        self.assertEqual(self.repo.get(1)["static_dosh"], {"kaal_sarp":{}})

    def test_sql_export_and_counts_use_synthetic_temp_table_only(self):
        for source in (row(1),row(2,tob=None),row(3,dob="2023-02-29"),row(4,lat=float("nan")),
                       row(5,static_dosh=None),row(6,static_dosh=[]),row(7,old={"manglik":{"severity":"Strong"},"kaal_sarp":{}})):
            self.insert(source)
        select, counts = sql_artifacts()
        synthetic_queries = (select.replace("public.app_users","pg_temp.manglik_writer_test"),
                             counts.replace("public.app_users","pg_temp.manglik_writer_test"))
        self.conn.set_session(readonly=True,isolation_level="REPEATABLE READ")
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            with patch("scripts.manglik_export.sql_artifacts",return_value=synthetic_queries):
                result = export_snapshot(self.conn,directory)
            self.assertEqual(result["counts"]["eligible"],4)
            self.assertEqual(result["counts"]["old_json_missing"],1)
            self.assertEqual(result["counts"]["old_json_malformed"],1)
            lines = (Path(directory)/"manglik.snapshot.part").read_text().splitlines()
            self.assertEqual(len(lines),4)
            for line in lines:
                exported = json.loads(line)
                self.assertEqual(exported["firebase_uid"],"linked")
                self.assertEqual(exported["pob"],"present")
                self.assertNotIn("kaal_sarp",line)


if __name__ == "__main__":
    unittest.main()
