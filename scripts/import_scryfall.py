#!/usr/bin/env python3
"""Baixa ou importa o arquivo default_cards do Scryfall."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from app.catalog import import_file  # noqa: E402

BULK_ENDPOINT = "https://api.scryfall.com/bulk-data"
USER_AGENT = "ManaPonte/0.1 (+https://example.invalid/manaponte)"


def request(url):
    return Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})


def default_cards_uri() -> str:
    with urlopen(request(BULK_ENDPOINT), timeout=30) as response:
        payload = json.load(response)
    for item in payload.get("data", []):
        if item.get("type") == "default_cards" and item.get("download_uri"):
            return item["download_uri"]
    raise RuntimeError("Scryfall não retornou o download default_cards")


def download_bulk(destination: Path) -> None:
    with urlopen(request(default_cards_uri()), timeout=120) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def main():
    parser = argparse.ArgumentParser(description="Importa o catálogo Scryfall no ManaPonte")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="default_cards JSON já baixado")
    source.add_argument("--download", action="store_true", help="baixa o default_cards atual")
    parser.add_argument("--db", type=Path, help="caminho alternativo do SQLite")
    args = parser.parse_args()

    if args.file:
        count = import_file(args.file, args.db)
    else:
        with tempfile.TemporaryDirectory(prefix="manaponte-") as temp:
            bulk = Path(temp) / "default-cards.json"
            print("Baixando Bulk Data do Scryfall…")
            download_bulk(bulk)
            count = import_file(bulk, args.db)
    print(f"{count} impressões em papel importadas.")
    print("Imagens permanecem hospedadas no Scryfall; respeite as políticas do Scryfall e da Wizards.")


if __name__ == "__main__":
    main()
