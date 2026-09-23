"""Testes que atravessam vários módulos/bancos legados.

Estes testes não exercitam diretamente o Worker de produção.
"""

"""Contratos entre API, bancos separados e a vitrine pública."""

import http.client
import json
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from app.db import get_connection
from app.seed import DEV_PASSWORD, seed_all
from app.server import create_server


class SplitApiContractTest(unittest.TestCase):
    """Exercita os fluxos que cruzam contas, catálogo e ofertas."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.paths = {
            name: root / f"{name}.db"
            for name in ("cards", "accounts", "listings")
        }
        seed_all(cls.paths, reset=True)
        cls.server = create_server("127.0.0.1", 0, db_paths=cls.paths)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def setUp(self):
        self.cookie = None
        self.csrf = None

    def request(self, method, path, payload=None, csrf=None):
        """Faz uma requisição HTTP e devolve status e JSON."""

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if body else {}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if csrf:
            headers["X-CSRF-Token"] = csrf

        connection.request(method, path, body, headers)
        response = connection.getresponse()
        raw = response.read()
        cookie = response.getheader("Set-Cookie")
        if cookie:
            self.cookie = cookie.split(";", 1)[0]
        status = response.status
        connection.close()
        return status, json.loads(raw)

    def login_demo(self):
        status, payload = self.request(
            "POST",
            "/api/auth/login",
            {"identifier": "danton", "password": DEV_PASSWORD},
        )
        self.assertEqual(status, 200)
        self.csrf = payload["csrf_token"]

    def test_listing_contact_and_language_round_trip(self):
        """Oferta usa o idioma da impressão mesmo com bancos separados."""

        self.login_demo()
        contact = "https://example.com/contato/pt"

        with closing(get_connection(self.paths["cards"])) as connection:
            cursor = connection.execute(
                """
                INSERT INTO cards(
                    scryfall_id,
                    oracle_id,
                    name,
                    set_code,
                    set_name,
                    collector_number,
                    language,
                    rarity,
                    image_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "split-pt-print",
                    "split-language-oracle",
                    "Carta Split PT",
                    "tst",
                    "Teste",
                    "77",
                    "pt",
                    "common",
                    "https://example.test/split-card.jpg",
                ),
            )
            card_id = cursor.lastrowid
            connection.commit()

        status, created = self.request(
            "POST",
            "/api/listings",
            {
                "card_id": card_id,
                "title": "Impressão em português",
                "description": "Edição brasileira, bem conservada.",
                "price_cents": 2500,
                "condition": "NM",
                # Deve ser ignorado: o idioma pertence à impressão.
                "language": "en",
                "mode": "venda",
                "contact_url": contact,
            },
            csrf=self.csrf,
        )
        self.assertEqual(status, 201)

        try:
            status, payload = self.request(
                "GET",
                f"/api/listings?lang=pt&limit=20&page=1",
            )
            self.assertEqual(status, 200)
            found = next(
                item
                for item in payload["listings"]
                if item["id"] == created["id"]
            )
            self.assertEqual(found["contact_url"], contact)
            self.assertEqual(found["language"], "pt")
            self.assertEqual(
                found["description"],
                "Edição brasileira, bem conservada.",
            )

            with closing(get_connection(self.paths["listings"])) as connection:
                row = connection.execute(
                    "SELECT contact_url, language FROM listings WHERE id = ?",
                    (created["id"],),
                ).fetchone()
            self.assertEqual(tuple(row), (contact, "pt"))
        finally:
            with closing(get_connection(self.paths["listings"])) as connection:
                connection.execute(
                    "DELETE FROM listings WHERE id = ?",
                    (created["id"],),
                )
                connection.commit()
            with closing(get_connection(self.paths["cards"])) as connection:
                connection.execute(
                    "DELETE FROM cards WHERE id = ?",
                    (card_id,),
                )
                connection.commit()

    def test_listing_pagination_contract_in_split_mode(self):
        """Páginas têm tamanho estável e cobrem todas as ofertas uma vez."""

        limit = 2
        page = 1
        seen = []
        total = None
        while True:
            status, payload = self.request(
                "GET",
                f"/api/listings?page={page}&limit={limit}",
            )
            self.assertEqual(status, 200)
            self.assertEqual(payload["page"], page)
            self.assertEqual(payload["limit"], limit)
            if total is None:
                total = payload["total"]
            self.assertEqual(payload["total"], total)
            batch = [item["id"] for item in payload["listings"]]
            self.assertLessEqual(len(batch), limit)
            self.assertFalse(set(seen).intersection(batch))
            seen.extend(batch)
            if len(seen) >= total:
                break
            page += 1

        with closing(get_connection(self.paths["listings"])) as connection:
            expected = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM listings ORDER BY created_at DESC, id DESC"
                )
            ]
        self.assertEqual(set(seen), set(expected))
        self.assertEqual(len(seen), len(expected))

    def test_wants_and_matches_work_across_split_databases(self):
        """Desejos cruzam listings, cards e accounts nos três bancos."""

        self.login_demo()

        status, initial = self.request("GET", "/api/matches")
        self.assertEqual(status, 200)
        self.assertTrue(
            any(item["wanted_name"] == "Rhystic Study" for item in initial["matches"])
        )

        status, created = self.request(
            "POST",
            "/api/wants",
            {
                "card_id": 4,
                "max_price_cents": 1000,
                "desired_condition": "NM",
                "mode": "compra",
            },
            csrf=self.csrf,
        )
        self.assertEqual(status, 201)

        status, matches = self.request("GET", "/api/matches")
        self.assertEqual(status, 200)
        self.assertTrue(
            any(
                item["want_id"] == created["id"]
                and item["name"] == "Counterspell"
                for item in matches["matches"]
            )
        )

    def test_public_profile_crosses_accounts_cards_and_listings(self):
        """Perfil público cruza os três bancos e expõe celular opcional."""

        with closing(get_connection(self.paths["accounts"])) as connection:
            connection.execute(
                "UPDATE users SET phone = ? WHERE id = 2",
                ("85999990000",),
            )
            connection.commit()

        status, profile = self.request("GET", "/api/users/2")
        self.assertEqual(status, 200)
        self.assertEqual(profile["user"]["username"], "marina")
        self.assertEqual(profile["user"]["state"], "CE")
        self.assertEqual(profile["user"]["phone"], "85999990000")
        self.assertTrue(profile["listings"])
        self.assertTrue(
            all(item["user_id"] == 2 for item in profile["listings"])
        )

        with closing(get_connection(self.paths["accounts"])) as connection:
            connection.execute("UPDATE users SET phone = NULL WHERE id = 2")
            connection.commit()

    def test_contact_url_over_limit_is_rejected(self):
        """A API não grava uma URL válida parcialmente truncada."""

        self.login_demo()
        oversized = "https://example.com/" + ("a" * 300)
        status, payload = self.request(
            "POST",
            "/api/listings",
            {
                "card_id": 2,
                "title": "Oferta longa",
                "condition": "NM",
                "mode": "venda",
                "contact_url": oversized,
            },
            csrf=self.csrf,
        )
        self.assertEqual(status, 400)
        self.assertIn("300", payload["error"])


if __name__ == "__main__":
    unittest.main()
