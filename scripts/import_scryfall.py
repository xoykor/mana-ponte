#!/usr/bin/env python3
"""Importa o catálogo de cartas de papel publicado pelo Scryfall.

Este script aceita duas formas de entrada:

* um arquivo ``default_cards`` já baixado com ``--file``;
* um download automático do arquivo atual com ``--download``.

O trabalho de interpretar e gravar as cartas fica em ``app.catalog``. Assim,
o script continua sendo apenas uma interface de linha de comando simples e
fácil de entender.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen


# O script pode ser executado diretamente a partir da pasta ``scripts``.
# Por isso, adicionamos a raiz do projeto ao caminho de importação antes de
# importar o pacote ``app``.
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from app.catalog import import_file  # noqa: E402  (import após ajustar sys.path)


# Endpoint oficial que informa os arquivos Bulk Data disponíveis no Scryfall.
BULK_ENDPOINT = "https://api.scryfall.com/bulk-data"

# Um User-Agent identificável ajuda o serviço remoto a diagnosticar chamadas.
USER_AGENT = "ManaPonte/0.1 (+https://example.invalid/manaponte)"


def request(url: str) -> Request:
    """Cria uma requisição HTTP com os cabeçalhos usados pelo importador."""

    return Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )


def default_cards_uri() -> str:
    """Descobre a URL temporária do arquivo ``default_cards`` mais recente."""

    # O endpoint de Bulk Data devolve metadados, não o arquivo das cartas.
    # Primeiro lemos esses metadados para descobrir o endereço de download.
    with urlopen(request(BULK_ENDPOINT), timeout=30) as response:
        payload = json.load(response)

    # O Scryfall pode publicar vários tipos de arquivos. Para o catálogo de
    # papel precisamos especificamente do item chamado ``default_cards``.
    for item in payload.get("data", []):
        if item.get("type") == "default_cards" and item.get("download_uri"):
            return item["download_uri"]

    # Se o formato da resposta mudar, falhar explicitamente é mais seguro do
    # que tentar baixar uma URL inexistente ou importar dados errados.
    raise RuntimeError("Scryfall não retornou o download default_cards")


def download_bulk(destination: Path) -> None:
    """Baixa o arquivo Bulk Data para ``destination`` sem carregá-lo na RAM."""

    # O arquivo completo pode ser grande. ``copyfileobj`` transmite os bytes
    # diretamente da resposta para o arquivo temporário no disco.
    with urlopen(request(default_cards_uri()), timeout=120) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def main() -> None:
    """Analisa os argumentos e executa a importação solicitada pelo usuário."""

    parser = argparse.ArgumentParser(
        description="Importa o catálogo Scryfall no ManaPonte"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--file",
        type=Path,
        help="arquivo default_cards JSON já baixado",
    )
    source.add_argument(
        "--download",
        action="store_true",
        help="baixa o default_cards atual antes de importar",
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="caminho alternativo para o banco SQLite de cartas",
    )
    args = parser.parse_args()

    if args.file:
        # Quando o arquivo já existe localmente, podemos importá-lo diretamente.
        imported_count = import_file(args.file, args.db)
    else:
        # O diretório temporário é removido automaticamente ao final do bloco.
        # Isso evita deixar um dump grande do catálogo no projeto.
        with tempfile.TemporaryDirectory(prefix="manaponte-") as temp:
            bulk_file = Path(temp) / "default-cards.json"
            print("Baixando Bulk Data do Scryfall…")
            download_bulk(bulk_file)
            imported_count = import_file(bulk_file, args.db)

    print(f"{imported_count} impressões em papel importadas.")
    print(
        "Imagens permanecem hospedadas no Scryfall; respeite as políticas "
        "do Scryfall e da Wizards."
    )


if __name__ == "__main__":
    main()
