"""Regression tests for F12-P3.5: configurable report output directory, credential-free local test DB
configuration, and the report_reviews unique-constraint name. No database or network is used."""
import os
import re
import unittest
from unittest.mock import patch

import local_test_db
import report_output

ROOT = os.path.dirname(os.path.abspath(__file__))
WRITERS = ("modules/focused_reports/paid_report_router.py", "tasks.py", "modules/love/love_premium_task.py", "report_writer.py")
DB_SUITES = ("test_report_platform_p0_3_focused_payment_bridge.py", "test_report_platform_r3_pending_order.py",
             "test_report_platform_r5_generation_dispatcher.py", "test_report_platform_r6_route_integration.py",
             "test_report_platform_suresh_webhook_first.py", "test_report_reviews.py")


def source(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
        return handle.read()


class ReportOutputDirTests(unittest.TestCase):
    def test_production_default_is_preserved_when_unset_or_blank(self):
        for env in ({}, {"REPORT_OUTPUT_DIR": ""}, {"REPORT_OUTPUT_DIR": "   "}):
            with patch.dict(os.environ, env, clear=False):
                if not env:
                    os.environ.pop("REPORT_OUTPUT_DIR", None)
                self.assertEqual(report_output.report_output_dir(), "/home/Jyotishasha/reports")

    def test_environment_overrides_the_directory(self):
        with patch.dict(os.environ, {"REPORT_OUTPUT_DIR": os.path.join("tmp", "reports-p35")}):
            path = report_output.report_output_path("focused_A_1.pdf")
        self.assertEqual(path, os.path.join("tmp", "reports-p35", "focused_A_1.pdf"))

    def test_default_path_string_is_unchanged_on_posix(self):
        import posixpath
        self.assertEqual(posixpath.join(report_output.DEFAULT_REPORT_OUTPUT_DIR, "love_A_7.pdf"),
                         "/home/Jyotishasha/reports/love_A_7.pdf")

    def test_no_report_writer_hardcodes_the_production_path(self):
        for path in WRITERS:
            text = source(path)
            self.assertNotIn("/home/Jyotishasha", text, path)
            self.assertRegex(text, r"from report_output import report_output_(path|dir)", path)


class LocalTestDbConfigTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in ("DATABASE_URL", local_test_db.ENV_VAR):
            os.environ.pop(key, None)

    def tearDown(self):
        self.env.stop()

    def test_remote_or_non_local_databases_are_refused(self):
        for url in ("postgresql://u:p@prod.example.com:5432/jyotishasha_local",
                    "postgresql://u@127.0.0.1:5432/jyotishasha_prod",
                    "postgresql://u@10.1.2.3/jyotishasha_local"):
            os.environ["DATABASE_URL"] = url
            with self.assertRaises(SystemExit):
                local_test_db.local_test_db_url()

    def test_local_dev_database_is_accepted_and_isolated_schema_takes_precedence(self):
        os.environ["DATABASE_URL"] = "postgresql://u@127.0.0.1:5432/jyotishasha_local"
        self.assertEqual(local_test_db.local_test_db_url(), "postgresql://u@127.0.0.1:5432/jyotishasha_local")
        isolated = "postgresql://u@127.0.0.1:5432/jyotishasha_local?options=-csearch_path%3Dtest_x"
        os.environ[local_test_db.ENV_VAR] = isolated
        self.assertEqual(local_test_db.local_test_db_url(), isolated)

    def test_db_writing_suites_carry_no_credentials(self):
        for path in DB_SUITES:
            text = source(path)
            self.assertNotRegex(text, r"postgresql://[^\"'\s]*:[^\"'\s@]+@", f"{path}: embedded credentials")
            self.assertIn("local_test_db_url()", text, path)


class ReviewConstraintTests(unittest.TestCase):
    def test_model_constraint_name_matches_migration_and_service(self):
        from modules.reviews.models import ReportReview
        from modules.reviews.review_service import ORDER_UNIQUE_CONSTRAINT
        uniques = {c.name: [col.name for col in c.columns] for c in ReportReview.__table__.constraints
                   if c.__class__.__name__ == "UniqueConstraint"}
        self.assertEqual(uniques, {"uq_report_reviews_order_id": ["order_id"]})
        self.assertEqual(ORDER_UNIQUE_CONSTRAINT, "uq_report_reviews_order_id")
        self.assertFalse(ReportReview.__table__.c.order_id.unique)
        migration = source("migrations/versions/b3d8f1a6c2e9_add_report_reviews.py")
        self.assertRegex(migration, re.escape("sa.UniqueConstraint('order_id', name='uq_report_reviews_order_id')"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
