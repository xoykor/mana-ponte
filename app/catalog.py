"""Normalização e importação do catálogo Scryfall."""
from __future__ import annotations

import json
from pathlib import Path

from .db import get_connection, init_db

BATCH_SIZE = 500


def image_url(card: dict) -> str | None:
    direct = card.get("image_uris") or {}
    if direct.get("normal"):
        return direct["normal"]
    for face in card.get("card_faces") or []:
        url = (face.get("image_uris") or {}).get("normal")
        if url:
            return url
    return None


def normalize_card(card: dict) -> tuple | None:
    if card.get("digital") or "paper" not in card.get("games", ["paper"]):
        return None
    required = (card.get("id"), card.get("name"), card.get("set"), card.get("set_name"), card.get("collector_number"))
    if not all(required):
        return None
    return (
        card["id"], card.get("oracle_id"), card["name"], card["set"], card["set_name"],
        str(card["collector_number"]), card.get("lang", "en"), card.get("rarity", "common"), image_url(card),
    )


UPSERT = """INSERT INTO cards(scryfall_id,oracle_id,name,set_code,set_name,collector_number,language,rarity,image_url)
VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(scryfall_id) DO UPDATE SET
oracle_id=excluded.oracle_id,name=excluded.name,set_code=excluded.set_code,set_name=excluded.set_name,
collector_number=excluded.collector_number,language=excluded.language,rarity=excluded.rarity,
image_url=excluded.image_url,updated_at=CURRENT_TIMESTAMP"""


def import_file(file_path: str | Path, db_path=None, batch_size=BATCH_SIZE) -> int:
    """Importa o array JSON do Bulk Data. Retorna o total de cartas em papel."""
    init_db(db_path)
    with Path(file_path).open(encoding="utf-8") as source:
        payload = json.load(source)
    if not isinstance(payload, list):
        raise ValueError("O Bulk Data deve ser um array JSON")
    total, batch = 0, []
    conn = get_connection(db_path)
    try:
        for raw in payload:
            normalized = normalize_card(raw)
            if normalized:
                batch.append(normalized)
            if len(batch) >= batch_size:
                conn.executemany(UPSERT, batch)
                total += len(batch)
                batch.clear()
        if batch:
            conn.executemany(UPSERT, batch)
            total += len(batch)
        conn.commit()
    finally:
        conn.close()
    return total
