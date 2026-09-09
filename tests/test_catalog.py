import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.catalog import import_file, normalize_card
from app.db import get_connection


class CatalogTest(unittest.TestCase):
    def test_normalizes_double_faced_and_rejects_digital(self):
        card = {"id":"abc","oracle_id":"oracle","name":"Delver // Insect","set":"mid",
                "set_name":"Innistrad: Midnight Hunt","collector_number":"47","lang":"pt",
                "rarity":"uncommon","games":["paper"],"card_faces":[{"image_uris":{"normal":"https://img.test/card.jpg"}}]}
        self.assertEqual(normalize_card(card)[-1], "https://img.test/card.jpg")
        card["digital"] = True
        self.assertIsNone(normalize_card(card))

    def test_import_file_upserts_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / "cards.json"; db = root / "catalog.db"
            source.write_text(json.dumps([{"id":"id-1","oracle_id":"o-1","name":"Sol Ring",
                "set":"cmm","set_name":"Commander Masters","collector_number":"396","lang":"en",
                "rarity":"uncommon","games":["paper"],"image_uris":{"normal":"https://img.test/sol.jpg"}},
                {"id":"arena","name":"Digital","set":"ana","set_name":"Arena","collector_number":"1",
                 "digital":True,"games":["arena"]}]), encoding="utf-8")
            self.assertEqual(import_file(source, db, batch_size=1), 1)
            self.assertEqual(import_file(source, db, batch_size=1), 1)
            with closing(get_connection(db)) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 1)
