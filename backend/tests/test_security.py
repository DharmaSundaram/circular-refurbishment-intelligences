import unittest
from config import Config
from extensions import db
from services.file_service import save_local_file, get_local_file_path
from app import create_app


class SecurityTests(unittest.TestCase):
    def setUp(self):
        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

        self.app = create_app(config_class=TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_path_traversal_prevention(self):
        # Attempt traversal via storage key
        path = get_local_file_path("../../app.py")
        self.assertIsNone(path)

        path2 = get_local_file_path("..\\..\\config.py")
        self.assertIsNone(path2)

    def test_safe_local_file_creation(self):
        content = b"sample diagnostic log content"
        f = save_local_file(
            device_id="DEV-SEC-01",
            original_filename="../../../unsafe_name.txt",
            file_bytes=content,
            is_private=True,
        )
        self.assertNotIn("..", f.storage_key)
        self.assertTrue(f.is_private)
        self.assertEqual(f.file_size, len(content))

    def test_unknown_routes_sanitization(self):
        # Must return generic 404 without leaking traceback
        resp = self.client.get("/api/v1/nonexistent/secret_path")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
