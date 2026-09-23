"""Catálogo de cartas do backend Python legado.

Fluxo mental:

    arquivo/API do Scryfall
        -> normalize_card()
        -> tupla local
        -> SQLite

O parser é incremental para não precisar colocar o catálogo inteiro na RAM.
Produção usa D1 + cloudflare-worker/src/catalog.js.
"""

"""Normalização e importação do catálogo Scryfall.

O banco guarda uma linha por impressão física. Este módulo transforma objetos
do Scryfall no formato simples usado pela tabela ``cards`` e pelos repositórios
de consulta.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Iterator, Mapping
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

# Variantes publicadas pelo Scryfall em ``image_uris``. A ordem mantém
# ``normal`` como opção padrão e cobre cartas que só expõem outra variante.
IMAGE_VARIANTS = (
    "normal",
    "large",
    "png",
    "small",
    "art_crop",
    "border_crop",
)


def image_url(card: Mapping) -> str | None:
    """Retorna a melhor URL de imagem disponível para uma carta.

    Cartas de uma face guardam a imagem em ``image_uris``. Cartas dupla-face
    normalmente guardam as imagens dentro de ``card_faces``; nesse caso,
    usamos a primeira fonte que tiver a melhor variante disponível.
    """

    if not isinstance(card, Mapping):
        return None

    sources = []
    direct_images = card.get("image_uris")
    if isinstance(direct_images, Mapping):
        sources.append(direct_images)

    faces = card.get("card_faces")
    if isinstance(faces, (list, tuple)):
        for face in faces:
            if not isinstance(face, Mapping):
                continue
            face_images = face.get("image_uris")
            if isinstance(face_images, Mapping):
                sources.append(face_images)

    # Tenta a melhor variante em todas as fontes. Assim uma face posterior
    # com ``normal`` não perde para uma ``small`` da primeira face.
    for variant in IMAGE_VARIANTS:
        for source in sources:
            url = source.get(variant)
            if isinstance(url, str) and url.strip():
                return url

    # Nem todas as cartas retornam imagem. O banco aceita NULL nesse campo.
    return None


def normalize_card(card: Mapping) -> tuple | None:
    """Converte um objeto Scryfall em uma tupla pronta para o SQLite.

    Cartas exclusivamente digitais são ignoradas porque o marketplace trata
    de cartas físicas. Registros sem os identificadores mínimos também não
    podem ser associados a uma impressão e, portanto, são descartados.
    """

    if not isinstance(card, Mapping):
        return None

    games = card.get("games", ("paper",))
    if isinstance(games, str):
        games = (games,)
    elif not isinstance(games, (list, tuple, set, frozenset)):
        return None

    if card.get("digital") or "paper" not in games:
        return None

    values = []
    for key in ("id", "name", "set", "set_name", "collector_number"):
        value = card.get(key)
        if isinstance(value, bool) or value is None:
            return None
        if not isinstance(value, (str, int, float)):
            return None
        text = str(value)
        if not text.strip():
            return None
        values.append(text)

    scryfall_id, name, set_code, set_name, collector_number = values

    # name é o nome Oracle/canônico. Impressões traduzidas podem trazer
    # o nome efetivamente impresso no campo printed_name.
    printed_name = card.get("printed_name")
    if printed_name is not None:
        printed_name = str(printed_name).strip() or None

    oracle_id = card.get("oracle_id")
    if oracle_id is not None and not isinstance(oracle_id, str):
        oracle_id = str(oracle_id)

    language = card.get("lang") or "en"
    rarity = card.get("rarity") or "common"
    if not isinstance(language, str) or not isinstance(rarity, str):
        return None

    return (
        scryfall_id,
        oracle_id,
        name,
        printed_name,
        set_code,
        set_name,
        collector_number,
        language,
        rarity,
        image_url(card),
    )


# O conflito pelo scryfall_id atualiza os metadados, sem criar duplicatas.
UPSERT = """
INSERT INTO cards(
    scryfall_id,
    oracle_id,
    name,
    printed_name,
    set_code,
    set_name,
    collector_number,
    language,
    rarity,
    image_url
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(scryfall_id) DO UPDATE SET
    oracle_id = excluded.oracle_id,
    name = excluded.name,
    printed_name = excluded.printed_name,
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
        f"q={quote(' '.join(query_parts))}"
        "&include_extras=false&include_multilingual=true"
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


def _notify_skip(on_skip: Callable[[str], None] | None, kind: str) -> None:
    """Notifica uma entrada ignorada sem exigir um callback no chamador."""

    if on_skip is not None:
        on_skip(kind)


def _iter_json_array(
    source,
    first_line: str,
    on_skip: Callable[[str], None] | None,
) -> Iterator[object]:
    """Lê um array JSON incrementalmente a partir da primeira linha."""

    decoder = json.JSONDecoder()
    buffer = first_line
    end_of_file = False

    def fill() -> None:
        nonlocal buffer, end_of_file
        if end_of_file:
            return
        chunk = source.read(64 * 1024)
        if chunk:
            buffer += chunk
        else:
            end_of_file = True

    def discard_whitespace() -> bool:
        nonlocal buffer
        while True:
            stripped = buffer.lstrip()
            if stripped:
                buffer = stripped
                return True
            if end_of_file:
                return False
            fill()

    if not discard_whitespace() or not buffer.startswith("["):
        _notify_skip(on_skip, "invalid")
        return

    buffer = buffer[1:]
    seen_value = False
    expecting_value = True

    def finish() -> bool:
        """Confirma que só há espaços depois do fechamento do array."""

        nonlocal buffer
        while True:
            if buffer.strip():
                _notify_skip(on_skip, "invalid")
                return False
            if end_of_file:
                return True
            fill()

    while True:
        if not discard_whitespace():
            _notify_skip(on_skip, "invalid")
            return

        if buffer.startswith("]"):
            if expecting_value and seen_value:
                _notify_skip(on_skip, "invalid")
                return
            buffer = buffer[1:]
            finish()
            return

        while True:
            try:
                value, consumed = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                if end_of_file:
                    _notify_skip(on_skip, "invalid")
                    return
                fill()
                continue

            yield value
            buffer = buffer[consumed:]
            seen_value = True
            expecting_value = False
            break

        if not discard_whitespace():
            _notify_skip(on_skip, "invalid")
            return
        if buffer.startswith(","):
            buffer = buffer[1:]
            expecting_value = True
            continue
        if buffer.startswith("]"):
            buffer = buffer[1:]
            finish()
            return

        _notify_skip(on_skip, "invalid")
        return


def _iter_cards(
    file_path: str | Path,
    on_skip: Callable[[str], None] | None = None,
) -> Iterator[object]:
    """Gera os objetos de carta do arquivo Bulk Data.

    Suporta JSONL e arrays JSON, comprimidos ou não. JSONL é consumido linha a
    linha; arrays também são decodificados em valores individuais, mantendo o
    uso de memória limitado ao buffer corrente.
    """

    path = Path(file_path)

    # Detecta gzip pelo número mágico (0x1f 0x8b), não pela extensão, lendo
    # apenas os dois bytes necessários. Isso evita duplicar na memória um bulk
    # inteiro antes de começar a importação.
    with path.open("rb") as probe:
        is_gzip = probe.read(2) == b"\x1f\x8b"
    opener = gzip.open if is_gzip else open

    with opener(path, mode="rt", encoding="utf-8-sig", errors="replace") as source:
        # A primeira linha não vazia identifica arrays JSON antigos. Para
        # JSONL, ela é processada imediatamente e as seguintes são lidas uma
        # por vez; não há ``read`` ou ``splitlines`` do arquivo inteiro.
        first_line = None
        for line in source:
            if line.strip():
                first_line = line
                break
            _notify_skip(on_skip, "blank")

        if first_line is None:
            return

        if first_line.lstrip().startswith("["):
            yield from _iter_json_array(source, first_line, on_skip)
            return

        try:
            yield json.loads(first_line.strip())
        except json.JSONDecodeError:
            _notify_skip(on_skip, "invalid")

        for line in source:
            stripped = line.strip()
            if not stripped:
                _notify_skip(on_skip, "blank")
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError:
                _notify_skip(on_skip, "invalid")


def import_file(
    file_path: str | Path,
    db_path: str | Path | None = None,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Importa o catálogo Bulk Data e retorna o total de cartas processadas.

    O retorno continua sendo um inteiro para os consumidores existentes. Um
    relatório legível é emitido ao final com importadas, ignoradas e inválidas;
    linhas JSON inválidas entram tanto em ``ignoradas`` quanto em ``inválidas``.
    """

    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or batch_size <= 0
    ):
        raise ValueError("batch_size deve ser um inteiro positivo")

    # O schema precisa existir antes de qualquer operação de upsert.
    init_cards_db(db_path)

    # Lê linha a linha para não carregar o arquivo inteiro na RAM.
    total_imported = 0
    skipped = 0
    invalid_entries = 0
    batch = []
    connection = get_cards_connection(db_path)
    skips = {"blank": 0, "invalid": 0}

    def on_skip(kind: str) -> None:
        nonlocal skipped
        if kind in skips:
            skips[kind] += 1
        skipped += 1

    try:
        for raw_card in _iter_cards(file_path, on_skip=on_skip):
            # Entradas não-objeto não abortam a importação com AttributeError.
            if not isinstance(raw_card, Mapping):
                skipped += 1
                invalid_entries += 1
                continue

            normalized = normalize_card(raw_card)
            if normalized:
                batch.append(normalized)
            else:
                # Descartada por ser digital ou falta campo obrigatório.
                skipped += 1
                invalid_entries += 1

            # Assim que o lote atinge o tamanho definido, grava e libera a
            # memória usada pelas tuplas normalizadas.
            if len(batch) >= batch_size:
                total_imported += upsert_rows(connection, batch)
                batch.clear()

        # O último lote normalmente é menor que BATCH_SIZE e também precisa
        # ser persistido.
        if batch:
            total_imported += upsert_rows(connection, batch)

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    # ``invalid_entries`` inclui registros não-objeto e cartas filtradas por
    # serem digitais/incompletas; ``skips`` inclui também linhas em branco.
    invalid_entries += skips["invalid"]
    print(
        "importadas:",
        total_imported,
        "ignoradas:",
        skipped,
        "invalidas:",
        invalid_entries,
    )
    return total_imported
