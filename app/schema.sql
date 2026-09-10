-- O schema usa SQLite e pode ser executado várias vezes sem apagar dados.
PRAGMA foreign_keys = ON;

-- Versões ficam registradas para que migrações futuras saibam o que já foi aplicado.
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A versão 1 representa a criação inicial das tabelas principais.
INSERT OR IGNORE INTO schema_version(version) VALUES (1);

-- Uma linha representa uma impressão específica de uma carta.
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    scryfall_id TEXT NOT NULL UNIQUE,
    oracle_id TEXT,
    name TEXT NOT NULL,
    set_code TEXT NOT NULL,
    set_name TEXT NOT NULL,
    collector_number TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    rarity TEXT NOT NULL DEFAULT 'common',
    image_url TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

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

-- Oferta de uma impressão que o usuário possui.
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_cents INTEGER CHECK(price_cents IS NULL OR price_cents >= 0),
    condition TEXT NOT NULL CHECK(condition IN ('NM', 'SP', 'MP', 'HP', 'DMG')),
    language TEXT NOT NULL DEFAULT 'en',
    mode TEXT NOT NULL CHECK(mode IN ('venda', 'troca', 'ambos')),
    contact_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Desejo de compra/troca. O MVP ainda não expõe uma rota completa para wants.
CREATE TABLE IF NOT EXISTS wants (
    id INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    max_price_cents INTEGER CHECK(max_price_cents IS NULL OR max_price_cents >= 0),
    desired_condition TEXT CHECK(desired_condition IN ('NM', 'SP', 'MP', 'HP', 'DMG')),
    mode TEXT NOT NULL DEFAULT 'ambos' CHECK(mode IN ('compra', 'troca', 'ambos')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(card_id, user_id)
);

-- O token bruto nunca é salvo; apenas seu hash é armazenado nesta tabela.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

-- Índice usado pela busca de nomes no seletor de cartas.
CREATE INDEX IF NOT EXISTS idx_cards_name
    ON cards(name COLLATE NOCASE);

-- Índice usado pelos filtros de coleção e idioma.
CREATE INDEX IF NOT EXISTS idx_cards_set_lang
    ON cards(set_code, language);

-- Permite agrupar impressões da mesma carta lógica.
CREATE INDEX IF NOT EXISTS idx_cards_oracle
    ON cards(oracle_id);

-- Índices de localização e filtros das ofertas.
CREATE INDEX IF NOT EXISTS idx_users_location
    ON users(state, city);
CREATE INDEX IF NOT EXISTS idx_listings_card
    ON listings(card_id);
CREATE INDEX IF NOT EXISTS idx_listings_mode
    ON listings(mode);

-- Índice usado quando desejos forem cruzados com ofertas no futuro.
CREATE INDEX IF NOT EXISTS idx_wants_card
    ON wants(card_id);

-- Índices para limpeza e consulta de sessões.
CREATE INDEX IF NOT EXISTS idx_sessions_user
    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry
    ON sessions(expires_at);
