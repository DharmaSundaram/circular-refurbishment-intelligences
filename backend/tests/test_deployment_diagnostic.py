"""Tests for database URL normalization, placeholder detection, transfers API authentication,
and the read-only database connectivity diagnostic tool.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

import config
from config import (
    Config,
    normalize_and_validate_database_url,
    KNOWN_UNSUPPORTED_PSYCOPG_PARAMS,
    PLACEHOLDER_SUBSTRINGS,
)
from app import create_app
from extensions import db
from models.transfer import Transfer
from scripts.db_diagnostic import run_database_diagnostic, REQUIRED_TABLES
from migrations.env import include_object


class DatabaseUrlNormalizationTests(unittest.TestCase):
    """Verify database URL normalization, parameter stripping, and placeholder validation."""

    def test_postgres_scheme_converted_to_psycopg(self):
        url = "postgres://user:pass@host:5432/dbname"
        norm = normalize_and_validate_database_url(url, is_production=False)
        self.assertTrue(norm.startswith("postgresql+psycopg://"))

    def test_generic_postgresql_scheme_converted_to_psycopg(self):
        url = "postgresql://user:pass@host:5432/dbname"
        norm = normalize_and_validate_database_url(url, is_production=False)
        self.assertTrue(norm.startswith("postgresql+psycopg://"))

    def test_already_psycopg_scheme_preserved(self):
        url = "postgresql+psycopg://user:pass@host:5432/dbname"
        norm = normalize_and_validate_database_url(url, is_production=False)
        self.assertTrue(norm.startswith("postgresql+psycopg://"))

    def test_pgbouncer_and_connection_limit_stripped(self):
        url = "postgresql://user:pass@host:6543/postgres?pgbouncer=true&connection_limit=1&sslmode=require"
        norm = normalize_and_validate_database_url(url, is_production=False)
        self.assertNotIn("pgbouncer", norm)
        self.assertNotIn("connection_limit", norm)
        self.assertIn("sslmode=require", norm)

    def test_placeholder_projectref_raises_value_error_in_production(self):
        url = "postgresql://postgres.projectref:mypassword@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        with self.assertRaises(ValueError) as ctx:
            normalize_and_validate_database_url(url, is_production=True)
        self.assertIn("projectref", str(ctx.exception))
        self.assertIn("Supabase pooler requires your actual project reference ID", str(ctx.exception))

    def test_bracketed_placeholder_tokens_raise_value_error_in_production(self):
        bracketed_urls = [
            "postgresql://postgres.[PROJECT-REF]:secret@host:6543/postgres",
            "postgresql://postgres:secret@[PROJECT-REF].supabase.co:5432/postgres",
            "postgresql://postgres:[PASSWORD]@host:6543/postgres",
            "postgresql://postgres:<PASSWORD>@host:6543/postgres",
        ]
        for b_url in bracketed_urls:
            with self.subTest(url=b_url):
                with self.assertRaises(ValueError) as ctx:
                    normalize_and_validate_database_url(b_url, is_production=True)
                self.assertIn("Invalid database connection URL", str(ctx.exception))


class TransfersApiAuthenticationTests(unittest.TestCase):
    """Verify that all transfer endpoints are properly secured with internal administrator authentication."""

    def setUp(self):
        class TransferTestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
            ADMIN_API_KEY = "admin-secret-key-100"
            PARTNER_INBOUND_API_KEY = "partner-inbound-key-200"
            CIRCULAR_API_KEY = None

        self.app = create_app(config_class=TransferTestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        # Seed sample transfer record
        t = Transfer(
            transfer_id="TRF-TEST-DIAG-01",
            device_id="DEV-DIAG-01",
            direction="Inbound",
            sender="Collection",
            receiver="Refurbishment",
            endpoint="/api/v1/refurbishment/devices",
            http_method="POST",
            http_status=201,
            status="Completed",
        )
        db.session.add(t)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_list_transfers_unauthenticated_returns_401(self):
        resp = self.client.get("/api/v1/transfers")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Administrator authentication required", resp.get_json()["message"])

    def test_list_transfers_partner_key_rejected_with_403(self):
        resp = self.client.get(
            "/api/v1/transfers",
            headers={"X-API-Key": "partner-inbound-key-200"},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("PARTNER_INBOUND_API_KEY is not permitted", resp.get_json()["message"])

    def test_list_transfers_admin_key_returns_200(self):
        resp = self.client.get(
            "/api/v1/transfers",
            headers={"X-API-Key": "admin-secret-key-100"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["transfers"][0]["transfer_id"], "TRF-TEST-DIAG-01")

    def test_get_transfer_detail_unauthenticated_returns_401(self):
        resp = self.client.get("/api/v1/transfers/TRF-TEST-DIAG-01")
        self.assertEqual(resp.status_code, 401)

    def test_get_transfer_detail_admin_key_returns_200(self):
        resp = self.client.get(
            "/api/v1/transfers/TRF-TEST-DIAG-01",
            headers={"X-API-Key": "admin-secret-key-100"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["transfer_id"], "TRF-TEST-DIAG-01")

    def test_retry_transfer_unauthenticated_returns_401(self):
        resp = self.client.post("/api/v1/transfers/TRF-TEST-DIAG-01/retry")
        self.assertEqual(resp.status_code, 401)


class DatabaseDiagnosticToolTests(unittest.TestCase):
    """Verify behavior of the read-only database diagnostic tool."""

    def test_unconfigured_url_reports_failure(self):
        with patch.dict(os.environ, {}, clear=True):
            res = run_database_diagnostic(None)
            self.assertEqual(res["status"], "FAIL")
            self.assertFalse(res["configured"])
            self.assertFalse(res["connected"])
            self.assertTrue(any("No database URL found" in i for i in res["issues"]))

    def test_placeholder_url_detected_without_crash(self):
        placeholder_url = "postgresql://postgres.projectref:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
        res = run_database_diagnostic(placeholder_url)
        self.assertEqual(res["status"], "FAIL")
        self.assertEqual(res["placeholder_detected"], "projectref")
        self.assertFalse(res["connected"])
        self.assertTrue(any("Placeholder token 'projectref' detected" in i for i in res["issues"]))

    def test_sqlite_fallback_connectivity_and_tables(self):
        class LocalTestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

        app = create_app(config_class=LocalTestConfig)
        with app.app_context():
            db.create_all()
            res = run_database_diagnostic("sqlite:///:memory:")
            self.assertTrue(res["connected"])
            self.assertTrue(res["is_sqlite"])


class AlembicIsolationTests(unittest.TestCase):
    """Verify that Alembic migrations strictly target refurbishment schema."""

    def test_include_object_only_includes_refurbishment_schema(self):
        mock_refurb_table = MagicMock()
        mock_refurb_table.schema = "refurbishment"
        self.assertTrue(include_object(mock_refurb_table, "devices", "table", False, None))

        mock_public_table = MagicMock()
        mock_public_table.schema = "public"
        self.assertFalse(include_object(mock_public_table, "users", "table", False, None))

        mock_collection_table = MagicMock()
        mock_collection_table.schema = "collection"
        self.assertFalse(include_object(mock_collection_table, "pickups", "table", False, None))

        mock_non_table = MagicMock()
        self.assertTrue(include_object(mock_non_table, "some_col", "column", False, None))


if __name__ == "__main__":
    unittest.main()

