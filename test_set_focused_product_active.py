"""Tests for scripts/set_focused_product_active.py (F12-P3.4).

Validation tests need no database. The DB tests run ONLY inside an isolated local test schema
(JYOTISHASHA_TEST_DATABASE_URL, see local_test_db.py / scripts/local_test_schema.py) and are skipped
otherwise, so the shared development data is never written.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import set_focused_product_active as tool  # noqa: E402
from local_test_db import ENV_VAR, isolated_schema, resolve_test_db_url  # noqa: E402

TEST_URL = os.environ.get(ENV_VAR)
KEYS = "promotion_timing,natural_strengths"


class ValidationTests(unittest.TestCase):
    def test_catalog_has_exactly_63_focused_keys(self):
        self.assertEqual(len(tool.focused_keys()), 63)

    def test_rejects_empty_duplicate_and_unknown_keys(self):
        catalog = tool.focused_keys()
        for raw in ("", " , ", "promotion_timing,promotion_timing", "not_a_key"):
            with self.assertRaises(tool.ToolError) as ctx:
                tool.parse_keys(raw, catalog)
            self.assertEqual(ctx.exception.code, 2, raw)

    def test_standard_report_slugs_are_refused_before_any_db_access(self):
        with patch.object(tool, "resolve_db_url") as resolve:
            for slug in ("career_report", "marriage_report", "relationship_future_report", "spouse_nature_report"):
                with self.assertRaises(tool.ToolError) as ctx:
                    tool.run(slug, True, apply=True)
                self.assertEqual(ctx.exception.code, 2)
        resolve.assert_not_called()

    def test_remote_hosts_are_refused(self):
        for url in ("postgresql://u:p@db.example.com:5432/x", "postgresql://u@10.0.0.5/x"):
            with self.assertRaises(tool.ToolError) as ctx:
                tool.resolve_db_url(url)
            self.assertEqual(ctx.exception.code, 4)
        self.assertTrue(tool.resolve_db_url("postgresql://u@127.0.0.1:5432/x").startswith("postgresql://"))

    def test_isolation_helper_requires_a_single_test_schema_on_a_local_host(self):
        good = "postgresql://u@127.0.0.1:5432/jyotishasha_local?options=-csearch_path%3Dtest_x"
        self.assertEqual(isolated_schema(good), "test_x")
        for bad in ("postgresql://u@127.0.0.1/jyotishasha_local?options=-csearch_path%3Dpublic",
                    "postgresql://u@127.0.0.1/jyotishasha_local?options=-csearch_path%3Dtest_x,public",
                    "postgresql://u@example.com/jyotishasha_local?options=-csearch_path%3Dtest_x",
                    "postgresql://u@127.0.0.1/jyotishasha_local"):
            with patch.dict(os.environ, {ENV_VAR: bad}), self.assertRaises(SystemExit):
                resolve_test_db_url("default")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV_VAR, None)
            self.assertEqual(resolve_test_db_url("default"), "default")

    def test_no_force_flag_exists(self):
        with open(tool.__file__, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("--force", source)
        self.assertNotIn("--allow-inflight", source)


@unittest.skipUnless(TEST_URL, f"set {ENV_VAR} to an isolated test schema to run DB tests")
class IsolatedDatabaseTests(unittest.TestCase):
    """Runs against the isolated schema only; restores every row it touches."""

    @classmethod
    def setUpClass(cls):
        import psycopg2
        cls.conn = psycopg2.connect(resolve_test_db_url(""))
        cls.conn.autocommit = True
        cur = cls.conn.cursor()
        cur.execute("SELECT current_schema()")
        assert cur.fetchone()[0] == isolated_schema(TEST_URL), "not connected to the isolated schema"

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def setUp(self):
        self.cur = self.conn.cursor()
        self.cur.execute("SELECT report_slug, active FROM report_products")
        self.snapshot = dict(self.cur.fetchall())
        self.cur.execute("DELETE FROM orders WHERE email LIKE 'p34-tool-%@example.invalid'")
        # Each test starts from the seeded state for its two keys (inactive), whatever the schema was copied from.
        self.cur.execute("UPDATE report_products SET active = false WHERE report_slug IN ('promotion_timing', 'natural_strengths')")

    def tearDown(self):
        self.cur.execute("DELETE FROM orders WHERE email LIKE 'p34-tool-%@example.invalid'")
        for slug, active in self.snapshot.items():
            self.cur.execute("UPDATE report_products SET active = %s WHERE report_slug = %s AND active IS DISTINCT FROM %s",
                             (active, slug, active))

    def state(self):
        self.cur.execute("SELECT report_slug, active FROM report_products")
        return dict(self.cur.fetchall())

    def quiet(self, *args, **kwargs):
        with redirect_stdout(io.StringIO()) as buffer:
            result = tool.run(*args, db_url=TEST_URL, out=print, **kwargs)
        return result, buffer.getvalue()

    def test_dry_run_reports_changes_but_writes_nothing(self):
        before = self.state()
        result, text = self.quiet(KEYS, True)
        self.assertEqual(result["changes"], ["natural_strengths", "promotion_timing"])
        self.assertEqual(result["updated"], [])
        self.assertIn("DRY RUN", text)
        self.assertEqual(self.state(), before)

    def test_apply_changes_only_the_two_keys_and_is_idempotent(self):
        before = self.state()
        result, _ = self.quiet(KEYS, True, apply=True)
        self.assertEqual(result["updated"], ["natural_strengths", "promotion_timing"])
        after = self.state()
        changed = sorted(k for k in after if after[k] != before[k])
        self.assertEqual(changed, ["natural_strengths", "promotion_timing"])
        again, _ = self.quiet(KEYS, True, apply=True)
        self.assertEqual(again["updated"], [])
        self.assertEqual(self.state(), after)

    def test_rollback_restores_the_original_state(self):
        before = self.state()
        self.quiet(KEYS, True, apply=True)
        self.quiet(KEYS, False, apply=True)
        self.assertEqual(self.state(), before)

    def test_deactivation_refused_while_a_paid_order_is_unfinished(self):
        self.quiet("promotion_timing", True, apply=True)
        self.cur.execute("INSERT INTO orders (name, email, product, status, payment_status, report_stage, email_status) "
                         "VALUES ('P34 Tool', 'p34-tool-1@example.invalid', 'promotion_timing', 'PAID', 'PAID', 'Queued', 'NOT_ATTEMPTED')")
        with self.assertRaises(tool.ToolError) as ctx:
            self.quiet("promotion_timing", False, apply=True)
        self.assertEqual(ctx.exception.code, 3)
        self.assertTrue(self.state()["promotion_timing"], "must stay active after a refused deactivation")
        # A delivered order (Ready + SENT) no longer blocks.
        self.cur.execute("UPDATE orders SET report_stage = 'Ready', email_status = 'SENT' WHERE email = 'p34-tool-1@example.invalid'")
        result, _ = self.quiet("promotion_timing", False, apply=True)
        self.assertEqual(result["updated"], ["promotion_timing"])

    def test_standard_products_are_never_touched(self):
        standard_before = {k: v for k, v in self.state().items() if k not in tool.focused_keys()}
        self.quiet(KEYS, True, apply=True)
        self.quiet(KEYS, False, apply=True)
        self.assertEqual({k: v for k, v in self.state().items() if k not in tool.focused_keys()}, standard_before)
        self.assertEqual(sum(standard_before.values()), 26)


if __name__ == "__main__":
    unittest.main(verbosity=2)
