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


def assert_isolated_schema(current_schema: str) -> None:
    """When isolation is requested, the live connection must actually be in that schema."""
    url = os.environ.get(ENV_VAR)
    if url and current_schema != isolated_schema(url):
        raise SystemExit(f"REFUSING TO RUN: expected schema {isolated_schema(url)!r}, connected to {current_schema!r}.")
