"""Normalização e importação do catálogo Scryfall.

O banco guarda uma linha por impressão física. Este módulo transforma objetos
do Scryfall no formato simples usado pela tabela ``cards`` e pelos repositórios
de consulta.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from .db import get_cards_connection, init_cards_db


# O importador de Bulk Data grava registros em grupos para reduzir commits.
BATCH_SIZE = 500

# Uma busca pode ter muitas impressões. O limite evita um loop infinito caso o
# provedor devolva links de paginação repetidos ou uma resposta inesperada.
MAX_SEARCH_PAGES = 50

SCRYFALL_SEARCH_ENDPOINT = "https://api.scryfall.com/cards/search"
SCRYFALL_USER_AGENT = "ManaPonte/0.1 (local card search)"


def image_url(card: dict) -> str | None:
    """Retorna a melhor URL de imagem disponível para uma carta.

    Cartas de uma face guardam a imagem em ``image_uris``. Cartas dupla-face
    normalmente guardam as imagens dentro de ``card_faces``; nesse caso,
    usamos a primeira face que tiver uma imagem normal.
    """

    direct_images = card.get("image_uris") or {}
    if direct_images.get("normal"):
        return direct_images["normal"]

    for face in card.get("card_faces") or []:
        face_images = face.get("image_uris") or {}
        if face_images.get("normal"):
            return face_images["normal"]

    # Nem todas as cartas retornam imagem. O banco aceita NULL nesse campo.
    return None


def normalize_card(card: dict) -> tuple | None:
    """Converte um objeto Scryfall em uma tupla pronta para o SQLite.

    Cartas exclusivamente digitais são ignoradas porque o marketplace trata
    de cartas físicas. Registros sem os identificadores mínimos também não
    podem ser associados a uma impressão e, portanto, são descartados.
    """

    games = card.get("games", ["paper"])
    if card.get("digital") or "paper" not in games:
        return None

    required_values = (
        card.get("id"),
        card.get("name"),
        card.get("set"),
        card.get("set_name"),
        card.get("collector_number"),
    )
    if not all(required_values):
        return None

    return (
        card["id"],
        card.get("oracle_id"),
        card["name"],
        card["set"],
        card["set_name"],
        str(card["collector_number"]),
        card.get("lang", "en"),
        card.get("rarity", "common"),
        image_url(card),
    )


# O conflito pelo scryfall_id atualiza os metadados, sem criar duplicatas.
UPSERT = """
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
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(scryfall_id) DO UPDATE SET
    oracle_id = excluded.oracle_id,
    name = excluded.name,
    set_code = excluded.set_code,
    set_name = excluded.set_name,
    collector_number = excluded.collector_number,
    language = excluded.language,
    rarity = excluded.rarity,
    image_url = excluded.image_url,
    updated_at = CURRENT_TIMESTAMP
"""


def upsert_rows(connection, rows: list[tuple]) -> int:
    """Insere ou atualiza impressões e retorna o número de tuplas processadas."""

    if not rows:
        return 0

    connection.executemany(UPSERT, rows)
    return len(rows)


def _get_json(url: str, timeout: int = 8) -> dict:
    """Busca JSON no Scryfall usando o User-Agent exigido pelo cliente."""

    request = Request(
        url,
        headers={
            "User-Agent": SCRYFALL_USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def search_scryfall(
    query: str,
    set_code: str | None = None,
    language: str | None = None,
) -> list[tuple]:
    """Busca todas as páginas de impressões físicas no Scryfall.

    O resultado usa exatamente o mesmo formato produzido por
    :func:`normalize_card`, então a API pode persistir a resposta sem uma
    segunda transformação. O endpoint retorna ``next_page`` quando há mais
    resultados; seguimos esses links até a busca terminar.
    """

    cleaned_query = " ".join(query.split())
    if not cleaned_query:
        return []

    # Remover aspas impede que o texto digitado feche o operador name: da
    # consulta construída. O restante da consulta continua sendo codificado
    # pela função quote antes de ir para a URL.
    safe_query = cleaned_query.replace('"', "")
    query_parts = [f'name:"{safe_query}"', "unique:prints"]

    if set_code:
        query_parts.append(f"set:{set_code.strip()}")
    if language:
        query_parts.append(f"lang:{language.strip()}")

    page_url = (
        f"{SCRYFALL_SEARCH_ENDPOINT}?"
        f"q={quote(' '.join(query_parts))}&include_extras=false"
    )
    raw_cards = []
    visited_urls = set()

    while (
        page_url
        and page_url not in visited_urls
        and len(visited_urls) < MAX_SEARCH_PAGES
    ):
        visited_urls.add(page_url)
        payload = _get_json(page_url)

        if not isinstance(payload, dict):
            break

        # ``data`` pode faltar em uma resposta válida sem resultados.
        raw_cards.extend(payload.get("data") or [])

        next_page = payload.get("next_page")
        if payload.get("has_more") and isinstance(next_page, str):
            page_url = next_page
        else:
            page_url = None

    # A normalização filtra cartas digitais e registros incompletos.
    return [
        normalized
        for card in raw_cards
        if (normalized := normalize_card(card)) is not None
    ]


def import_file(
    file_path: str | Path,
    db_path: str | Path | None = None,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Importa um array JSON do Bulk Data e retorna o total processado."""

    # O schema precisa existir antes de qualquer operação de upsert.
    init_cards_db(db_path)

    with Path(file_path).open(encoding="utf-8") as source:
        payload = json.load(source)

    if not isinstance(payload, list):
        raise ValueError("O Bulk Data deve ser um array JSON")

    total_imported = 0
    batch = []
    connection = get_cards_connection(db_path)

    try:
        for raw_card in payload:
            normalized = normalize_card(raw_card)
            if normalized:
                batch.append(normalized)

            # Assim que o lote atinge o tamanho definido, grava e libera a
            # memória usada pelas tuplas normalizadas.
            if len(batch) >= batch_size:
                connection.executemany(UPSERT, batch)
                total_imported += len(batch)
                batch.clear()

        # O último lote normalmente é menor que BATCH_SIZE e também precisa
        # ser persistido.
        if batch:
            connection.executemany(UPSERT, batch)
            total_imported += len(batch)

        connection.commit()
    finally:
        connection.close()

    return total_imported
