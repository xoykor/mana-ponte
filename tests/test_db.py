"""Testes de schema, migração e inicialização dos bancos SQLite.

A suíte testa o backend Python legado/local, não o Worker de produção.
"""

"""Testes do schema SQLite e das migrações compatíveis."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.db import get_connection, init_db
from app.seed import seed_all


class DatabaseTest(unittest.TestCase):
    """Verifica inicialização, seed e migração de bancos antigos."""

    def setUp(self):
        # O seed cria o schema atual e alguns dados conhecidos para os testes.
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.db"
        seed_all(self.db, reset=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_schema_seed_and_idempotence(self):
        """Executar o seed novamente não duplica cartas ou ofertas."""

        seed_all(self.db)

        with closing(get_connection(self.db)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

            expected_tables = {"cards", "users", "listings", "wants", "sessions"}
            self.assertTrue(expected_tables.issubset(tables))
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
                12,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0],
                6,
            )

            # O SQLite não encontrou referências estrangeiras quebradas.
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_migrates_legacy_users_without_data_loss(self):
        """A migração adiciona colunas novas e preserva o usuário antigo."""

        legacy = Path(self.temp.name) / "legacy.db"
        conn = sqlite3.connect(legacy)
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                city TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO users (
                id, username, email, display_name, city, state
            ) VALUES (
                7, 'legacy', 'legacy@example.com', 'Legacy User', 'Natal', 'RN'
            );
            """
        )
        conn.commit()
        conn.close()

        # init_db reconhece o banco antigo e aplica a migração necessária.
        init_db(legacy)

        with closing(get_connection(legacy)) as migrated:
            columns = {
                row["name"]
                for row in migrated.execute("PRAGMA table_info(users)")
            }

            self.assertTrue(
                {"password_hash", "email_verified", "updated_at", "phone"}.issubset(
                    columns
                )
            )
            self.assertEqual(
                migrated.execute(
                    "SELECT username FROM users WHERE id = 7"
                ).fetchone()[0],
                "legacy",
            )
            self.assertEqual(
                migrated.execute(
                    "SELECT MAX(version) FROM schema_version"
                ).fetchone()[0],
                5,
            )

    def test_migrates_cards_printed_name(self):
        """Banco antigo recebe nome impresso sem perder cartas existentes."""

        legacy = Path(self.temp.name) / "cards-legacy.db"
        with closing(get_connection(legacy)) as connection:
            connection.executescript(
                """
                CREATE TABLE schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO schema_version(version) VALUES (1);

                CREATE TABLE cards (
                    id INTEGER PRIMARY KEY,
                    scryfall_id TEXT NOT NULL UNIQUE,
                    oracle_id TEXT,
                    name TEXT NOT NULL,
                    set_code TEXT NOT NULL,
                    set_name TEXT NOT NULL,
                    collector_number TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'en',
                    rarity TEXT NOT NULL DEFAULT 'common',
                    image_url TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO cards(
                    scryfall_id, name, set_code, set_name, collector_number
                ) VALUES ('legacy-card', 'Test Card', 'tst', 'Teste', '1');
                """
            )
            connection.commit()

        init_db(legacy)

        with closing(get_connection(legacy)) as migrated:
            columns = {
                row["name"]
                for row in migrated.execute("PRAGMA table_info(cards)")
            }
            self.assertIn("printed_name", columns)
            self.assertEqual(
                migrated.execute(
                    "SELECT name FROM cards WHERE scryfall_id = 'legacy-card'"
                ).fetchone()[0],
                "Test Card",
            )

    def test_migrates_marketplace_desired_language(self):
        """Banco antigo recebe idioma desejado sem perder anúncios."""

        legacy = Path(self.temp.name) / "marketplace-legacy.db"
        seed_all(legacy, reset=True)

        with closing(get_connection(legacy)) as connection:
            connection.execute(
                """
                CREATE TABLE wants_old AS
                SELECT id, card_id, user_id, max_price_cents,
                       desired_condition, mode, created_at
                FROM wants
                """
            )
            connection.execute("DROP TABLE wants")
            connection.execute("ALTER TABLE wants_old RENAME TO wants")
            connection.commit()

        init_db(legacy)

        with closing(get_connection(legacy)) as migrated:
            want_columns = {
                row["name"]
                for row in migrated.execute("PRAGMA table_info(wants)")
            }
            self.assertIn("desired_language", want_columns)
            self.assertEqual(
                migrated.execute(
                    "SELECT COUNT(*) FROM listings"
                ).fetchone()[0],
                6,
            )
            self.assertEqual(
                migrated.execute(
                    "SELECT MAX(version) FROM schema_version"
                ).fetchone()[0],
                5,
            )
