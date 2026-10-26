import tempfile
import unittest
from pathlib import Path

from app import create_app


class FlaskAppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.dist = Path(self.directory.name)
        (self.dist / "assets").mkdir()
        (self.dist / "index.html").write_text("<html>Unchanged UI</html>")
        (self.dist / "assets" / "app-test.js").write_text("console.log('UI')")
        self.client = create_app(self.dist).test_client()

    def test_serves_exact_html(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"<html>Unchanged UI</html>")
        self.assertEqual(response.headers["Cache-Control"], "no-cache")

    def test_serves_built_assets(self):
        response = self.client.get("/assets/app-test.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"console.log('UI')")
        self.assertIn("immutable", response.headers["Cache-Control"])

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ui_build_available"])

    def test_missing_build(self):
        (self.dist / "index.html").unlink()
        self.assertEqual(self.client.get("/").status_code, 503)

    def test_missing_files_and_unknown_api_routes(self):
        for path in ["/assets/missing.js", "/api/devices", "/app.py", "/../app.py"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
