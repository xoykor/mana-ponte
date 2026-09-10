"""Conexões, schema e migrações incrementais do SQLite.

Este módulo concentra tudo o que é específico da abertura e inicialização do
banco. As regras de negócio ficam nos módulos que chamam estas funções.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


# O diretório raiz do projeto é o pai do diretório ``app``.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# O banco padrão fica fora de ``public/`` para nunca ser publicado pelo Pages.
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "app.db"

# O schema é mantido como SQL separado para continuar fácil de ler e editar.
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Retorna o caminho do banco escolhido pela aplicação.

    A prioridade é:

    1. caminho recebido explicitamente pela função;
    2. variável de ambiente ``MANAPONTE_DB_PATH``;
    3. banco padrão dentro de ``data/``.
    """

    configured_path = db_path or os.environ.get("MANAPONTE_DB_PATH", DEFAULT_DB_PATH)
    return Path(configured_path)


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Abre uma conexão SQLite configurada para o projeto.

    Cada chamada abre uma conexão independente. Isso combina com o servidor
    HTTP, que pode atender várias requisições em paralelo, e com os testes,
    que podem criar bancos temporários.
    """

    path = resolve_db_path(db_path)

    # O SQLite não cria automaticamente os diretórios pais do arquivo.
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, timeout=10)

    # Permite acessar colunas pelo nome, por exemplo: row["username"].
    connection.row_factory = sqlite3.Row

    # Impede registros órfãos quando uma relação possui uma chave estrangeira.
    connection.execute("PRAGMA foreign_keys = ON")

    # Aguarda até dez segundos quando outra conexão estiver escrevendo.
    connection.execute("PRAGMA busy_timeout = 10000")

    return connection


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    """Retorna os nomes das colunas existentes em uma tabela.

    O nome da tabela vem apenas de chamadas internas do módulo, nunca de uma
    requisição HTTP. Por isso ele pode ser usado diretamente no PRAGMA.
    """

    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def _migrate_auth(connection: sqlite3.Connection) -> None:
    """Atualiza as tabelas de autenticação de versões antigas.

    Usuários são dados permanentes e, portanto, recebem colunas novas sem
    serem apagados. Sessões são efêmeras: se a estrutura antiga for
    incompatível, elas são revogadas e recriadas.
    """

    user_columns = _columns(connection, "users")
    user_additions = {
        "password_hash": "TEXT",
        "email_verified": "INTEGER NOT NULL DEFAULT 0 CHECK(email_verified IN (0,1))",
        "updated_at": "TEXT",
    }

    for column_name, declaration in user_additions.items():
        if column_name not in user_columns:
            connection.execute(
                f"ALTER TABLE users ADD COLUMN {column_name} {declaration}"
            )

    # Preenche a data de atualização de registros vindos do schema legado.
    connection.execute(
        "UPDATE users SET updated_at=COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)"
    )

    session_columns = {
        row["name"]: row["type"].upper()
        for row in connection.execute("PRAGMA table_info(sessions)")
    }
    session_foreign_keys = list(
        connection.execute("PRAGMA foreign_key_list(sessions)")
    )

    # A sessão antiga não pode ser convertida com segurança em todas as bases.
    # Como ela é temporária, apagar sessões antigas é preferível a manter uma
    # estrutura incompatível ou quebrar o login.
    has_incompatible_sessions = session_columns and (
        session_columns.get("expires_at") != "INTEGER"
        or not session_foreign_keys
    )
    if has_incompatible_sessions:
        connection.execute("DROP TABLE sessions")

    connection.executescript(
        """
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
        """
    )


def init_db(db_path: str | Path | None = None) -> Path:
    """Cria o schema e aplica migrações pendentes.

    A função é idempotente: pode ser chamada no início do servidor, do seed ou
    de um teste sem apagar os dados existentes.
    """

    path = resolve_db_path(db_path)
    connection = get_connection(path)

    try:
        # ``executescript`` executa as tabelas, índices e a versão inicial.
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        connection.executescript(schema)

        # Migrações adicionais ficam depois do schema-base.
        _migrate_auth(connection)
        connection.commit()
    finally:
        # Mesmo quando uma migração falha, a conexão precisa ser fechada.
        connection.close()

    return path
