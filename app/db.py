"""Conexões e inicialização do SQLite do ManaPonte."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "app.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

def resolve_db_path(db_path: str | Path | None = None) -> Path:
    return Path(db_path or os.environ.get("MANAPONTE_DB_PATH", DEFAULT_DB_PATH))

def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def init_db(db_path: str | Path | None = None) -> Path:
    path = resolve_db_path(db_path)
    connection = get_connection(path)
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()
    return path
