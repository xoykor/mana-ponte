import tempfile
import unittest
from pathlib import Path

from app.db import get_connection
from app.seed import seed_all


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.db"
        seed_all(self.db, reset=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_schema_and_seed(self):
        with get_connection(self.db) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"cards", "users", "listings", "wants"}.issubset(tables))
            self.assertGreaterEqual(conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 12)
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0], 0)

    def test_seed_is_idempotent(self):
        seed_all(self.db)
        with get_connection(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 12)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0], 6)
