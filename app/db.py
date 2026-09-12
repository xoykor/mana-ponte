"""Conexões, schemas e migrações incrementais do SQLite.

A aplicação usa três bancos separados:

- ``data/cards.db``: impressões de cartas;
- ``data/accounts.db``: usuários cadastrados e sessões;
- ``data/listings.db``: ofertas (listings) e desejos (wants).

Cada banco tem o próprio arquivo de schema. As regras de negócio ficam nos
módulos que chamam estas funções.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path


# O diretório raiz do projeto é o pai do diretório ``app``.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# O banco legado continua disponível para compatibilidade com instalações
# anteriores e com integrações que ainda passam um único caminho explícito.
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "app.db"

# O diretório ``data/`` fica fora de ``public/`` para nunca ser publicado pelo Pages.
DEFAULT_CARDS_DB_PATH = PROJECT_ROOT / "data" / "cards.db"
DEFAULT_ACCOUNTS_DB_PATH = PROJECT_ROOT / "data" / "accounts.db"
DEFAULT_LISTINGS_DB_PATH = PROJECT_ROOT / "data" / "listings.db"

# Cada schema é mantido como SQL separado para continuar fácil de ler e editar.
SCHEMA_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = SCHEMA_DIR / "schema.sql"
CARDS_SCHEMA_PATH = SCHEMA_DIR / "schema_cards.sql"
ACCOUNTS_SCHEMA_PATH = SCHEMA_DIR / "schema_accounts.sql"
LISTINGS_SCHEMA_PATH = SCHEMA_DIR / "schema_listings.sql"
SPLIT_DB_ENV_VARS = (
    "MANAPONTE_CARDS_DB_PATH",
    "MANAPONTE_ACCOUNTS_DB_PATH",
    "MANAPONTE_LISTINGS_DB_PATH",
)


def _resolve(db_path: str | Path | None, env_var: str, default: Path) -> Path:
    """Resolve o caminho de um banco.

    A prioridade é:

    1. caminho recebido explicitamente pela função;
    2. variável de ambiente específica do banco;
    3. banco padrão dentro de ``data/``.
    """

    configured = (
        db_path
        if db_path is not None
        else os.environ.get(env_var) or default
    )
    return Path(configured)


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Caminho do banco único legado.

    A aplicação nova usa os três resolvedores específicos abaixo. Esta função
    permanece para scripts e consumidores antigos que ainda trabalham com um
    único arquivo SQLite.
    """

    return _resolve(db_path, "MANAPONTE_DB_PATH", DEFAULT_DB_PATH)


def resolve_cards_db_path(db_path: str | Path | None = None) -> Path:
    """Caminho do banco de cartas."""

    return _resolve(db_path, "MANAPONTE_CARDS_DB_PATH", DEFAULT_CARDS_DB_PATH)


def resolve_accounts_db_path(db_path: str | Path | None = None) -> Path:
    """Caminho do banco de contas."""

    return _resolve(db_path, "MANAPONTE_ACCOUNTS_DB_PATH", DEFAULT_ACCOUNTS_DB_PATH)


def resolve_listings_db_path(db_path: str | Path | None = None) -> Path:
    """Caminho do banco de anúncios."""

    return _resolve(db_path, "MANAPONTE_LISTINGS_DB_PATH", DEFAULT_LISTINGS_DB_PATH)


def legacy_env_db_path() -> Path | None:
    """Retorna o caminho legado quando só a configuração antiga foi usada."""

    if os.environ.get("MANAPONTE_DB_PATH") and not any(
        os.environ.get(name) for name in SPLIT_DB_ENV_VARS
    ):
        return resolve_db_path()
    return None


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


def get_cards_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Conexão apenas ao banco de cartas."""

    return get_connection(resolve_cards_db_path(db_path))


def get_accounts_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Conexão apenas ao banco de contas."""

    return get_connection(resolve_accounts_db_path(db_path))


def get_listings_app_connection(
    listings_db: str | Path | None = None,
    cards_db: str | Path | None = None,
    accounts_db: str | Path | None = None,
) -> sqlite3.Connection:
    """Conexão ao banco de anúncios com os outros bancos anexados.

    A conexão principal é o banco de anúncios; os bancos de cartas e contas
    são anexados como ``catalog`` e ``accounts``. Assim uma única conexão pode
    consultar ``catalog.cards`` e ``accounts.users`` junto de ``listings`` e
    ``wants``.
    """

    listings_path = resolve_listings_db_path(listings_db)
    cards_path = resolve_cards_db_path(cards_db)
    accounts_path = resolve_accounts_db_path(accounts_db)

    # ATTACH não cria os diretórios pais dos arquivos anexados.
    cards_path.parent.mkdir(parents=True, exist_ok=True)
    accounts_path.parent.mkdir(parents=True, exist_ok=True)

    connection = get_connection(listings_path)
    try:
        connection.execute(
            "ATTACH DATABASE ? AS catalog",
            (str(cards_path),),
        )
        connection.execute(
            "ATTACH DATABASE ? AS accounts",
            (str(accounts_path),),
        )
    except Exception:
        connection.close()
        raise
    return connection


def get_listings_db_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Conexão apenas ao banco de anúncios."""

    return get_connection(resolve_listings_db_path(db_path))


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
    required_session_columns = {
        "token_hash",
        "user_id",
        "csrf_token",
        "created_at",
        "expires_at",
    }
    foreign_key_targets = {row["table"] for row in session_foreign_keys}
    has_incompatible_sessions = bool(session_columns) and (
        not required_session_columns.issubset(session_columns)
        or session_columns.get("expires_at") != "INTEGER"
        or "users" not in foreign_key_targets
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


def _init_with_schema(path: Path, schema_path: Path, migrations=None) -> Path:
    """Executa o schema do banco e migrações pendentes de forma idempotente."""

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = get_connection(path)

    try:
        # O schema usa ``CREATE TABLE IF NOT EXISTS``; reexecutá-lo não
        # apaga dados. A conexão usa ``executescript`` para tabelas, índices
        # e a versão inicial.
        schema = schema_path.read_text(encoding="utf-8")
        connection.executescript(schema)

        # Migrações adicionais ficam depois do schema-base.
        if migrations is not None:
            migrations(connection)
        connection.commit()
    finally:
        # Mesmo quando uma migração falha, a conexão precisa ser fechada.
        connection.close()

    return path


def init_cards_db(db_path: str | Path | None = None) -> Path:
    """Cria o schema do banco de cartas."""

    return _init_with_schema(resolve_cards_db_path(db_path), CARDS_SCHEMA_PATH)


def init_accounts_db(db_path: str | Path | None = None) -> Path:
    """Cria o schema do banco de contas e aplica migrações de autenticação."""

    return _init_with_schema(resolve_accounts_db_path(db_path), ACCOUNTS_SCHEMA_PATH, _migrate_auth)


def init_listings_db(db_path: str | Path | None = None) -> Path:
    """Cria o schema do banco de anúncios."""

    return _init_with_schema(resolve_listings_db_path(db_path), LISTINGS_SCHEMA_PATH)


def resolve_db_paths(
    db_paths: Mapping[str, str | Path | None] | None = None,
) -> dict[str, Path]:
    """Resolve a configuração dos três bancos da aplicação."""

    configured = db_paths or {}
    return {
        "cards": resolve_cards_db_path(configured.get("cards")),
        "accounts": resolve_accounts_db_path(configured.get("accounts")),
        "listings": resolve_listings_db_path(configured.get("listings")),
    }


def init_db(
    db_paths: Mapping[str, str | Path | None] | str | Path | None = None,
) -> dict[str, Path] | Path:
    """Cria os schemas dos três bancos e aplica migrações pendentes.

    A função é idempotente: pode ser chamada no início do servidor, do seed ou
    de um teste sem apagar os dados existentes. Sem caminho, usa três arquivos
    separados. Um caminho único explícito mantém o modo legado para não quebrar
    instalações e scripts que ainda esperam todas as tabelas no mesmo arquivo.
    """

    if isinstance(db_paths, (str, os.PathLike)):
        return _init_with_schema(
            resolve_db_path(db_paths),
            SCHEMA_PATH,
            _migrate_auth,
        )

    if db_paths is None and (legacy_path := legacy_env_db_path()) is not None:
        return _init_with_schema(legacy_path, SCHEMA_PATH, _migrate_auth)

    paths = resolve_db_paths(db_paths)
    init_cards_db(paths["cards"])
    init_accounts_db(paths["accounts"])
    init_listings_db(paths["listings"])
    return paths
