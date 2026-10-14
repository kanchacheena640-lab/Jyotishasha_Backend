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
