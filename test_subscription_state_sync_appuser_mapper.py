"""
test_subscription_state_sync_appuser_mapper.py
-------------------------------------------------
Regression test for the Subscription State Sync SQLAlchemy mapper-
configuration crash fix.

Root cause (confirmed by prior read-only audit, reproduced locally):
AIReport (modules/models_ai_reports.py) and CurrentEntitlement
(modules/models_premium_subscription.py) both declare a STRING-based
`db.relationship("AppUser", ...)`. SQLAlchemy only resolves that string
lazily, at mapper-configuration time (triggered by the first ORM
operation in the process) -- it requires modules.models_user (which
defines AppUser) to have actually been imported somewhere in the SAME
process by then.

The normal Flask app (app.py) gets this for free: several of its ~40
blueprint imports (e.g. routes/routes_admin_tokens.py,
routes/routes_auth.py) import modules.models_user directly. The
standalone .github/workflows/subscription_state_sync.yml entrypoint's
much narrower import chain (factory.create_app + SubscriptionStateSyncService)
never did -- so SQLAlchemy's configure_mappers() (triggered by
CurrentEntitlement.query... inside sync_all_profiles()) failed with
`InvalidRequestError: ... expression 'AppUser' failed to locate a name`.

Fix (narrow, release-safe -- explicitly NOT a central model registry in
factory.py, per this task's own instruction): the workflow's inline
Python entrypoint now does `from modules.models_user import AppUser`
(model-registration side effect only, AppUser itself unused) before
SubscriptionStateSyncService runs any ORM query.

These tests prove:
1. Mirroring the workflow's now-fixed import order, configure_mappers()
   -- the exact operation the first real query triggers -- succeeds.
2. Without the fix (AppUser import order reversed to AFTER the sync
   service, i.e. omitted from the critical early position this test
   simulates by not importing it at all in a fresh process), the same
   failure reproduces -- proving this is a genuine fix, not a coincidence.
3. The fix works with zero Razorpay credentials, and never loads
   modules.subscription.routes / config.razorpay_config (the previous,
   separately-fixed coupling stays fixed).
4. AIReport's relationship and CurrentEntitlement's own model definition
   are untouched -- neither file was modified by this fix.

LOCAL ONLY. No production DB, no real network/payment/OpenAI call. Uses a
fresh subprocess per scenario, matching test_subscription_state_sync_lazy_import.py's
own convention -- import-time/mapper-configuration behavior can only be
tested honestly in a clean process.
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


def run_in_fresh_process(code: str, strip_razorpay_env: bool = False) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if strip_razorpay_env:
        env["RAZORPAY_KEY_ID"] = ""
        env["RAZORPAY_KEY_SECRET"] = ""
    env.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-used")
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
    print("=== A: fixed import order -- configure_mappers() succeeds ===")
    # ==========================================================
    code_a = (
        "import sys; sys.path.insert(0, '.');"
        "from factory import create_app;"
        "from modules.models_user import AppUser;"
        "from modules.subscription.subscription_state_sync_service import SubscriptionStateSyncService;"
        "from sqlalchemy.orm import configure_mappers;"
        "app = create_app();"
        "app.app_context().push();"
        "configure_mappers();"
        "print('CONFIGURE_MAPPERS_OK')"
    )
    result_a = run_in_fresh_process(code_a)
    check("A-1: subprocess exits cleanly (mirrors the fixed workflow's exact import order)",
          result_a.returncode == 0)
    check("A-2: configure_mappers() completed without an InvalidRequestError",
          "CONFIGURE_MAPPERS_OK" in result_a.stdout)
    if result_a.returncode != 0:
        print("    stderr:", result_a.stderr[-800:])

    # ==========================================================
    print("\n=== B: negative control -- WITHOUT the AppUser import, the original failure reproduces ===")
    # ==========================================================
    code_b = (
        "import sys; sys.path.insert(0, '.');"
        "from factory import create_app;"
        "from modules.subscription.subscription_state_sync_service import SubscriptionStateSyncService;"
        "from sqlalchemy.orm import configure_mappers;"
        "app = create_app();"
        "app.app_context().push();"
        "configure_mappers();"
        "print('SHOULD_NOT_SUCCEED')"
    )
    result_b = run_in_fresh_process(code_b)
    check("B-1: without the AppUser import, configure_mappers() still fails "
          "(proves this fix is doing real work, not coincidental)",
          result_b.returncode != 0
          and "SHOULD_NOT_SUCCEED" not in result_b.stdout)
    check("B-2: the failure is the exact reported AppUser mapper error",
          "AppUser" in result_b.stderr and "InvalidRequestError" in result_b.stderr)

    # ==========================================================
    print("\n=== C: fix works with zero Razorpay credentials (prior coupling fix stays intact) ===")
    # ==========================================================
    code_c = (
        "import sys; sys.path.insert(0, '.');"
        "from factory import create_app;"
        "from modules.models_user import AppUser;"
        "from modules.subscription.subscription_state_sync_service import SubscriptionStateSyncService;"
        "from sqlalchemy.orm import configure_mappers;"
        "app = create_app();"
        "app.app_context().push();"
        "configure_mappers();"
        "print('routes_loaded=' + str('modules.subscription.routes' in sys.modules));"
        "print('razorpay_config_loaded=' + str('config.razorpay_config' in sys.modules));"
        "print('CONFIGURE_MAPPERS_OK')"
    )
    result_c = run_in_fresh_process(code_c, strip_razorpay_env=True)
    check("C-1: succeeds with RAZORPAY_KEY_ID/SECRET forced empty",
          result_c.returncode == 0 and "CONFIGURE_MAPPERS_OK" in result_c.stdout)
    check("C-2: modules.subscription.routes still never loaded",
          "routes_loaded=False" in result_c.stdout)
    check("C-3: config.razorpay_config still never loaded",
          "razorpay_config_loaded=False" in result_c.stdout)

    # ==========================================================
    print("\n=== D: no unrelated model file was touched ===")
    # ==========================================================
    import subprocess as _sp
    diff = _sp.run(
        ["git", "diff", "--name-only", "HEAD"], cwd=REPO_ROOT,
        capture_output=True, text=True,
    ).stdout.splitlines()
    diff = [f.strip() for f in diff if f.strip()]
    check("D-1: modules/models_ai_reports.py not modified", "modules/models_ai_reports.py" not in diff)
    check("D-2: modules/models_premium_subscription.py not modified",
          "modules/models_premium_subscription.py" not in diff)
    check("D-3: modules/models_user.py not modified", "modules/models_user.py" not in diff)
    check("D-4: factory.py not modified (release-safety decision honored)", "factory.py" not in diff)

    print(f"\n{'='*50}\nRESULT: {passed} passed, {failed} failed\n{'='*50}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
