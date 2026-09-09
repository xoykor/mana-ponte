PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO schema_version(version) VALUES (1);

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
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL CHECK(length(state) = 2),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
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
CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_cards_set_lang ON cards(set_code, language);
CREATE INDEX IF NOT EXISTS idx_cards_oracle ON cards(oracle_id);
CREATE INDEX IF NOT EXISTS idx_users_location ON users(state, city);
CREATE INDEX IF NOT EXISTS idx_listings_card ON listings(card_id);
CREATE INDEX IF NOT EXISTS idx_listings_mode ON listings(mode);
CREATE INDEX IF NOT EXISTS idx_wants_card ON wants(card_id);
