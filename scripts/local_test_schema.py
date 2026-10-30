"""Create or drop an isolated test schema inside the LOCAL development database (F12-P3.4).

    python scripts/local_test_schema.py create test_p34
    python scripts/local_test_schema.py drop test_p34

`create` builds every model table in the new schema with SQLAlchemy's create_all (Alembic is not used: two
migrations pin schema='public' and would write to development tables), then copies the report_products
registry rows from `public` with a read-only SELECT. Development data in `public` is never written. Use the
printed JYOTISHASHA_TEST_DATABASE_URL with the DB-writing suites (see local_test_db.py).
"""
import os
import re
import sys
from urllib.parse import quote, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEV_DB = "/jyotishasha_local"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def dev_url() -> str:
    with open(os.path.join(ROOT, ".env"), encoding="utf-8") as handle:
        lines = handle.readlines()
    for line in lines:
        if line.startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip().strip('"').strip("'")
            parsed = urlparse(url)
            if parsed.hostname not in LOCAL_HOSTS or parsed.path != DEV_DB:
                raise SystemExit(f"REFUSED: .env DATABASE_URL is not the local {DEV_DB[1:]} database.")
            return url
    raise SystemExit("REFUSED: no DATABASE_URL in .env")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("create", "drop"):
        raise SystemExit(__doc__)
    action, schema = sys.argv[1], sys.argv[2]
    if not re.fullmatch(r"test_[a-z0-9_]{1,40}", schema):
        raise SystemExit("REFUSED: schema must look like test_<name> (lowercase letters, digits, underscores).")
    base = dev_url()
    import psycopg2

    conn = psycopg2.connect(base)
    conn.autocommit = True
    cur = conn.cursor()
    if action == "drop":
        cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        print(f"dropped schema {schema}")
        return
    cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (schema,))
    if cur.fetchone():
        raise SystemExit(f"REFUSED: schema {schema} already exists; drop it first.")
    cur.execute(f'CREATE SCHEMA "{schema}"')

    isolated = f"{base}?options={quote(f'-csearch_path={schema}')}"
    os.environ["DATABASE_URL"] = isolated
    os.environ.setdefault("RAZORPAY_KEY_ID", "local-test-unused")
    os.environ.setdefault("RAZORPAY_KEY_SECRET", "local-test-unused")
    from app import app  # noqa: E402  (reads DATABASE_URL at import)
    from extensions import db
    with app.app_context():
        current = db.session.execute(db.text("SELECT current_schema()")).scalar()
        if current != schema:
            raise SystemExit(f"REFUSED: expected search_path {schema}, got {current!r}")
        db.create_all()
    # Fidelity with the Alembic-built schema: the model declares only unique=True, but migration
    # b3d8f1a6c2e9 names the constraint, and review_service matches on that name to return 409 try_again.
    cur.execute(f'ALTER TABLE "{schema}".report_reviews RENAME CONSTRAINT report_reviews_order_id_key TO uq_report_reviews_order_id')
    # Registry rows only: read from public, written into the isolated schema.
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = 'report_products' "
                "ORDER BY ordinal_position", (schema,))
    columns = ", ".join(f'"{name}"' for (name,) in cur.fetchall())
    cur.execute(f'INSERT INTO "{schema}".report_products ({columns}) SELECT {columns} FROM public.report_products')
    cur.execute(f'SELECT COUNT(*), COUNT(*) FILTER (WHERE active) FROM "{schema}".report_products')
    total, active = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s", (schema,))
    print(f"created schema {schema}: {cur.fetchone()[0]} tables, report_products {total} rows ({active} active)")
    print(f"JYOTISHASHA_TEST_DATABASE_URL={isolated}")


if __name__ == "__main__":
    main()
