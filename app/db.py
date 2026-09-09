"""Conexões, schema e migrações incrementais do SQLite."""
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
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _migrate_auth(connection: sqlite3.Connection) -> None:
    columns = _columns(connection, "users")
    additions = {
        "password_hash": "TEXT",
        "email_verified": "INTEGER NOT NULL DEFAULT 0 CHECK(email_verified IN (0,1))",
        "updated_at": "TEXT",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE users ADD COLUMN {name} {declaration}")
    connection.execute("UPDATE users SET updated_at=COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)")
    session_columns = {row["name"]: row["type"].upper() for row in connection.execute("PRAGMA table_info(sessions)")}
    session_fks = list(connection.execute("PRAGMA foreign_key_list(sessions)"))
    if session_columns and (session_columns.get("expires_at") != "INTEGER" or not session_fks):
        # Sessões são efêmeras: uma migração estrutural as revoga sem perder contas.
        connection.execute("DROP TABLE sessions")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            csrf_token TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
        INSERT OR IGNORE INTO schema_version(version) VALUES (2);
    """)


def init_db(db_path: str | Path | None = None) -> Path:
    path = resolve_db_path(db_path)
    connection = get_connection(path)
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate_auth(connection)
        connection.commit()
    finally:
        connection.close()
    return path
