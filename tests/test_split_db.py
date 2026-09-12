"""Testes do armazenamento separado do catálogo, contas e ofertas."""

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.db import get_connection, get_listings_app_connection
from app.seed import seed_all


class SplitDatabaseTest(unittest.TestCase):
    """Garante que a configuração nova mantém os domínios isolados."""

    def test_seed_and_cross_database_listing_query(self):
        """O seed separa tabelas e a conexão de ofertas faz o join necessário."""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = {
                name: root / f"{name}.db"
                for name in ("cards", "accounts", "listings")
            }

            seed_all(paths, reset=True)
            seed_all(paths)

            with closing(get_connection(paths["cards"])) as cards:
                self.assertEqual(
                    cards.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
                    12,
                )
                self.assertIsNone(
                    cards.execute(
                        "SELECT 1 FROM sqlite_master WHERE name = 'users'"
                    ).fetchone()
                )

            with closing(get_connection(paths["accounts"])) as accounts:
                self.assertEqual(
                    accounts.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                    4,
                )

            with closing(
                get_listings_app_connection(
                    paths["listings"],
                    paths["cards"],
                    paths["accounts"],
                )
            ) as listings:
                total = listings.execute(
                    """
                    SELECT COUNT(*)
                    FROM listings AS l
                    JOIN catalog.cards AS c ON c.id = l.card_id
                    JOIN accounts.users AS u ON u.id = l.user_id
                    """
                ).fetchone()[0]
                self.assertEqual(total, 6)


if __name__ == "__main__":
    unittest.main()
