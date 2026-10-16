"""Shared, fail-closed metadata guards. No connection is opened on import."""
from pathlib import Path
import hashlib
import json
import os
import subprocess


class SecurityFailure(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise SecurityFailure(code)


# PostgreSQL grants EXECUTE on these pg_catalog built-ins to PUBLIC by default, and only a superuser can
# revoke them (for every role at once). For a READ-ONLY guard role they cannot reach user data: the verified
# read-only transaction rejects nextval/setval and the large-object writes, the role holds no sequence
# privilege (checked below), pg_notify carries no data, and pg_cancel/terminate_backend only affect the
# role's own sessions. Accepted only in read-only mode and only when the right comes solely from PUBLIC.
# lo_import/lo_export (server file access) are deliberately NOT listed.
PUBLIC_DEFAULT_BUILTINS = (
    "nextval", "setval", "pg_notify", "pg_cancel_backend", "pg_terminate_backend", "lowrite",
    "lo_open", "lo_close", "lo_creat", "lo_create", "lo_unlink", "lo_lseek", "lo_lseek64", "lo_tell",
    "lo_tell64", "lo_truncate", "lo_truncate64", "lo_from_bytea", "lo_get", "lo_put",
)

# Also PUBLIC-default in PostgreSQL 17, but refused at run time ("permission denied to use replication slots")
# unless the role has REPLICATION or superuser. Excused only when the role cannot reach either attribute.
REPLICATION_SLOT_BUILTINS = (
    "pg_create_physical_replication_slot", "pg_create_logical_replication_slot", "pg_drop_replication_slot",
)

# OWNER-APPROVED RESIDUAL RISK (read-only exporter only). PostgreSQL 17 grants EXECUTE on both variants
# (text, bytea) to PUBLIC, and they run even in a READ ONLY transaction: verified locally, a rolled-back call
# still writes its payload to WAL (~1 MB per 1 MB message) and into logical-decoding streams. It cannot read
# or change user data, a role-level REVOKE cannot remove PUBLIC's grant, and every login already holds it.
# Mitigations live outside this guard: CONNECTION LIMIT 2, statement_timeout, an interactive never-stored
# password, the exporter never calls it, and the role is dropped after the comparison. Excused under the
# same conditions as REPLICATION_SLOT_BUILTINS; writer mode never excuses it.
WAL_MESSAGE_BUILTINS = ("pg_logical_emit_message",)

# Excused only while the role cannot reach REPLICATION or superuser.
PRIVILEGE_GATED_BUILTINS = REPLICATION_SLOT_BUILTINS + WAL_MESSAGE_BUILTINS

# True when the role reaches EXECUTE/privilege through something other than PUBLIC (grantee 0).
_GRANTED_BEYOND_PUBLIC = """EXISTS(SELECT 1 FROM pg_catalog.aclexplode({acl}) a
    WHERE a.privilege_type = '{privilege}' AND a.grantee <> 0 AND pg_catalog.pg_has_role(current_user, a.grantee, 'MEMBER'))"""

# Params: (readonly, PUBLIC_DEFAULT_BUILTINS list, PRIVILEGE_GATED_BUILTINS list). Counts executable
# routines the role must not have.
ROUTINE_CHECK_SQL = """SELECT count(*) FROM pg_catalog.pg_proc p
    JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
    WHERE has_function_privilege(current_user, p.oid, 'EXECUTE') AND
    (n.nspname NOT IN ('pg_catalog','information_schema') OR p.prosecdef OR
     p.proname ~ '^(lo_|lo_create$|lo_creat$|lo_unlink$|lowrite$|nextval$|setval$|pg_notify$|pg_logical_emit_message$|pg_write_|pg_file_|pg_reload_conf$|pg_rotate_logfile$|pg_terminate_backend$|pg_cancel_backend$|pg_promote$|pg_stat_reset|pg_create_|pg_drop_|pg_switch_|pg_backup_)')
    AND NOT (%s AND n.nspname = 'pg_catalog' AND NOT p.prosecdef
             AND NOT """ + _GRANTED_BEYOND_PUBLIC.format(
    acl="COALESCE(p.proacl, pg_catalog.acldefault('f', p.proowner))", privilege="EXECUTE") + """
             AND (p.proname = ANY(%s) OR (p.proname = ANY(%s) AND NOT EXISTS(
                 SELECT 1 FROM pg_catalog.pg_roles r WHERE (r.rolreplication OR r.rolsuper)
                 AND pg_catalog.pg_has_role(current_user, r.oid, 'MEMBER')))))"""

# Param: (readonly,). 1 when the role may CREATE in the database, or holds TEMP other than the PUBLIC default
# in read-only mode (a read-only transaction cannot run CREATE TEMP TABLE).
DATABASE_CHECK_SQL = """SELECT (has_database_privilege(current_user, current_database(), 'CREATE')
    OR (has_database_privilege(current_user, current_database(), 'TEMP') AND NOT (%s AND NOT EXISTS(
        SELECT 1 FROM pg_catalog.pg_database d
        WHERE d.datname = current_database() AND """ + _GRANTED_BEYOND_PUBLIC.format(
    acl="COALESCE(d.datacl, pg_catalog.acldefault('d', d.datdba))", privilege="TEMPORARY") + "))))::integer"

# Neither the reader nor the writer needs any sequence; without USAGE/UPDATE, nextval/setval cannot run.
SEQUENCE_CHECK_SQL = """SELECT count(*) FROM pg_catalog.pg_class c WHERE c.relkind = 'S' AND
    (has_sequence_privilege(current_user, c.oid, 'USAGE') OR has_sequence_privilege(current_user, c.oid, 'UPDATE')
     OR has_sequence_privilege(current_user, c.oid, 'SELECT'))"""


def storage_preflight(directory):
    path = Path(directory).resolve(strict=True)
    require(path.is_dir(), "storage_not_directory")
    # Never accept repositories, known cloud folders or shared temp as data storage.
    workspace = Path(__file__).resolve().parents[1]
    require(not path.is_relative_to(workspace), "storage_inside_repository")
    require(not any((parent / ".git").exists() for parent in (path,) + tuple(path.parents)), "storage_inside_repository")
    for root in (os.environ.get("OneDrive"), os.environ.get("OneDriveConsumer"), os.environ.get("OneDriveCommercial"),
                 os.environ.get("TEMP"), os.environ.get("TMP")):
        if root:
            require(not path.is_relative_to(Path(root).resolve()), "storage_synced_or_temporary")
    require(os.name == "nt", "storage_platform_requires_reviewed_encryption_adapter")
    script = Path(__file__).with_name("manglik_storage_preflight.ps1")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-File", str(script),
                             "-Directory", str(directory)], capture_output=True, text=True, check=False)
    require(result.returncode == 0, "storage_verification_failed")
    try:
        proof = json.loads(result.stdout)
    except ValueError:
        raise SecurityFailure("storage_invalid_proof") from None
    require(proof == {"encrypted": True, "restricted_acl": True, "no_reparse_points": True}, "storage_unverified")
    return path


def verify_connection(conn, approved, readonly=True):
    """Inspect only metadata. Never echo DSNs, host values or exception messages."""
    params = conn.get_dsn_parameters()
    for key in ("host", "port", "dbname", "user"):
        require(str(params.get(key, "")) == str(approved[key]), "connection_identity_mismatch")
    require(params.get("sslmode") == "verify-full", "tls_certificate_validation_required")
    require(params.get("sslrootcert") == str(approved["sslrootcert"]), "tls_ca_mismatch")
    require(Path(approved["sslrootcert"]).is_file(), "tls_ca_missing")
    require(hashlib.sha256(Path(approved["sslrootcert"]).read_bytes()).hexdigest() == approved["sslrootcert_sha256"], "tls_ca_integrity_mismatch")
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL search_path = pg_catalog")
        cursor.execute("SET LOCAL statement_timeout = '5min'")
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("""SELECT current_database(), current_user,
            current_setting('transaction_read_only'), current_setting('transaction_isolation'),
            EXISTS(SELECT 1 FROM pg_catalog.pg_stat_ssl WHERE pid = pg_backend_pid() AND ssl),
            EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = current_user AND
                   (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls))""")
        database, role, ro, isolation, tls, elevated = cursor.fetchone()
        require(database == approved["dbname"] and role == approved["user"], "server_identity_mismatch")
        require(tls and not elevated, "tls_or_role_attributes_unsafe")
        require(ro == ("on" if readonly else "off"), "transaction_mode_mismatch")
        require(isolation == ("repeatable read" if readonly else "read committed"), "isolation_mismatch")
        # No ownership or reachable privileged/owner role, including SET ROLE capability.
        cursor.execute("""SELECT count(*) FROM pg_catalog.pg_roles r WHERE r.rolname <> current_user
            AND pg_has_role(current_user, r.oid, 'MEMBER') AND
            (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls
             OR r.rolname IN ('pg_write_all_data','pg_read_server_files','pg_write_server_files','pg_execute_server_program')
             OR EXISTS(SELECT 1 FROM pg_catalog.pg_class c WHERE c.relowner = r.oid))""")
        require(cursor.fetchone()[0] == 0, "reachable_privileged_role")
        cursor.execute("""SELECT count(*) FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND
            c.relowner = (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = current_user)""")
        require(cursor.fetchone()[0] == 0, "role_owns_relations")
        # All callable non-system routines are untrusted until separately reviewed.
        # Also reject known side-effecting built-ins, including large-object/sequence writes, except the
        # PUBLIC-default built-ins a read-only role cannot avoid (see PUBLIC_DEFAULT_BUILTINS).
        cursor.execute(ROUTINE_CHECK_SQL, (readonly, list(PUBLIC_DEFAULT_BUILTINS), list(PRIVILEGE_GATED_BUILTINS)))
        require(cursor.fetchone()[0] == 0, "executable_unreviewed_or_side_effecting_routines")
        cursor.execute(SEQUENCE_CHECK_SQL)
        require(cursor.fetchone()[0] == 0, "sequence_privilege")
        cursor.execute("""SELECT count(*) FROM pg_catalog.pg_namespace
            WHERE has_schema_privilege(current_user, oid, 'CREATE')""")
        require(cursor.fetchone()[0] == 0, "schema_create_privilege")
        cursor.execute(DATABASE_CHECK_SQL, (readonly,))
        require(cursor.fetchone()[0] == 0, "database_create_or_temp_privilege")
        cursor.execute("""SELECT count(*) FROM pg_catalog.pg_class c
            WHERE c.relkind IN ('r','p','v','m','f') AND
            (has_table_privilege(current_user,c.oid,'INSERT') OR has_table_privilege(current_user,c.oid,'UPDATE')
             OR has_table_privilege(current_user,c.oid,'DELETE') OR has_table_privilege(current_user,c.oid,'TRUNCATE')
             OR has_any_column_privilege(current_user,c.oid,'INSERT'))""")
        require(cursor.fetchone()[0] == 0, "table_write_privilege")
        cursor.execute("""SELECT n.nspname,c.relname,a.attname FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE a.attnum>0 AND NOT a.attisdropped AND c.relkind IN ('r','p','v','f')
              AND has_column_privilege(current_user,c.oid,a.attnum,'UPDATE')""")
        updates = set(cursor.fetchall())
        expected = {("public", "app_users", name) for name in (
            "static_dosh", "manglik_calculation_version", "manglik_calculated_at",
            "manglik_input_digest", "manglik_correction_run_id")}
        require(not updates if readonly else updates == expected, "column_write_scope_mismatch")
        cursor.execute("""SELECT n.nspname,c.relname,a.attname FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE a.attnum>0 AND NOT a.attisdropped AND n.nspname NOT IN ('pg_catalog','information_schema')
              AND c.relkind IN ('r','p','v','f') AND has_column_privilege(current_user,c.oid,a.attnum,'SELECT')""")
        reads = set(cursor.fetchall())
        read_fields = {"firebase_uid", "dob", "tob", "pob", "lat", "lng", "static_dosh"}
        if not readonly:
            read_fields |= {"id", "manglik_calculation_version", "manglik_calculated_at", "manglik_input_digest", "manglik_correction_run_id"}
        require(reads == {("public", "app_users", name) for name in read_fields}, "column_read_scope_mismatch")
        cursor.execute("""SELECT c.relkind,c.relrowsecurity FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname='app_users'""")
        require(cursor.fetchone() == ('r', False), "application_relation_or_rls_requires_review")
    return True


def connect_verified(approved, readonly):
    """Called only by an explicitly executed operation, never from tests/imports."""
    import psycopg2
    conn = psycopg2.connect(service=approved["service"], sslmode="verify-full", sslrootcert=approved["sslrootcert"])
    try:
        conn.set_session(readonly=readonly, isolation_level="REPEATABLE READ" if readonly else "READ COMMITTED")
        verify_connection(conn, approved, readonly)
        return conn
    except SecurityFailure:
        conn.close()
        raise
    except Exception:
        conn.close()
        raise SecurityFailure("connection_preflight_failed") from None
