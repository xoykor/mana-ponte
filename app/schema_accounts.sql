-- O banco de contas guarda usuários cadastrados e sessões ativas.
-- Pode ser executado várias vezes sem apagar dados.
PRAGMA foreign_keys = ON;

-- Versões ficam registradas para que migrações futuras saibam o que já foi aplicado.
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A versão 1 representa a criação inicial das tabelas de autenticação.
INSERT OR IGNORE INTO schema_version(version) VALUES (1);

-- Identidade e dados básicos do jogador.
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL CHECK(length(state) = 2),
    password_hash TEXT,
    email_verified INTEGER NOT NULL DEFAULT 0 CHECK(email_verified IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- O token bruto nunca é salvo; apenas seu hash é armazenado nesta tabela.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_location
    ON users(state, city);

CREATE INDEX IF NOT EXISTS idx_sessions_user
    ON sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_sessions_expiry
    ON sessions(expires_at);
