# db_safety.py

"""
LOCAL vs PRODUCTION ENVIRONMENT SAFETY BOUNDARY -- Phase 1.

The incident this exists to prevent: a local Flask process was left
running with no local DATABASE_URL override, so it silently inherited
this repo's own .env (whose DATABASE_URL is the real production
Postgres instance) and served/queried real production data from a
"local" admin dashboard session. Nothing in factory.py::create_app()
validated the DB target against the running environment before use --
this module is that missing check.

ENVIRONMENT CONTRACT (reused, not duplicated)
----------------------------------------------
This project already has exactly one canonical environment marker:
ACTIVITY_EVENTS_ENVIRONMENT (introduced by
modules/activity_events/service.py, whose own docstring confirms "this
codebase has no existing environment-detection convention of its own
-- no FLASK_ENV/APP_ENV/etc. anywhere"). Its allowed values are already
exactly {"local", "production"} -- exactly the two-value contract this
task asked for. Rather than introduce a second, competing APP_ENV
variable, this module formally promotes ACTIVITY_EVENTS_ENVIRONMENT to
also be the project's one general-purpose environment marker. Every
existing test file already sets it to "local" (or leaves it unset,
handled below) when running locally, so this reuse requires no test
migration.

DECISION LOGIC (enforce_local_database_safety, called from
factory.py::create_app() BEFORE SQLALCHEMY_DATABASE_URI is wired up or
any table is touched -- pure string inspection, the URL is never
dialed to make this decision):

  ACTIVITY_EVENTS_ENVIRONMENT == "production"
      -> ALLOW, unconditionally. An operator who has explicitly
         declared this process production is trusted; this guard's job
         is to catch ACCIDENTAL local/production crossover, never to
         second-guess a deliberate production declaration.

  ACTIVITY_EVENTS_ENVIRONMENT == "local"
      -> ALLOW only if DATABASE_URL's host+dbname match the approved
         local allowlist (see LOCAL_DB_ALLOWLIST below). Otherwise
         REFUSE -- this is the direct fix for the reported incident:
         a developer who *has* declared "local" but is (accidentally or
         via a stale .env) pointed at a non-local database.

  Anything else (unset, empty, a typo, any value outside the two above)
      -> AMBIGUOUS. Two sub-cases, in order:
      1. This process is actually running ON Render (detected via
         RENDER, which the Render platform injects automatically into
         every native-runtime web service -- see _running_on_render()
         below -- with ZERO render.yaml/dashboard configuration
         required). -> ALLOW. This is the fail-safe rule from this
         task's own brief: production must never be broken by this
         guard, and must never be required to change any Render
         configuration for that guarantee to hold, regardless of
         whether ACTIVITY_EVENTS_ENVIRONMENT actually ended up set on
         the live service.
      2. Not on Render -> this is indistinguishable from an ordinary
         local run that forgot to export ACTIVITY_EVENTS_ENVIRONMENT
         (exactly the reported incident's own shape). Falls back to the
         SAME local-allowlist check as the explicit "local" branch:
         ALLOW if the DB target is the approved local database (so
         ordinary local dev that simply forgot the env var still
         works), REFUSE otherwise (so an unmarked process pointed at
         production -- the actual incident -- is now caught).

This gives the one guarantee Step 5 of the brief requires unconditionally:
production, however it is actually configured today (explicit
ACTIVITY_EVENTS_ENVIRONMENT=production, OR nothing at all -- both real
possibilities, since this repo cannot inspect the live Render
dashboard), always starts. See PRODUCTION CONFIGURATION REQUIRED in
this task's report: NONE.

LOCAL DATABASE ALLOWLIST
------------------------
A positive allowlist (Step 4's preferred principle), not a production
blocklist -- this is what protects against a FUTURE production host/
name change too, not just today's known host. Never a fragile
substring check on the full DATABASE_URL (e.g. "if 'render' in
DATABASE_URL"): the URL is actually parsed and only its hostname and
database name are compared, both against an explicit, exact allowlist.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

# The only local Postgres database this project's local-dev convention
# ever points at (see every test_*.py's own identical LOCAL_DB_URL
# constant, and this engagement's established "never touch production
# DB, always verify via SELECT current_database()" rule). Extend this
# set deliberately, never guess, if a genuinely new local/test DB name
# is introduced later.
LOCAL_DB_ALLOWED_NAMES = frozenset({"jyotishasha_local"})
LOCAL_DB_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1"})

# Reused, not duplicated -- see module docstring.
_ENV_VAR = "ACTIVITY_EVENTS_ENVIRONMENT"


class DatabaseSafetyError(RuntimeError):
    """Raised by enforce_local_database_safety() to abort startup.
    Never carries the DATABASE_URL, credentials, or any secret -- only
    the parsed (safe-to-print) hostname/dbname it rejected, at most."""


def _running_on_render() -> bool:
    """True only when this process is actually executing on the Render
    platform. RENDER=true is injected automatically by Render into
    every native-runtime web service's environment -- this repo's
    render.yaml never has to (and does not) declare it; it is not a
    render.yaml/dashboard setting anyone can forget to configure, which
    is exactly why it is safe to lean on for the "never require a
    production config change" guarantee. Deliberately NOT a substring
    check on any URL."""
    return os.environ.get("RENDER") == "true"


def _parse_db_target(database_url: str | None) -> tuple[str | None, str | None]:
    """Returns (hostname, dbname), both lowercased, without ever
    connecting. (None, None) for an empty/unparseable value -- treated
    as "does not match the local allowlist", never as an error here."""
    if not database_url:
        return None, None
    try:
        parsed = urlparse(database_url)
    except ValueError:
        return None, None
    host = (parsed.hostname or "").lower() or None
    dbname = (parsed.path or "").lstrip("/").lower() or None
    return host, dbname


def _is_approved_local_db(database_url: str | None) -> bool:
    host, dbname = _parse_db_target(database_url)
    return host in LOCAL_DB_ALLOWED_HOSTS and dbname in LOCAL_DB_ALLOWED_NAMES


def _safe_target_summary(database_url: str | None) -> str:
    """A human-readable, non-secret description of the rejected target
    for the exception message -- deliberately NEVER the hostname itself
    (a bare hostname isn't a credential, but this errs on the safe side
    of "redact URLs" rather than relying on that distinction), only
    whether it looks local, plus the database name (a plain label, not
    a secret)."""
    host, dbname = _parse_db_target(database_url)
    host_kind = "a local-looking host" if host in LOCAL_DB_ALLOWED_HOSTS else "a non-local host"
    if host is None:
        host_kind = "no host at all"
    return f"Found: {host_kind}, database={dbname!r}"


def _announce(label: str) -> None:
    """The ONLY output this module ever prints -- a fixed, human-authored
    label plus which env-detection path allowed startup. Never the
    resolved host/dbname, never the URL, never a credential."""
    print(f"[db_safety] Environment: {label}")
    print("[db_safety] Database safety: LOCAL DATABASE VERIFIED"
          if label.startswith("local") else
          "[db_safety] Database safety: PRODUCTION (unguarded by design -- see db_safety.py)")


def enforce_local_database_safety(database_url: str | None) -> None:
    """Call BEFORE the app wires DATABASE_URL into SQLAlchemy or touches
    any table. Raises DatabaseSafetyError to abort startup; never prints
    or includes the URL/credentials, only the parsed host/dbname (safe,
    non-secret identifiers) when explaining a refusal."""
    declared_env = os.environ.get(_ENV_VAR)

    if declared_env == "production":
        _announce("production (explicit)")
        return  # explicit, trusted declaration -- never second-guessed

    if declared_env == "local":
        if _is_approved_local_db(database_url):
            _announce("local (explicit)")
            return
        summary = _safe_target_summary(database_url)
        raise DatabaseSafetyError(
            "Local development attempted to use a database that is not "
            "the approved local database. Startup aborted.\n"
            f"  Expected host in {sorted(LOCAL_DB_ALLOWED_HOSTS)}, "
            f"database in {sorted(LOCAL_DB_ALLOWED_NAMES)}.\n"
            f"  {summary} ({_ENV_VAR}={declared_env!r}).\n"
            "  Fix: point DATABASE_URL at jyotishasha_local, or unset "
            f"{_ENV_VAR} if this really is production."
        )

    # Ambiguous: unset, empty, or an unrecognized value.
    if _running_on_render():
        _announce("production (Render-detected, ambiguous marker)")
        return  # real deployed platform -- never blocked, zero config required

    if _is_approved_local_db(database_url):
        _announce("local (ambiguous marker, DB target verified)")
        return  # ordinary local dev that simply forgot to export the marker

    summary = _safe_target_summary(database_url)
    raise DatabaseSafetyError(
        "Local development attempted to use a production database. "
        "Startup aborted.\n"
        f"  {_ENV_VAR} is not set to a recognized value (got "
        f"{declared_env!r}), and the configured database is not the "
        f"approved local database.\n"
        f"  Expected host in {sorted(LOCAL_DB_ALLOWED_HOSTS)}, "
        f"database in {sorted(LOCAL_DB_ALLOWED_NAMES)}.\n"
        f"  {summary}.\n"
        f"  Fix: export {_ENV_VAR}=local and point DATABASE_URL at "
        "jyotishasha_local before starting Flask locally."
    )
