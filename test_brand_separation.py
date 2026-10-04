"""
test_brand_separation.py
------------------------
Brand separation guard -- Jyotishasha and STAARAE are separate products.

Fails if the other brand's name appears (case-insensitive, byte-level, so
binary assets are covered too) in anything that produces customer-facing
Jyotishasha output: application code, routes, report/PDF/email templates,
AI prompts, content data and config. Tests, migrations, venv, caches and
local QA output directories are deliberately out of scope.

Standalone script (repo convention): python test_brand_separation.py
No database, network or app import needed.
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))

# Built from parts so this guard file can never match itself.
NEEDLE = ("staa" + "rae").encode()

SHIPPED_DIRS = [
    "modules", "services", "routes", "notifications", "prompts", "content",
    "templates", "static", "config", "data", "rules",
]
SKIP_DIRS = {"__pycache__", ".pytest_cache", "venv", ".git", "node_modules"}


def shipped_files():
    for name in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, name)
        if os.path.isfile(path) and name.endswith((".py", ".html")) and not name.startswith(("test_", "gate4_")):
            yield path
    for d in SHIPPED_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
            for f in filenames:
                yield os.path.join(dirpath, f)


def main():
    files = list(shipped_files())
    offenders = []
    for path in files:
        with open(path, "rb") as fh:
            if NEEDLE in fh.read().lower():
                offenders.append(os.path.relpath(path, ROOT))

    print(f"Scanned {len(files)} shipped backend files.")
    if offenders:
        print("  FAIL: other-brand reference found in:\n    " + "\n    ".join(offenders))
        print("RESULT: 0 passed, 1 failed")
        sys.exit(1)
    print("  PASS: no other-brand references in shipped backend files")
    print("RESULT: 1 passed, 0 failed")


if __name__ == "__main__":
    main()
