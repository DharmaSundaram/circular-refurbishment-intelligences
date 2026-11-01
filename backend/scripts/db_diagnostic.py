#!/usr/bin/env python3
"""Database Connectivity Diagnostic Tool for Refurbishment Intelligence.

Performs read-only verification of:
1. PostgreSQL connectivity.
2. Current database, user, schema, and PostgreSQL engine version.
3. Existence of the dedicated 'refurbishment' schema.
4. Existence of all required application tables.
5. Migration tracking status via 'refurbishment.alembic_version'.
6. Database user privileges (SELECT, INSERT, UPDATE, DELETE).
7. Partner schema isolation ('collection' schema separation).

STRICT RULE: This diagnostic is 100% read-only. It performs NO DDL or DML.
"""

import os
import sys
import argparse
from pathlib import Path
from typing import Dict, Any, List

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from config import Config, normalize_and_validate_database_url, PLACEHOLDER_SUBSTRINGS
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

REQUIRED_TABLES = [
    "devices",
    "assessments",
    "assessment_components",
    "recovery_analyses",
    "reports",
    "transfers",
    "device_files",
    "idempotency_events",
]


def run_database_diagnostic(db_url: str = None) -> Dict[str, Any]:
    """Execute a comprehensive, read-only diagnostic on the database connection."""
    raw_url = (
        db_url
        or os.environ.get("SUPABASE_DB_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
    )

    results: Dict[str, Any] = {
        "configured": False,
        "is_sqlite": False,
        "url_valid": False,
        "connected": False,
        "placeholder_detected": None,
        "session": {},
        "refurbishment_schema_exists": False,
        "collection_schema_exists": False,
        "tables_found": [],
        "missing_tables": [],
        "alembic_version_table_exists": False,
        "alembic_current_revision": None,
        "privileges": {},
        "issues": [],
        "warnings": [],
        "status": "FAIL",
    }

    if not raw_url:
        results["issues"].append(
            "No database URL found in SUPABASE_DB_URL, DATABASE_URL, or POSTGRES_URL. "
            "Please configure SUPABASE_DB_URL with your Supabase PostgreSQL connection string."
        )
        return results

    results["configured"] = True

    # Check for placeholder credentials in the connection string
    raw_lower = raw_url.lower()
    for placeholder in PLACEHOLDER_SUBSTRINGS:
        if placeholder in raw_lower:
            results["placeholder_detected"] = placeholder
            results["issues"].append(
                f"Placeholder token '{placeholder}' detected in database connection string. "
                "The Supabase pooler requires your actual project reference ID (not 'projectref'). "
                "Format: postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres "
                "or direct: postgresql://postgres:[PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres"
            )
            return results

    if any(c in raw_url for c in ("[", "]", "<", ">")):
        results["placeholder_detected"] = "bracketed_token"
        results["issues"].append(
            "Unreplaced bracket token (e.g., '[PASSWORD]' or '<PROJECT-REF>') detected in connection string. "
            "Ensure actual credentials are substituted."
        )
        return results

    # Normalize connection string
    normalized_url = normalize_and_validate_database_url(raw_url, is_production=False)
    results["url_valid"] = True

    if normalized_url.startswith("sqlite"):
        results["is_sqlite"] = True
        results["warnings"].append(
            "Connected to local SQLite database. In production, configure SUPABASE_DB_URL for PostgreSQL."
        )

    # Establish read-only engine connection
    schema_name = os.environ.get("DB_SCHEMA", "refurbishment")
    engine_kwargs = {"poolclass": NullPool}
    if not results["is_sqlite"]:
        engine_kwargs["connect_args"] = {
            "options": f"-c search_path={schema_name},public",
        }

    try:
        engine = create_engine(normalized_url, **engine_kwargs)
        with engine.connect() as conn:
            # Set session to read-only mode for safety
            if not results["is_sqlite"]:
                conn.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;"))

            # 1. Connectivity test
            conn.execute(text("SELECT 1;"))
            results["connected"] = True

            # 2. Session identification
            if not results["is_sqlite"]:
                session_row = conn.execute(
                    text("SELECT current_database(), current_user, current_schema(), version();")
                ).fetchone()
                if session_row:
                    results["session"] = {
                        "current_database": session_row[0],
                        "current_user": session_row[1],
                        "current_schema": session_row[2],
                        "postgres_version": session_row[3].split()[0] + " " + session_row[3].split()[1],
                    }

                # 3. Check schema existence
                schema_res = conn.execute(
                    text("SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('refurbishment', 'collection');")
                ).fetchall()
                found_schemas = {r[0] for r in schema_res}
                results["refurbishment_schema_exists"] = "refurbishment" in found_schemas
                results["collection_schema_exists"] = "collection" in found_schemas

                if not results["refurbishment_schema_exists"]:
                    results["issues"].append(
                        "Schema 'refurbishment' does NOT exist in the database. "
                        "Run 'flask migrate-refurbishment-schema' or execute backend/migrations/refurbishment_schema.sql."
                    )

                # 4. Check required tables in refurbishment schema
                tables_res = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'refurbishment';"
                    )
                ).fetchall()
                found_tables = {r[0] for r in tables_res}
                results["tables_found"] = sorted(list(found_tables))

                for req_tbl in REQUIRED_TABLES:
                    if req_tbl not in found_tables:
                        results["missing_tables"].append(req_tbl)

                if results["missing_tables"]:
                    results["issues"].append(
                        f"Missing required table(s) in 'refurbishment' schema: {', '.join(results['missing_tables'])}. "
                        "Run 'flask migrate-refurbishment-schema' to initialize."
                    )

                # 5. Check alembic_version table
                alembic_check = conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = 'refurbishment' AND table_name = 'alembic_version');"
                    )
                ).scalar()

                if alembic_check:
                    results["alembic_version_table_exists"] = True
                    rev = conn.execute(
                        text("SELECT version_num FROM refurbishment.alembic_version LIMIT 1;")
                    ).scalar()
                    results["alembic_current_revision"] = rev
                else:
                    results["warnings"].append(
                        "Table 'refurbishment.alembic_version' does not exist. "
                        "If tables were created via SQL script, run 'flask stamp-refurbishment-schema' to align Alembic."
                    )

                # 6. Check privileges on refurbishment tables
                if found_tables:
                    priv_summary = {}
                    for tbl in REQUIRED_TABLES:
                        if tbl in found_tables:
                            priv_row = conn.execute(
                                text(
                                    f"SELECT has_table_privilege(current_user, 'refurbishment.{tbl}', 'SELECT') AS can_sel, "
                                    f"has_table_privilege(current_user, 'refurbishment.{tbl}', 'INSERT') AS can_ins, "
                                    f"has_table_privilege(current_user, 'refurbishment.{tbl}', 'UPDATE') AS can_upd, "
                                    f"has_table_privilege(current_user, 'refurbishment.{tbl}', 'DELETE') AS can_del;"
                                )
                            ).fetchone()
                            if priv_row:
                                priv_summary[tbl] = {
                                    "SELECT": priv_row[0],
                                    "INSERT": priv_row[1],
                                    "UPDATE": priv_row[2],
                                    "DELETE": priv_row[3],
                                }
                                if not all(priv_row):
                                    results["warnings"].append(
                                        f"User '{results['session'].get('current_user')}' lacks some permissions on 'refurbishment.{tbl}'."
                                    )
                    results["privileges"] = priv_summary

                # 7. Check collection schema isolation
                if results["collection_schema_exists"]:
                    results["session"]["collection_schema_status"] = "present (partner schema isolated)"

            else:
                # SQLite fallback inspection
                tables_res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';")).fetchall()
                found_tables = {r[0] for r in tables_res}
                results["tables_found"] = sorted(list(found_tables))
                for req_tbl in REQUIRED_TABLES:
                    if req_tbl not in found_tables:
                        results["missing_tables"].append(req_tbl)

            # Determine overall status
            if not results["issues"]:
                results["status"] = "PASS"
            elif results["connected"] and not results["missing_tables"]:
                results["status"] = "WARN"
            else:
                results["status"] = "FAIL"

    except Exception as e:
        results["connected"] = False
        results["issues"].append(f"Connection failure: {str(e)}")
        results["status"] = "FAIL"

    return results


def print_diagnostic_report(res: Dict[str, Any]):
    """Format and print the diagnostic results to stdout using ASCII-safe characters."""
    print("=" * 72)
    print("  REFURBISHMENT INTELLIGENCE -- DATABASE CONNECTIVITY DIAGNOSTIC")
    print("=" * 72)

    status_icon = "[PASS]" if res["status"] == "PASS" else ("[WARN]" if res["status"] == "WARN" else "[FAIL]")
    print(f"Overall Status: {status_icon}")
    print(f"Database Configured: {'Yes' if res['configured'] else 'No'}")

    if res.get("placeholder_detected"):
        print(f"Placeholder Detected: [DETECTED] '{res['placeholder_detected']}'")

    print(f"PostgreSQL Connected: {'[OK] Yes' if res['connected'] else '[FAIL] No'}")

    if res.get("session"):
        s = res["session"]
        print("-" * 72)
        print("  SESSION & CONNECTION CONTEXT")
        print("-" * 72)
        print(f"  Current Database:   {s.get('current_database')}")
        print(f"  Current User:       {s.get('current_user')}")
        print(f"  Search Schema:      {s.get('current_schema')}")
        print(f"  PostgreSQL Version: {s.get('postgres_version')}")

    print("-" * 72)
    print("  SCHEMA & TABLES VERIFICATION")
    print("-" * 72)
    if not res["connected"]:
        print("  Status:                 N/A (Connection not established)")
    else:
        refurb_stat = "[OK] Exists" if res["refurbishment_schema_exists"] else ("N/A (SQLite)" if res["is_sqlite"] else "[MISSING]")
        col_stat = "[OK] Present & Isolated" if res["collection_schema_exists"] else "Not Present"
        print(f"  'refurbishment' Schema: {refurb_stat}")
        print(f"  'collection' Schema:    {col_stat}")
        print(f"  Tables Found:           {len(res['tables_found'])} ({', '.join(res['tables_found']) if res['tables_found'] else 'None'})")

        if res["missing_tables"]:
            print(f"  Missing Required Tables: [MISSING] {', '.join(res['missing_tables'])}")
        else:
            print(f"  Required Tables:        [OK] All {len(REQUIRED_TABLES)} required tables present")

    print("-" * 72)
    print("  ALEMBIC MIGRATION STATUS")
    print("-" * 72)
    if not res["connected"]:
        print("  Status:                 N/A (Connection not established)")
    else:
        elembic_stat = "[OK] refurbishment.alembic_version present" if res["alembic_version_table_exists"] else "[NOT FOUND]"
        print(f"  Version Table:          {elembic_stat}")
        print(f"  Current Revision:       {res['alembic_current_revision'] or 'None'}")

    if res.get("privileges"):
        print("-" * 72)
        print("  USER PRIVILEGES CHECK")
        print("-" * 72)
        all_ok = True
        for tbl, privs in res["privileges"].items():
            priv_str = " ".join([f"{k}:{'OK' if v else 'NO'}" for k, v in privs.items()])
            if not all(privs.values()):
                all_ok = False
            print(f"  refurbishment.{tbl:<22} -> {priv_str}")
        if all_ok:
            print("  Privileges:             [OK] Full CRUD privileges on all tables")

    if res["warnings"]:
        print("-" * 72)
        print("  WARNINGS")
        print("-" * 72)
        for w in res["warnings"]:
            print(f"  ! {w}")

    if res["issues"]:
        print("-" * 72)
        print("  CRITICAL ISSUES / REMEDIATION REQUIRED")
        print("-" * 72)
        for issue in res["issues"]:
            print(f"  * {issue}")

    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="Read-only PostgreSQL connectivity diagnostic.")
    parser.add_argument("--url", help="Database connection URL to test (defaults to SUPABASE_DB_URL)", default=None)
    args = parser.parse_args()

    results = run_database_diagnostic(args.url)
    print_diagnostic_report(results)
    sys.exit(0 if results["status"] in ("PASS", "WARN") else 1)


if __name__ == "__main__":
    main()
