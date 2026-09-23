
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scryfall_id TEXT NOT NULL UNIQUE,
  oracle_id TEXT,
  name TEXT NOT NULL,
  printed_name TEXT,
  set_code TEXT NOT NULL,
  set_name TEXT NOT NULL,
  collector_number TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT 'en',
  rarity TEXT NOT NULL DEFAULT 'common',
  image_url TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_cards_printed_name ON cards(printed_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_cards_set_lang ON cards(set_code, language);
CREATE INDEX IF NOT EXISTS idx_cards_oracle ON cards(oracle_id);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL,
  phone TEXT,
  city TEXT NOT NULL,
  state TEXT NOT NULL CHECK(length(state) = 2),
  password_hash TEXT NOT NULL,
  email_verified INTEGER NOT NULL DEFAULT 0 CHECK(email_verified IN (0,1)),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_location ON users(state, city);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id INTEGER NOT NULL REFERENCES cards(id),
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  price_cents INTEGER CHECK(price_cents IS NULL OR price_cents >= 0),
  condition TEXT NOT NULL CHECK(condition IN ('NM','SP','MP','HP','DMG')),
  language TEXT NOT NULL DEFAULT 'en',
  mode TEXT NOT NULL CHECK(mode IN ('venda','troca','ambos')),
  contact_url TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_listings_card ON listings(card_id);
CREATE INDEX IF NOT EXISTS idx_listings_user ON listings(user_id);
CREATE INDEX IF NOT EXISTS idx_listings_mode ON listings(mode);
CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at);

CREATE TABLE IF NOT EXISTS wants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  card_id INTEGER NOT NULL REFERENCES cards(id),
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  max_price_cents INTEGER CHECK(max_price_cents IS NULL OR max_price_cents >= 0),
  desired_condition TEXT CHECK(desired_condition IN ('NM','SP','MP','HP','DMG')),
  desired_language TEXT,
  mode TEXT NOT NULL DEFAULT 'ambos' CHECK(mode IN ('compra','troca','ambos')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(card_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_wants_card ON wants(card_id);
CREATE INDEX IF NOT EXISTS idx_wants_user ON wants(user_id);

CREATE TABLE IF NOT EXISTS login_attempts (
  key TEXT PRIMARY KEY,
  failures INTEGER NOT NULL DEFAULT 0,
  window_started INTEGER NOT NULL,
  blocked_until INTEGER NOT NULL DEFAULT 0
);

-- Somente metadados e URLs externas. Nenhum byte de imagem é armazenado.
INSERT OR IGNORE INTO cards(
  scryfall_id,name,set_code,set_name,collector_number,language,rarity,image_url
) VALUES
('b0faa7f2-b547-42c4-a810-839da50dadfe','Black Lotus','lea','Limited Edition Alpha','232','en','rare','https://cards.scryfall.io/normal/front/b/0/b0faa7f2-b547-42c4-a810-839da50dadfe.jpg'),
('46ca0b66-a000-4483-b916-f5b89e710244','Sol Ring','cmm','Commander Masters','410','en','uncommon','https://cards.scryfall.io/normal/front/4/6/46ca0b66-a000-4483-b916-f5b89e710244.jpg'),
('e768c957-3a1f-42f5-853a-96942f645df5','Lightning Bolt','m11','Magic 2011','149','en','common','https://cards.scryfall.io/normal/front/e/7/e768c957-3a1f-42f5-853a-96942f645df5.jpg'),
('1920dae4-fb92-4f19-ae4b-eb3276b8dac7','Counterspell','mh2','Modern Horizons 2','267','en','uncommon','https://cards.scryfall.io/normal/front/1/9/1920dae4-fb92-4f19-ae4b-eb3276b8dac7.jpg'),
('581b7327-3215-4a4f-b4ae-d9d4002ba882','Llanowar Elves','dom','Dominaria','168','en','common','https://cards.scryfall.io/normal/front/5/8/581b7327-3215-4a4f-b4ae-d9d4002ba882.jpg'),
('4d3473d0-b46f-41f5-ac1e-ba217f7747d4','Stoneforge Mystic','2xm','Double Masters','31','en','rare','https://cards.scryfall.io/normal/front/4/d/4d3473d0-b46f-41f5-ac1e-ba217f7747d4.jpg'),
('6fc57076-cac4-4f5e-956b-e3d77bd258b2','Dark Ritual','sta','Strixhaven Mystical Archive','26','en','rare','https://cards.scryfall.io/normal/front/6/f/6fc57076-cac4-4f5e-956b-e3d77bd258b2.jpg'),
('b281a308-ab6b-47b6-bec7-632c9aaecede','Thoughtseize','2xm','Double Masters','109','en','rare','https://cards.scryfall.io/normal/front/b/2/b281a308-ab6b-47b6-bec7-632c9aaecede.jpg'),
('3d69a3e0-6a2e-475a-964e-0affed1c017d','Birds of Paradise','rvr','Ravnica Remastered','133','en','rare','https://cards.scryfall.io/normal/front/3/d/3d69a3e0-6a2e-475a-964e-0affed1c017d.jpg'),
('043b2d30-a40f-4d47-933b-80544512f9c2','Rhystic Study','wot','Wilds of Eldraine: Enchanting Tales','25','en','mythic','https://cards.scryfall.io/normal/front/0/4/043b2d30-a40f-4d47-933b-80544512f9c2.jpg'),
('ff08e5ed-f47b-4d8e-8b8b-41675dccef8b','Cyclonic Rift','2xm','Double Masters','47','en','rare','https://cards.scryfall.io/normal/front/f/f/ff08e5ed-f47b-4d8e-8b8b-41675dccef8b.jpg'),
('71590b6f-9f38-4c5d-8431-50e5f02f8c93','Surrak, the Hunt Caller','cmm','Commander Masters','326','en','uncommon','https://cards.scryfall.io/normal/front/7/1/71590b6f-9f38-4c5d-8431-50e5f02f8c93.jpg');
