"""Testes de normalização, importação e busca remota do catálogo."""

import io
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.catalog import import_file, normalize_card, search_scryfall
from app.db import get_connection


class CatalogTest(unittest.TestCase):
    """Verifica as operações que transformam dados de cartas."""

    def test_normalizes_double_faced_and_rejects_digital(self):
        """Cartas físicas são aceitas, inclusive quando têm duas faces."""

        card = {
            "id": "abc",
            "oracle_id": "oracle",
            "name": "Delver // Insect",
            "printed_name": "Investigador // Inseto",
            "set": "mid",
            "set_name": "Innistrad: Midnight Hunt",
            "collector_number": "47",
            "lang": "pt",
            "rarity": "uncommon",
            "games": ["paper"],
            "card_faces": [
                {"image_uris": {"normal": "https://img.test/card.jpg"}}
            ],
        }

        normalized = normalize_card(card)
        self.assertEqual(normalized[3], "Investigador // Inseto")
        self.assertEqual(normalized[-1], "https://img.test/card.jpg")

        # O catálogo da aplicação é de cartas de papel, não de cartas digitais.
        card["digital"] = True
        self.assertIsNone(normalize_card(card))

    def test_import_file_upserts_offline(self):
        """Importar o mesmo arquivo duas vezes continua idempotente."""

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "cards.json"
            db = root / "catalog.db"

            source.write_text(
                json.dumps(
                    [
                        {
                            "id": "id-1",
                            "oracle_id": "o-1",
                            "name": "Sol Ring",
                            "printed_name": "Anel Solar",
                            "set": "cmm",
                            "set_name": "Commander Masters",
                            "collector_number": "396",
                            "lang": "en",
                            "rarity": "uncommon",
                            "games": ["paper"],
                            "image_uris": {
                                "normal": "https://img.test/sol.jpg"
                            },
                        },
                        {
                            "id": "arena",
                            "name": "Digital",
                            "set": "ana",
                            "set_name": "Arena",
                            "collector_number": "1",
                            "digital": True,
                            "games": ["arena"],
                        },
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(import_file(source, db, batch_size=1), 1)

            with closing(get_connection(db)) as conn:
                stable_id = conn.execute(
                    "SELECT id FROM cards WHERE scryfall_id = 'id-1'"
                ).fetchone()[0]

            # Uma atualização do mesmo bulk preserva a chave local usada por
            # listings e altera apenas os metadados da impressão.
            updated = json.loads(source.read_text(encoding="utf-8"))
            updated[0]["name"] = "Sol Ring atualizado"
            source.write_text(json.dumps(updated), encoding="utf-8")
            self.assertEqual(import_file(source, db, batch_size=1), 1)

            with closing(get_connection(db)) as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
                    1,
                )
                row = conn.execute(
                    "SELECT id, name, printed_name FROM cards "
                    "WHERE scryfall_id = 'id-1'"
                ).fetchone()
                self.assertEqual(row[0], stable_id)
                self.assertEqual(row[1], "Sol Ring atualizado")
                self.assertEqual(row[2], "Anel Solar")

    def test_search_scryfall_follows_all_result_pages(self):
        """A busca remota percorre as páginas seguintes do Scryfall."""

        def card(card_id, name):
            """Cria uma carta mínima para cada resposta simulada."""

            return {
                "id": card_id,
                "oracle_id": f"oracle-{card_id}",
                "name": name,
                "set": "tst",
                "set_name": "Test Set",
                "collector_number": card_id,
                "lang": "en",
                "rarity": "common",
                "games": ["paper"],
                "image_uris": {
                    "normal": f"https://img.test/{card_id}.jpg"
                },
            }

        first_page = io.BytesIO(
            json.dumps(
                {
                    "data": [card("page-1", "Mountain")],
                    "has_more": True,
                    "next_page": (
                        "https://api.scryfall.test/cards/search?page=2"
                    ),
                }
            ).encode()
        )
        second_page = io.BytesIO(
            json.dumps(
                {
                    "data": [card("page-2", "Mountain")],
                    "has_more": False,
                }
            ).encode()
        )

        # Cada objeto BytesIO representa uma resposta HTTP consecutiva.
        with patch(
            "app.catalog.urlopen",
            side_effect=[first_page, second_page],
        ) as request:
            rows = search_scryfall("Mountain")

        self.assertEqual([row[0] for row in rows], ["page-1", "page-2"])
        self.assertEqual(request.call_count, 2)
        first_request = request.call_args_list[0].args[0]
        self.assertIn("include_multilingual=true", first_request.full_url)
