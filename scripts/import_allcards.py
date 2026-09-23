"""Importador local para tipos alternativos de Bulk Data do Scryfall.

É uma variação de import_scryfall.py que permite escolher o tipo publicado
pelo Scryfall, como all_cards.
"""

#!/usr/bin/env python3
"""Importa um bulk type arbitrário do Scryfall (ex.: all_cards).

Diferente de ``import_scryfall.py``, que usa sempre o ``default_cards``,
este aceita qualquer tipo de bulk data e faz upsert por ``scryfall_id``
nas cartas já existentes. Cartas em outros idiomas tornam-se novas linhas.
"""

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

from app.catalog import import_file  # noqa: E402 (import após ajustar sys.path)

BULK_ENDPOINT = "https://api.scryfall.com/bulk-data"
USER_AGENT = "ManaPonte/0.1 (+https://example.invalid/manaponte)"


def request(url: str) -> Request:
    return Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


def bulk_uri(bulk_type: str) -> str:
    """Descobre a URL temporária do arquivo de um tipo de bulk data."""
    with urlopen(request(BULK_ENDPOINT), timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("Scryfall retornou metadados inválidos de Bulk Data")

    items = payload.get("data")
    if not isinstance(items, list):
        raise RuntimeError("Scryfall retornou uma lista de Bulk Data inválida")

    for item in items:
        if not isinstance(item, dict) or item.get("type") != bulk_type:
            continue
        download_uri = item.get("jsonl_download_uri") or item.get("download_uri")
        if download_uri:
            return download_uri
    raise RuntimeError(f"Scryfall não retornou o download para o tipo '{bulk_type}'")


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa um bulk type Scryfall no ManaPonte")
    parser.add_argument("--type", required=True, help="tipo de bulk data (ex.: all_cards)")
    parser.add_argument("--db", type=Path, default=None,
                        help="caminho alternativo para o banco SQLite de cartas")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else PROJECT / "data" / "cards.db"

    temp = tempfile.mkdtemp(prefix="manaponte-")
    try:
        bulk_file = Path(temp) / f"{args.type}.jsonl.gz"
        print(f"Baixando {args.type} do Scryfall…")
        with urlopen(request(bulk_uri(args.type)), timeout=120) as response:
            with bulk_file.open("wb") as output:
                shutil.copyfileobj(response, output)

        size_mb = bulk_file.stat().st_size / (1024 * 1024)
        print(f"Arquivo baixado: {bulk_file.name} ({size_mb:.1f} MB)\n")

        before = import_file(bulk_file, db_path)
        print(f"{before} impressões em papel importadas (upsert por scryfall_id).")
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    main()
