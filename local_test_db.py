"""Opt-in isolated database target for the local DB-writing test suites (F12-P3.4).

The report-platform suites write real rows (orders, processed payments, product flags) and historically
pointed straight at the shared development database. Setting

    JYOTISHASHA_TEST_DATABASE_URL=postgresql://<user>@127.0.0.1:5432/jyotishasha_local?options=-csearch_path%3Dtest_<name>

runs them inside a dedicated schema instead (built by scripts/local_test_schema.py), so the development
data in `public` is never written. The search_path must name exactly one `test_` schema: with `public`
absent from the path, a missing table fails loudly instead of silently reaching development data.
Without the variable each suite keeps its existing default.
"""
import os
from urllib.parse import parse_qs, unquote, urlparse

ENV_VAR = "JYOTISHASHA_TEST_DATABASE_URL"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def isolated_schema(url: str):
    """The single search_path schema named in the URL's libpq `options`, or None."""
    for option in parse_qs(urlparse(url).query).get("options", []):
        for part in unquote(option).split():
            if part.startswith("-csearch_path="):
                return part.split("=", 1)[1]
    return None


def resolve_test_db_url(default: str) -> str:
    """The isolated URL when JYOTISHASHA_TEST_DATABASE_URL is set (validated), else `default`."""
    url = os.environ.get(ENV_VAR)
    if not url:
        return default
    parsed = urlparse(url)
    if parsed.hostname not in LOCAL_HOSTS:
        raise SystemExit(f"REFUSING TO RUN: {ENV_VAR} must point at a local host, got {parsed.hostname!r}.")
    schema = isolated_schema(url)
    if not schema or not schema.startswith("test_") or "," in schema:
        raise SystemExit(f"REFUSING TO RUN: {ENV_VAR} must pin search_path to exactly one test_ schema, got {schema!r}.")
    return url


LOCAL_DEV_DB_PATH = "/jyotishasha_local"


def _dotenv_database_url() -> str:
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_file):
        return ""
    with open(env_file, encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def local_dev_db_url() -> str:
    """The developer's own local DATABASE_URL (environment, then .env), never the isolated test schema.

    Anything that is not the local jyotishasha_local database on a local host is refused, so a production
    or staging URL in the environment can never be used. The URL itself is never printed.
    """
    url = os.environ.get("DATABASE_URL") or _dotenv_database_url()
    parsed = urlparse(url)
    if parsed.hostname not in LOCAL_HOSTS or parsed.path != LOCAL_DEV_DB_PATH:
        raise SystemExit("REFUSING TO RUN: a local jyotishasha_local DATABASE_URL is required "
                         f"(or {ENV_VAR} for tests); host {parsed.hostname!r} / database {parsed.path!r} is not allowed.")
    return url


def local_test_db_url() -> str:
    """Database URL for the local DB-writing suites. No credentials live in test code.

    The isolated schema (JYOTISHASHA_TEST_DATABASE_URL) when set; otherwise local_dev_db_url().
    """
    if os.environ.get(ENV_VAR):
        return resolve_test_db_url("")
    return local_dev_db_url()


def describe_target(url: str) -> str:
    """host:port/database only -- never the user or password."""
    parsed = urlparse(url)
    return f"{parsed.hostname}:{parsed.port or 5432}{parsed.path}"


CONFIRM_FLAG = "--confirm-target"


def require_target_confirmation(url: str, argv, script: str) -> None:
    """Writes need `--confirm-target <database>` naming the exact database about to be changed."""
    expected = urlparse(url).path.lstrip("/")
    given = argv[argv.index(CONFIRM_FLAG) + 1] if CONFIRM_FLAG in argv[:-1] else None
    if given != expected:
        raise SystemExit(f"Target: {describe_target(url)}. Nothing was changed.\n"
                         f"Re-run with `python {script} {CONFIRM_FLAG} {expected}` to apply.")


def assert_isolated_schema(current_schema: str) -> None:
    """When isolation is requested, the live connection must actually be in that schema."""
    url = os.environ.get(ENV_VAR)
    if url and current_schema != isolated_schema(url):
        raise SystemExit(f"REFUSING TO RUN: expected schema {isolated_schema(url)!r}, connected to {current_schema!r}.")
