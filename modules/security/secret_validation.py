"""Warn-only validation of JWT_SECRET_KEY and SECRET_KEY (PR #8).

app_config.py falls back to well-known placeholder strings when these
variables are unset. A JWT secret equal to its public fallback lets anyone
mint valid tokens, including admin ones, so the web service should say so
loudly. This module only ever WARNS:

- it never blocks startup or a request and never raises;
- it never reads, changes or rotates a secret beyond checking it;
- it never logs a value, a prefix or a length -- only the variable name and
  which rule failed;
- it runs once per worker process, on that process's first HTTP request, so
  CLI scripts, Celery, cron jobs and migration workflows that import `app`
  without serving HTTP never trigger it.

Enforcement (refusing to start) is deliberately left for a later PR.
"""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger("secret_validation")

# Values app_config.py falls back to, plus obvious placeholders.
_KNOWN_UNSAFE = frozenset({
    "change-this-in-prod",
    "fallback-secret",
    "changeme",
    "secret",
    "dev",
    "test",
})
_MIN_LENGTH = 32
CHECKED_VARIABLES = ("JWT_SECRET_KEY", "SECRET_KEY")

_checked = False
_lock = threading.Lock()


def find_problems(environ=None) -> list[tuple[str, str]]:
    """Return (variable, reason) pairs. Reasons never include the value."""
    environ = os.environ if environ is None else environ
    problems = []
    for name in CHECKED_VARIABLES:
        value = environ.get(name)
        if value is None or not value.strip():
            problems.append((name, "not set; app_config.py falls back to a public placeholder"))
        elif value.strip().lower() in _KNOWN_UNSAFE:
            problems.append((name, "set to a known placeholder value"))
        elif len(value) < _MIN_LENGTH:
            problems.append((name, f"shorter than the recommended {_MIN_LENGTH} characters"))
    return problems


def run_check_once() -> None:
    global _checked
    with _lock:
        if _checked:
            return
        _checked = True
    try:
        problems = find_problems()
        for name, reason in problems:
            logger.critical("SECURITY secret_validation: %s is %s. Set a strong random value "
                            "in the service environment.", name, reason)
        if not problems:
            logger.info("secret_validation: JWT_SECRET_KEY and SECRET_KEY look configured.")
    except Exception:
        pass  # warn-only: never let the check affect the service


def register_secret_validation(app) -> None:
    @app.before_request
    def _secret_validation_once():
        if not _checked:
            run_check_once()
