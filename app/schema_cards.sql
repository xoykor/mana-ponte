-- O banco de cartas guarda uma linha por impressão física de uma carta.
-- Pode ser executado várias vezes sem apagar dados.
PRAGMA foreign_keys = ON;

-- Versões ficam registradas para que migrações futuras saibam o que já foi aplicado.
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A versão 1 representa a criação inicial da tabela de cartas.
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

-- Índice usado pela busca de nomes no seletor de cartas.
CREATE INDEX IF NOT EXISTS idx_cards_name
    ON cards(name COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_cards_set_lang
    ON cards(set_code, language);

CREATE INDEX IF NOT EXISTS idx_cards_oracle
    ON cards(oracle_id);
