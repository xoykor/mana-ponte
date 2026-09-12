"""Testes do cache de busca remota: limite, evicção e deduplicação em voo."""

import threading
import time as _time
import unittest
from unittest.mock import patch

import app.server as server_module


class RemoteCacheTest(unittest.TestCase):
    """Cache limitado, evicção por idade e deduplicação concorrente."""

    def setUp(self):
        server_module.REMOTE_CARD_CACHE.clear()
        server_module.REMOTE_CARD_CACHE_AGE.clear()
        server_module.REMOTE_CARD_CACHE_PENDING.clear()

    def tearDown(self):
        server_module.REMOTE_CARD_CACHE.clear()
        server_module.REMOTE_CARD_CACHE_AGE.clear()
        server_module.REMOTE_CARD_CACHE_PENDING.clear()

    def test_cache_is_bounded_and_evicts_oldest(self):
        limit = server_module.REMOTE_CARD_CACHE_MAX_ENTRIES
        keys = [(str(i), "", "") for i in range(limit + 5)]
        for index, key in enumerate(keys):
            server_module.REMOTE_CARD_CACHE[key] = (9e18, [])
            server_module.REMOTE_CARD_CACHE_AGE[key] = float(index)
        server_module._remote_evict_oldest()
        self.assertEqual(len(server_module.REMOTE_CARD_CACHE), limit)
        self.assertNotIn(keys[0], server_module.REMOTE_CARD_CACHE)
        self.assertIn(keys[-1], server_module.REMOTE_CARD_CACHE)

    def test_cached_hit_returns_stored_result(self):
        key = ("dragon", "", "")
        payload = [("id-1",)]
        server_module.REMOTE_CARD_CACHE[key] = (_time.monotonic() + 999, payload)
        server_module.REMOTE_CARD_CACHE_AGE[key] = _time.monotonic()
        self.assertEqual(server_module.remote_cards("dragon", "", ""), payload)

    def test_concurrent_identical_queries_fetch_once(self):
        counter = {"n": 0}
        lock = threading.Lock()

        def slow(query, set_code=None, language=None):
            with lock:
                counter["n"] += 1
            _time.sleep(0.2)
            return [("c", "x")]

        with patch("app.server.search_scryfall", side_effect=slow):
            results = []
            barrier = threading.Barrier(8)

            def worker():
                barrier.wait()
                r = server_module.remote_cards("Dragon", "", "")
                with lock:
                    results.append(r)

            threads = [
                threading.Thread(target=worker, daemon=True) for _ in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

        self.assertEqual(counter["n"], 1)
        self.assertEqual(len(results), 8)

    def test_failed_fetch_releases_waiters(self):
        counter = {"n": 0}
        lock = threading.Lock()

        def failing(query, set_code=None, language=None):
            with lock:
                counter["n"] += 1
            _time.sleep(0.1)
            raise RuntimeError("offline")

        with patch("app.server.search_scryfall", side_effect=failing):
            results = []
            barrier = threading.Barrier(8)

            def worker():
                barrier.wait()
                r = server_module.remote_cards("Dragon", "", "")
                with lock:
                    results.append(r)

            threads = [
                threading.Thread(target=worker, daemon=True) for _ in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

        self.assertEqual(counter["n"], 1)
        self.assertEqual(len(results), 8)
        self.assertTrue(all(result == [] for result in results))
        self.assertNotIn(("dragon", "", ""), server_module.REMOTE_CARD_CACHE_PENDING)

    def test_expired_entry_is_refetched(self):
        key = ("dragon", "", "")
        server_module.REMOTE_CARD_CACHE[key] = (_time.monotonic() - 1, [("stale",)])
        server_module.REMOTE_CARD_CACHE_AGE[key] = _time.monotonic() - 2

        fresh = [("fresh",)]
        with patch("app.server.search_scryfall", return_value=fresh) as remote:
            self.assertEqual(server_module.remote_cards("Dragon", "", ""), fresh)

        remote.assert_called_once_with("Dragon", "", "")
        self.assertEqual(server_module.REMOTE_CARD_CACHE[key][1], fresh)

    def test_waiter_timeout_releases_expired_pending_event(self):
        key = ("dragon", "", "")
        server_module.REMOTE_CARD_CACHE_PENDING[key] = threading.Event()

        with patch.object(server_module, "REMOTE_CARD_CACHE_TTL", 0.01):
            with patch("app.server.search_scryfall") as remote:
                self.assertEqual(server_module.remote_cards("Dragon", "", ""), [])

        remote.assert_not_called()
        self.assertNotIn(key, server_module.REMOTE_CARD_CACHE_PENDING)

    def test_contact_url_accepts_empty_http_and_https_only(self):
        accepted = (
            None,
            "",
            "  ",
            "http://localhost:8000/contact",
            "https://example.com/u",
        )
        rejected = (
            "javascript:alert(1)",
            "data:text/html,hello",
            "ftp://example.com/contact",
            "//example.com/contact",
            "https://",
            "https://%20/",
            "https://example.com:bad",
            "https://example.com\\@evil.example",
        )

        for value in accepted:
            with self.subTest(value=value):
                self.assertTrue(server_module.valid_contact_url(value))
        for value in rejected:
            with self.subTest(value=value):
                self.assertFalse(server_module.valid_contact_url(value))


if __name__ == "__main__":
    unittest.main()
