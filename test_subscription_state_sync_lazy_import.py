"""
test_subscription_state_sync_lazy_import.py
---------------------------------------------
Regression test for the Subscription State Sync GitHub Actions import-time
crash fix.

Root cause (confirmed by prior read-only audit): modules/subscription/
__init__.py used to do `from .routes import subscription_bp` at MODULE
level -- so importing ANY submodule of modules.subscription (e.g.
subscription_state_sync_service, which never uses Razorpay at all) forced
Python to run this package's __init__.py first, which pulled in routes.py,
which pulled in config/razorpay_config.py, which raises at IMPORT time
without RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET -- crashing the
.github/workflows/subscription_state_sync.yml cron even though
SubscriptionStateSyncService's own code never touches Razorpay.

Fix: the `from .routes import subscription_bp` import was moved inside
register_subscription(app) itself (its only use site) -- a lazy import.
routes.py/razorpay_config.py are now only ever loaded when
register_subscription(app) is actually called (app.py's own boot
sequence), never merely by importing modules.subscription or one of its
submodules.

These tests prove:
1. modules.subscription.subscription_state_sync_service imports cleanly
   with NO Razorpay env vars set.
2. Neither modules.subscription.routes nor config.razorpay_config are
   loaded as a side effect of that import (the real proof -- not just
   "no exception", since .env might coincidentally have the keys anyway).
3. SubscriptionStateSyncService itself remains importable and usable.
4. modules.subscription.__init__.py's external API
   (register_subscription(app)) is unchanged in shape/behavior --
   register_subscription is still importable from the package, and still
   registers the same blueprint the same way when actually called with
   Razorpay env vars present (proven via routes.py, no change made
   there).

LOCAL ONLY. No production DB, no real network/payment call, no OpenAI
call. Uses subprocess with a fresh Python interpreter per scenario so each
test gets a clean sys.modules/os.environ -- import-time behavior can only
be tested honestly in a fresh process, not by importing twice in one.
"""

import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}")
        failed += 1


LOCAL_DB_URL = "postgresql://jyotishasha_dev:dcaslQQbyPSBsvTg2UEa@localhost:5432/jyotishasha_local"


def run_in_fresh_process(code: str, strip_razorpay_env: bool) -> subprocess.CompletedProcess:
    """Runs `code` in a brand-new Python process (own sys.modules), with
    the Razorpay env vars removed if requested -- and, critically, an
    empty-string RAZORPAY_KEY_ID/SECRET override so a real .env file's
    keys (if present locally) can never accidentally mask the test."""
    env = dict(os.environ)
    if strip_razorpay_env:
        env["RAZORPAY_KEY_ID"] = ""
        env["RAZORPAY_KEY_SECRET"] = ""
    env.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
    # LOCAL/PRODUCTION SAFETY BOUNDARY -- this subprocess (scenario D
    # below does `from app import app`, a full boot) previously inherited
    # DATABASE_URL from the ambient environment/.env's own production
    # URL if nothing was exported. Made explicit and local-only.
    env["DATABASE_URL"] = LOCAL_DB_URL
    env["ACTIVITY_EVENTS_ENVIRONMENT"] = "local"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def main():
    # ==========================================================
    print("=== A: subscription_state_sync_service imports without Razorpay env vars ===")
    # ==========================================================
    code_a = (
        "import sys; sys.path.insert(0, '.');"
        "from modules.subscription.subscription_state_sync_service import SubscriptionStateSyncService;"
        "print('IMPORT_OK')"
    )
    result_a = run_in_fresh_process(code_a, strip_razorpay_env=True)
    check("A-1: import succeeds (exit code 0) with empty Razorpay env vars",
          result_a.returncode == 0)
    check("A-2: no Razorpay/OpenAIError-style exception in output",
          "Missing Razorpay API keys" not in result_a.stderr
          and "Missing Razorpay API keys" not in result_a.stdout)
    check("A-3: stdout confirms the import actually completed",
          "IMPORT_OK" in result_a.stdout)
    if result_a.returncode != 0:
        print("    stderr:", result_a.stderr[-500:])

    # ==========================================================
    print("\n=== B: routes.py / razorpay_config.py are NOT loaded as a side effect ===")
    # ==========================================================
    code_b = (
        "import sys; sys.path.insert(0, '.');"
        "from modules.subscription.subscription_state_sync_service import SubscriptionStateSyncService;"
        "print('routes_loaded=' + str('modules.subscription.routes' in sys.modules));"
        "print('razorpay_config_loaded=' + str('config.razorpay_config' in sys.modules))"
    )
    result_b = run_in_fresh_process(code_b, strip_razorpay_env=True)
    check("B-1: subprocess exits cleanly", result_b.returncode == 0)
    check("B-2: modules.subscription.routes was never imported",
          "routes_loaded=False" in result_b.stdout)
    check("B-3: config.razorpay_config was never imported",
          "razorpay_config_loaded=False" in result_b.stdout)

    # ==========================================================
    print("\n=== C: SubscriptionStateSyncService remains usable (has its expected method) ===")
    # ==========================================================
    code_c = (
        "import sys; sys.path.insert(0, '.');"
        "from modules.subscription.subscription_state_sync_service import SubscriptionStateSyncService;"
        "print('has_sync_all_profiles=' + str(hasattr(SubscriptionStateSyncService, 'sync_all_profiles')))"
    )
    result_c = run_in_fresh_process(code_c, strip_razorpay_env=True)
    check("C-1: subprocess exits cleanly", result_c.returncode == 0)
    check("C-2: SubscriptionStateSyncService.sync_all_profiles still exists",
          "has_sync_all_profiles=True" in result_c.stdout)

    # ==========================================================
    print("\n=== D: register_subscription(app) external API/behavior unchanged (WITH Razorpay env vars) ===")
    # ==========================================================
    # Uses the real local .env (not stripped) -- proves normal app boot
    # (which DOES call register_subscription(app)) still registers the
    # blueprint exactly as before, unaffected by the lazy-import move.
    code_d = (
        "import sys; sys.path.insert(0, '.');"
        "from modules.subscription import register_subscription;"
        "print('register_subscription_importable=True');"
        "from app import app;"
        "rules = [r.rule for r in app.url_map.iter_rules() if 'subscription' in r.rule.lower()];"
        "print('subscription_route_count=' + str(len(rules)));"
        "print('has_google_confirm=' + str(any('google/confirm' in r for r in rules)))"
    )
    result_d = run_in_fresh_process(code_d, strip_razorpay_env=False)
    check("D-1: register_subscription is still importable from the package",
          "register_subscription_importable=True" in result_d.stdout)
    check("D-2: app still boots and registers subscription routes when Razorpay env vars ARE present",
          result_d.returncode == 0 and "subscription_route_count=0" not in result_d.stdout)
    check("D-3: the known google/confirm route is still registered (behavior unchanged)",
          "has_google_confirm=True" in result_d.stdout)
    if result_d.returncode != 0:
        print("    stderr:", result_d.stderr[-500:])

    # ==========================================================
    print("\n=== E: config/razorpay_config.py's OWN separate fix (P4.3, Campaign C worker "
          "boot incident) -- razorpay_client is now a lazy proxy, so importing routes.py "
          "directly no longer itself requires Razorpay keys; REAL use still fails exactly "
          "as before (proves E is not a silent fake-credential fallback on a real payment "
          "path) ===")
    # ==========================================================
    code_e1 = (
        "import sys; sys.path.insert(0, '.');"
        "from modules.subscription.routes import subscription_bp;"
        "print('IMPORT_OK')"
    )
    result_e1 = run_in_fresh_process(code_e1, strip_razorpay_env=True)
    check("E-1: directly importing modules.subscription.routes WITHOUT Razorpay keys now "
          "succeeds (config/razorpay_config.py's own P4.3 lazy-proxy fix, orthogonal to "
          "this file's own lazy-IMPORT fix above)",
          result_e1.returncode == 0 and "IMPORT_OK" in result_e1.stdout)

    code_e2 = (
        "import sys; sys.path.insert(0, '.');"
        "from config.razorpay_config import razorpay_client;"
        "razorpay_client.order;"  # first REAL use -- must still fail clearly
        "print('SHOULD_NOT_REACH_HERE')"
    )
    result_e2 = run_in_fresh_process(code_e2, strip_razorpay_env=True)
    check("E-2: first REAL use of razorpay_client (not merely importing it) WITHOUT "
          "Razorpay keys still fails with the exact original message -- proves the P4.3 "
          "fix only deferred WHEN the check runs, never weakened it",
          result_e2.returncode != 0
          and ("Missing Razorpay API keys" in result_e2.stderr
               or "Missing Razorpay API keys" in result_e2.stdout))

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
