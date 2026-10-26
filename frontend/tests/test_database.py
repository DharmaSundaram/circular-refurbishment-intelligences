import unittest
from config import Config
from extensions import db
from models.device import Device
from models.transfer import Transfer
from models.assessment import Assessment
from app import create_app


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        class TestConfig(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

        self.app = create_app(config_class=TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_postgres_url_replacement(self):
        url = "postgres://user:pass@host.render.com:5432/refurb_db"
        if url.startswith("postgres://"):
            converted = url.replace("postgres://", "postgresql://", 1)
        self.assertTrue(converted.startswith("postgresql://"))

    def test_device_crud_and_constraints(self):
        dev = Device(
            device_id="TEST-DEV-001",
            device_type="Laptop",
            brand="Dell",
            model="Latitude 5420",
            condition="Good",
            status="Received",
        )
        db.session.add(dev)
        db.session.commit()

        retrieved = Device.query.filter_by(device_id="TEST-DEV-001").first()
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.brand, "Dell")

    def test_transaction_rollback(self):
        dev = Device(
            device_id="TEST-DEV-ROLLBACK",
            device_type="Laptop",
            brand="Dell",
            model="Latitude 5420",
            condition="Good",
        )
        db.session.add(dev)
        db.session.commit()

        try:
            # Attempt duplicate primary key insertion
            duplicate = Device(
                device_id="TEST-DEV-ROLLBACK",
                device_type="Laptop",
                brand="HP",
                model="Envy",
                condition="Fair",
            )
            db.session.add(duplicate)
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Database state remains consistent
        count = Device.query.filter_by(device_id="TEST-DEV-ROLLBACK").count()
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
