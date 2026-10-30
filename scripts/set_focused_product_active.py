"""Activate or deactivate FOCUSED report products in a LOCAL database -- safely (F12-P3.4).

    python scripts/set_focused_product_active.py --keys promotion_timing,natural_strengths --active true            # dry run
    python scripts/set_focused_product_active.py --keys promotion_timing,natural_strengths --active true --apply    # write

Safety rules (see test_set_focused_product_active.py):
- Dry run unless --apply. Every run prints the before/after `active` state of each requested key.
- --keys is an exact allowlist: each key must be one of the backend's focused question_keys
  (modules.intents.question_catalog.QUESTIONS) AND its report_products row must use a focused generator.
  Standard report slugs (e.g. career_report) are always refused -- this tool cannot touch them.
- Local databases only (127.0.0.1 / localhost / ::1). The URL comes from --db-url, else DATABASE_URL in
  the environment, else .env; any remote host is refused.
- One atomic transaction: the requested rows are locked, re-checked and updated with
  `WHERE active IS DISTINCT FROM target`, so re-running is a no-op.
- Deactivation is refused while any PAID order for those products is unfinished (report not Ready or email
  not SENT): ReportGenerationDispatcher re-checks `active` before generating, so deactivating would strand a
  customer who already paid. There is deliberately no flag to bypass this.

Exit codes: 0 ok, 2 invalid request, 3 refused (unfinished paid orders), 4 environment refused.
"""
import argparse
import os
import sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
FOCUSED_GENERATORS = ("focused_v1", "focused_dual_v1")
UNFINISHED_PAID_SQL = (
    "SELECT product, id, report_stage, email_status FROM orders "
    "WHERE product = ANY(%s) AND payment_status = 'PAID' "
    "AND (report_stage IS DISTINCT FROM 'Ready' OR email_status IS DISTINCT FROM 'SENT') ORDER BY id"
)


class ToolError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def focused_keys():
    from modules.intents.question_catalog import QUESTIONS
    return {q.question_key for q in QUESTIONS}


def resolve_db_url(explicit=None):
    url = explicit or os.environ.get("DATABASE_URL")
    if not url:
        env_file = os.path.join(ROOT, ".env")
        if os.path.exists(env_file):
            with open(env_file, encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("DATABASE_URL="):
                        url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        raise ToolError("No database URL (--db-url, DATABASE_URL or .env).", 4)
    host = urlparse(url).hostname
    if host not in LOCAL_HOSTS:
        raise ToolError(f"Refusing non-local database host {host!r}; this tool only runs against a local database.", 4)
    return url


def parse_keys(raw, catalog):
    keys = [k.strip() for k in (raw or "").split(",") if k.strip()]
    if not keys:
        raise ToolError("--keys must list at least one focused question_key.", 2)
    if len(set(keys)) != len(keys):
        raise ToolError("--keys contains duplicates.", 2)
    unknown = sorted(set(keys) - catalog)
    if unknown:
        raise ToolError(f"Not focused question_keys (refused): {', '.join(unknown)}", 2)
    return keys


def run(keys_raw, active, apply=False, db_url=None, out=print):
    """Return a dict summary; raise ToolError on any refusal. Never writes unless apply=True."""
    keys = parse_keys(keys_raw, focused_keys())
    url = resolve_db_url(db_url)
    import psycopg2

    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT report_slug, active, generator FROM report_products WHERE report_slug = ANY(%s) "
                    "ORDER BY report_slug FOR UPDATE", (keys,))
        rows = {slug: (is_active, generator) for slug, is_active, generator in cur.fetchall()}
        missing = sorted(set(keys) - set(rows))
        if missing:
            raise ToolError(f"No report_products row for: {', '.join(missing)}", 2)
        not_focused = sorted(k for k, (_, gen) in rows.items() if gen not in FOCUSED_GENERATORS)
        if not_focused:
            raise ToolError(f"Not focused products (generator check, refused): {', '.join(not_focused)}", 2)

        changes = sorted(k for k, (is_active, _) in rows.items() if is_active != active)
        if not active and changes:
            cur.execute(UNFINISHED_PAID_SQL, (changes,))
            blocking = cur.fetchall()
            if blocking:
                detail = "; ".join(f"order {oid} ({prod}: stage={stage}, email={email})" for prod, oid, stage, email in blocking)
                raise ToolError(f"Refusing to deactivate: unfinished PAID orders would be stranded -- {detail}", 3)
            cur.execute("SELECT product, COUNT(*) FROM orders WHERE product = ANY(%s) AND payment_status = 'PAYMENT_PENDING' "
                        "GROUP BY product", (changes,))
            for product, count in cur.fetchall():
                out(f"WARNING: {product} has {count} PAYMENT_PENDING order(s); a later capture would be blocked from generation.")

        for key in keys:
            before = rows[key][0]
            out(f"{key}: active {before} -> {active if key in changes else before}{'' if key in changes else ' (unchanged)'}")

        updated = []
        if apply and changes:
            cur.execute("UPDATE report_products SET active = %s WHERE report_slug = ANY(%s) AND active IS DISTINCT FROM %s "
                        "RETURNING report_slug", (active, changes, active))
            updated = sorted(r[0] for r in cur.fetchall())
            if updated != changes:
                raise ToolError(f"Unexpected update set {updated} != {changes}; rolled back.", 4)
            conn.commit()
        else:
            conn.rollback()
        out(("APPLIED" if apply else "DRY RUN (no changes written; add --apply)") + f": {len(updated if apply else changes)} row(s) "
            + ("updated" if apply else "would change"))
        return {"keys": keys, "changes": changes, "updated": updated, "applied": bool(apply)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keys", required=True, help="comma-separated focused question_keys (exact allowlist)")
    parser.add_argument("--active", required=True, choices=("true", "false"))
    parser.add_argument("--apply", action="store_true", help="write the change (default is a dry run)")
    parser.add_argument("--db-url", help="local database URL (default: DATABASE_URL env, then .env)")
    args = parser.parse_args(argv)
    try:
        run(args.keys, args.active == "true", apply=args.apply, db_url=args.db_url)
    except ToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
