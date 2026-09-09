import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.db import get_connection, init_db
from app.seed import seed_all


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.db=Path(self.temp.name)/"test.db"; seed_all(self.db,reset=True)
    def tearDown(self): self.temp.cleanup()

    def test_schema_seed_and_idempotence(self):
        seed_all(self.db)
        with closing(get_connection(self.db)) as conn:
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"cards","users","listings","wants","sessions"}.issubset(tables))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0],12)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0],6)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_migrates_legacy_users_without_data_loss(self):
        legacy=Path(self.temp.name)/"legacy.db"
        conn=sqlite3.connect(legacy)
        conn.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,email TEXT UNIQUE NOT NULL,display_name TEXT NOT NULL,city TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP); INSERT INTO users(id,username,email,display_name,city,state) VALUES(7,'legacy','legacy@example.com','Legacy User','Natal','RN');""")
        conn.commit(); conn.close(); init_db(legacy)
        with closing(get_connection(legacy)) as migrated:
            columns={r["name"] for r in migrated.execute("PRAGMA table_info(users)")}
            self.assertTrue({"password_hash","email_verified","updated_at"}.issubset(columns))
            self.assertEqual(migrated.execute("SELECT username FROM users WHERE id=7").fetchone()[0],"legacy")
            self.assertEqual(migrated.execute("SELECT MAX(version) FROM schema_version").fetchone()[0],2)
