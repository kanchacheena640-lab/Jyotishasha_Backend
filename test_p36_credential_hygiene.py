"""Regression tests for F12-P3.6: no database credentials in tracked files, local-only DB targets for tests
and the local migration helpers, and explicit target confirmation before those helpers write anything.
No database or network is used (the helper subprocesses refuse before connecting)."""
import glob
import os
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

import local_test_db

ROOT = os.path.dirname(os.path.abspath(__file__))
MIGRATION_HELPERS = sorted(os.path.relpath(p, ROOT).replace(os.sep, "/")
                           for p in glob.glob(os.path.join(ROOT, "scripts", "n[3-6]_apply_*_migration.py")))
CRED_URL = re.compile(r"postgres(?:ql)?(?:\+psycopg2)?://([^\"'\s/:@]+):([^\"'\s@]+)@")
# Obviously fake passwords used by guard tests and the .env.example placeholder. Anything else is a leak.
FAKE_PASSWORDS = {"p", "pw", "x", "unused", "YOUR_LOCAL_DB_PASSWORD"}
FAKE_WORDS = re.compile(r"bad|fake|dummy|placeholder", re.I)
FAKE_SECRET = "s3cret-should-never-print"


def is_fake(password: str) -> bool:
    return password in FAKE_PASSWORDS or len(password) <= 2 or bool(FAKE_WORDS.search(password))


class TrackedFileSecretScanTests(unittest.TestCase):
    def test_no_tracked_file_embeds_a_real_database_password(self):
        try:
            files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available")
        leaks = []
        for path in filter(None, files):
            try:
                with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
                    text = handle.read()
            except (UnicodeDecodeError, OSError):
                continue
            leaks += [f"{path} (user {m.group(1)!r})" for m in CRED_URL.finditer(text) if not is_fake(m.group(2))]
        self.assertEqual(leaks, [], "credential-bearing database URLs (values not shown)")

    def test_env_example_uses_placeholders_only(self):
        with open(os.path.join(ROOT, ".env.example"), encoding="utf-8") as handle:
            line = next(l for l in handle if l.startswith("DATABASE_URL="))
        self.assertIn("YOUR_LOCAL_DB_USER:YOUR_LOCAL_DB_PASSWORD@localhost:5432/jyotishasha_local", line)


class LocalOnlyTargetTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in ("DATABASE_URL", local_test_db.ENV_VAR):
            os.environ.pop(key, None)

    def tearDown(self):
        self.env.stop()

    def test_dev_url_refuses_remote_or_other_databases(self):
        for url in ("postgresql://u:p@prod.example.com:5432/jyotishasha_local",
                    "postgresql://u@127.0.0.1:5432/jyotishasha", "postgresql://u@10.0.0.5/jyotishasha_local"):
            os.environ["DATABASE_URL"] = url
            with self.assertRaises(SystemExit):
                local_test_db.local_dev_db_url()

    def test_dev_url_ignores_the_isolated_test_schema(self):
        os.environ["DATABASE_URL"] = "postgresql://u@localhost:5432/jyotishasha_local"
        os.environ[local_test_db.ENV_VAR] = "postgresql://u@127.0.0.1:5432/jyotishasha_local?options=-csearch_path%3Dtest_x"
        self.assertEqual(local_test_db.local_dev_db_url(), "postgresql://u@localhost:5432/jyotishasha_local")
        self.assertTrue(local_test_db.local_test_db_url().endswith("test_x"))

    def test_target_description_never_contains_credentials(self):
        url = f"postgresql://someone:{FAKE_SECRET}@localhost:5432/jyotishasha_local"
        self.assertEqual(local_test_db.describe_target(url), "localhost:5432/jyotishasha_local")

    def test_confirmation_requires_the_exact_database_name(self):
        url = f"postgresql://someone:{FAKE_SECRET}@localhost:5432/jyotishasha_local"
        for argv in ([], ["--confirm-target"], ["--confirm-target", "jyotishasha"], ["jyotishasha_local"]):
            with self.assertRaises(SystemExit) as ctx:
                local_test_db.require_target_confirmation(url, argv, "scripts/x.py")
            self.assertNotIn(FAKE_SECRET, str(ctx.exception.code))
            self.assertIn("Nothing was changed", str(ctx.exception.code))
        local_test_db.require_target_confirmation(url, ["--confirm-target", "jyotishasha_local"], "scripts/x.py")


class MigrationHelperTests(unittest.TestCase):
    def test_all_four_helpers_are_covered(self):
        self.assertEqual(len(MIGRATION_HELPERS), 4, MIGRATION_HELPERS)

    def test_helpers_take_the_url_from_the_environment_and_confirm_before_any_write(self):
        for path in MIGRATION_HELPERS:
            with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
                text = handle.read()
            self.assertIsNone(CRED_URL.search(text), path)
            self.assertIn("LOCAL_DB_URL = local_dev_db_url()", text, path)
            main = text[text.index("def main():"):]
            self.assertLess(main.index("require_target_confirmation("), main.index("prepare()"), path)

    def test_running_a_helper_without_confirmation_changes_nothing_and_prints_no_secret(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", local_test_db.ENV_VAR)}
        env["DATABASE_URL"] = f"postgresql://someone:{FAKE_SECRET}@localhost:5432/jyotishasha_local"
        for path in MIGRATION_HELPERS:
            result = subprocess.run([sys.executable, "-B", path], cwd=ROOT, env=env, capture_output=True,
                                    text=True, timeout=60)
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, path)
            self.assertIn("Nothing was changed", output, path)
            self.assertIn("--confirm-target jyotishasha_local", output, path)
            self.assertNotIn(FAKE_SECRET, output, path)
            self.assertNotIn("Revision before upgrade", output, path)

    def test_helpers_refuse_a_remote_database_even_with_confirmation(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", local_test_db.ENV_VAR)}
        env["DATABASE_URL"] = f"postgresql://someone:{FAKE_SECRET}@prod.example.com:5432/jyotishasha_local"
        for path in MIGRATION_HELPERS:
            result = subprocess.run([sys.executable, "-B", path, "--confirm-target", "jyotishasha_local"], cwd=ROOT,
                                    env=env, capture_output=True, text=True, timeout=60)
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, path)
            self.assertIn("REFUSING TO RUN", output, path)
            self.assertNotIn(FAKE_SECRET, output, path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
