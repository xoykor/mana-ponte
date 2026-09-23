"""Testes de paginação dos anúncios.

Estes testes não exercitam diretamente o Worker de produção.
"""

"""Valida paginacao de ofertas (Etapa 3 item 6)."""

import http.client
import json
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from app.db import get_connection, init_listings_db
from app.seed import DEV_PASSWORD, seed_all
from app.server import create_server


class ListingsPaginationTest(unittest.TestCase):
    """Paginacao limita resultados e nao perde nem repete ofertas."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        db_path = Path(cls.temp.name) / "listings.db"
        seed_all(db_path, reset=True)
        with closing(get_connection(db_path)) as conn:
            card_ids = [r[0] for r in conn.execute("SELECT id FROM cards ORDER BY id LIMIT 5").fetchall()]
            uid = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
        created = ["2026-01-01T00:00:%d:00Z" % i for i in range(5)]
        titles = ["Card " + str(i) for i in range(5)]
        with closing(get_connection(db_path)) as conn:
            conn.executemany(
                "INSERT INTO listings (card_id, user_id, title, description, condition, mode) VALUES (?, ?, ?, ?, ?, ?)",
                [(card_ids[i], uid, titles[i], "desc", "NM", "venda") for i in range(5)],
            )
        with closing(get_connection(db_path)) as conn:
            cls.total_count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        cls.limit = 2
        cls.server = create_server("127.0.0.1", 0, db_path)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def request(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        return resp.status, body

    def test_pagination_limits_and_keeps_total(self):
        limit = self.limit
        pages = []
        seen = set()
        page = 1
        while True:
            status, body = self.request("/api/listings?page=%d&limit=%d" % (page, limit))
            self.assertEqual(status, 200)
            self.assertEqual(body["total"], self.total_count)
            self.assertEqual(body["page"], page)
            batch = [l["id"] for l in body["listings"]]
            self.assertLessEqual(len(batch), limit)
            self.assertFalse(seen.intersection(set(batch)), "overlap entre paginas")
            seen |= set(batch)
            pages.append(body)
            if len(batch) < limit or not batch:
                break
            page += 1
        self.assertEqual(len(seen), self.total_count)
        ids = sorted(seen)
        with closing(get_connection(self.temp.name + "/listings.db")) as conn:
            db_ids = [r[0] for r in conn.execute("SELECT id FROM listings ORDER BY id").fetchall()]
        self.assertEqual(ids, db_ids)


if __name__ == "__main__":
    unittest.main()
