"""Testes dos formatos aceitos pelos importadores de catálogo.

A suíte testa o backend Python legado/local, não o Worker de produção.
"""

"""Valida as correcoes de importacao do catalogo (Etapa 2)."""

import gzip
import json
import tempfile
import unittest
from builtins import open as builtin_open
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.catalog import import_file, image_url
from app.db import get_connection


class ImportFixturesTest(unittest.TestCase):
    """Formatos, contagens e idempotencia da importacao."""

    def _write(self, root, name, text, binary=False):
        root.mkdir(parents=True, exist_ok=True)
        path = Path(root) / name
        if binary:
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def test_array_json_imports_only_paper_cards(self):
        with tempfile.TemporaryDirectory() as _tmp:
            root = Path(_tmp)
            src = self._write(root, "cards.json", json.dumps([
                {"id": "a", "name": "X", "set": "cmm", "set_name": "CM",
                 "collector_number": "1", "games": ["paper"],
                 "image_uris": {"normal": "https://img.test/a.jpg"}},
                {"id": "arena", "name": "Digital", "set": "ana", "set_name": "Arena",
                 "collector_number": "1", "digital": True, "games": ["arena"]},
            ]))
            db = Path(root) / "c.db"
            n = import_file(src, db, batch_size=1)
            self.assertEqual(n, 1)
            with closing(get_connection(db)) as conn:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
                    1,
                )

    def test_gzip_jsonl_streams_without_loading_whole_file(self):
        with tempfile.TemporaryDirectory() as _tmp:
            root = Path(_tmp)
            lines = []
            for i in range(3):
                obj = {"id": f"g{i}", "name": f"Card {i}", "set": "cmm",
                       "set_name": "CM", "collector_number": str(i), "games": ["paper"]}
                lines.append(json.dumps(obj))
            payload = "\n".join(lines) + "\n"
            gz = gzip.compress(payload.encode("utf-8"))
            src = self._write(root, "cards.jsonl.gz", gz, binary=True)
            db = Path(root) / "c.db"
            n = import_file(src, db)
            self.assertEqual(n, 3)

    def test_compressed_array_imports_cards(self):
        with tempfile.TemporaryDirectory() as _tmp:
            root = Path(_tmp)
            arr = json.dumps([
                {"id": "z", "name": "Z", "set": "cmm",
                 "set_name": "CM", "collector_number": "1", "games": ["paper"]},
            ])
            gz = gzip.compress(arr.encode("utf-8"))
            src = self._write(root, "cards.jsonl.gz", gz, binary=True)
            db = Path(root) / "c.db"
            n = import_file(src, db)
            self.assertEqual(n, 1)
            with closing(get_connection(db)) as conn:
                self.assertEqual(
                    conn.execute("SELECT scryfall_id FROM cards").fetchone()[0],
                    "z",
                )

    def test_plain_jsonl_is_read_incrementally(self):
        """A JSONL file is iterated line by line without a whole-file read."""

        class NoWholeRead:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.wrapped.__exit__(*args)

            def __iter__(self):
                return self

            def __next__(self):
                return next(self.wrapped)

            def read(self, *args, **kwargs):
                raise AssertionError("JSONL não deve usar read()")

        with tempfile.TemporaryDirectory() as _tmp:
            root = Path(_tmp)
            lines = [
                json.dumps({"id": f"p{i}", "name": f"Plain {i}", "set": "cmm",
                            "set_name": "CM", "collector_number": str(i),
                            "games": ["paper"]})
                for i in range(3)
            ]
            src = self._write(root, "cards.jsonl", "\n".join(lines) + "\n")
            db = Path(root) / "c.db"

            def tracked_open(*args, **kwargs):
                return NoWholeRead(builtin_open(*args, **kwargs))

            with patch("app.catalog.Path.read_bytes", side_effect=AssertionError), \
                    patch("app.catalog.open", side_effect=tracked_open):
                self.assertEqual(import_file(src, db), 3)

    def test_invalid_lines_are_reported(self):
        with tempfile.TemporaryDirectory() as _tmp:
            root = Path(_tmp)
            text = "\n".join([
                json.dumps({"id": "ok", "name": "OK", "set": "cmm",
                            "set_name": "CM", "collector_number": "1", "games": ["paper"]}),
                "{not valid json",
                "",
                "   ",
            ]) + "\n"
            src = self._write(root, "cards.jsonl", text)
            db = Path(root) / "c.db"
            report = StringIO()
            with redirect_stdout(report):
                n = import_file(src, db)
            self.assertEqual(n, 1)
            self.assertIn("ignoradas: 3", report.getvalue())
            self.assertIn("invalidas: 1", report.getvalue())

    def test_image_url_prefers_normal_then_variants(self):
        card_normal = {"image_uris": {"normal": "https://img.test/n.jpg",
                                      "small": "https://img.test/s.jpg"}}
        self.assertEqual(image_url(card_normal), "https://img.test/n.jpg")
        card_faceonly = {
            "card_faces": [
                {"image_uris": {"small": "https://img.test/s.jpg"}},
                {"image_uris": {"normal": "https://img.test/d.jpg"}},
            ]
        }
        self.assertEqual(image_url(card_faceonly), "https://img.test/d.jpg")
        none_card = {}
        self.assertIsNone(image_url(none_card))


if __name__ == "__main__":
    unittest.main()
