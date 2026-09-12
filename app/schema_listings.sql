-- O banco de anúncios guarda ofertas (listings) e desejos (wants).
-- Pode ser executado várias vezes sem apagar dados.
PRAGMA foreign_keys = ON;

-- Versões ficam registradas para que migrações futuras saibam o que já foi aplicado.
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A versão 1 representa a criação inicial das tabelas de anúncios.
INSERT OR IGNORE INTO schema_version(version) VALUES (1);

-- Oferta de uma impressão que o usuário possui.
-- card_id aponta para o banco de cartas e user_id para o banco de contas;
-- a consistência entre bancos é validada na aplicação (seed, import e API).
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
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
    card_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    max_price_cents INTEGER CHECK(max_price_cents IS NULL OR max_price_cents >= 0),
    desired_condition TEXT CHECK(desired_condition IN ('NM', 'SP', 'MP', 'HP', 'DMG')),
    mode TEXT NOT NULL DEFAULT 'ambos' CHECK(mode IN ('compra', 'troca', 'ambos')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(card_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_listings_card
    ON listings(card_id);

CREATE INDEX IF NOT EXISTS idx_listings_mode
    ON listings(mode);

-- Índice usado quando desejos forem cruzados com ofertas no futuro.
CREATE INDEX IF NOT EXISTS idx_wants_card
    ON wants(card_id);
