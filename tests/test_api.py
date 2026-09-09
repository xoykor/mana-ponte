import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from app.seed import seed_all
from app.server import create_server


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.db = Path(cls.temp.name) / "api.db"
        seed_all(cls.db, reset=True)
        cls.server = create_server("127.0.0.1", 0, cls.db)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2); cls.temp.cleanup()

    def request(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type":"application/json"} if body else {}
        conn.request(method, path, body, headers); response = conn.getresponse(); raw = response.read()
        result = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
        conn.close(); return response.status, result

    def test_health_home_and_filters(self):
        status, health = self.request("GET", "/api/health")
        self.assertEqual((status, health["status"]), (200, "ok"))
        status, home = self.request("GET", "/")
        self.assertEqual(status, 200); self.assertIn(b"ManaPonte", home)
        status, result = self.request("GET", "/api/cards?q=Sol&set=cmm&limit=1")
        self.assertEqual(status, 200); self.assertEqual(result["total"], 1)
        status, result = self.request("GET", "/api/listings?state=RN&mode=troca")
        self.assertEqual(status, 200); self.assertEqual(result["total"], 1)

    def test_create_listing_and_validation(self):
        _, cards = self.request("GET", "/api/cards?q=Black%20Lotus")
        payload = {"card_id":cards["cards"][0]["id"],"user_id":1,"title":"Procuro propostas",
                   "condition":"NM","mode":"ambos","price_cents":100}
        status, result = self.request("POST", "/api/listings", payload)
        self.assertEqual(status, 201); self.assertIn("id", result)
        status, _ = self.request("POST", "/api/listings", {"card_id":1})
        self.assertEqual(status, 400)

    def test_matches_requires_card(self):
        status, _ = self.request("GET", "/api/matches")
        self.assertEqual(status, 400)
