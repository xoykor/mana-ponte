-- SUPORTE MULTI-TCG (MAGIC & POKÉMON) E ACABAMENTO DE CARTAS
-- ==========================================================
--
-- Evolui o banco D1 preservando todos os dados existentes:
--   1. cards.game diferencia Magic ('mtg') e Pokémon ('pokemon');
--   2. listings.finish diferencia Normal, Foil/Holo, Reverse Holo, etc.;
--   3. adiciona cartas iniciais de Pokémon TCG com URLs externas do TCGdex.
--
-- Regra importante mantida: image_url guarda somente uma URL externa.

ALTER TABLE cards ADD COLUMN game TEXT NOT NULL DEFAULT 'mtg'
  CHECK(game IN ('mtg', 'pokemon'));

CREATE INDEX IF NOT EXISTS idx_cards_game_name
  ON cards(game, name COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_cards_game_printed_name
  ON cards(game, printed_name COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_cards_game_set_lang
  ON cards(game, set_code, language);

ALTER TABLE listings ADD COLUMN finish TEXT NOT NULL DEFAULT 'normal'
  CHECK(finish IN (
    'normal',
    'foil',
    'reverse_holo',
    'pokeball_foil',
    'masterball_foil',
    'etched'
  ));

CREATE INDEX IF NOT EXISTS idx_listings_finish
  ON listings(finish);

-- Sementes iniciais de Pokémon TCG (somente metadados + URL externa do TCGdex).
INSERT OR IGNORE INTO cards(
  game, scryfall_id, oracle_id, name, printed_name,
  set_code, set_name, collector_number, language, rarity, image_url
) VALUES
  ('pokemon','pokemon:pt:sv03.5-006','pokemon:sv03.5-006','Charizard ex','Charizard ex','sv03.5','151','006','pt','Rara Dupla','https://assets.tcgdex.net/pt/sv/sv03.5/006/high.webp'),
  ('pokemon','pokemon:pt:swsh4-43','pokemon:swsh4-43','Pikachu V','Pikachu V','swsh4','Voltagem Vívida','43','pt','Rara Holo V','https://assets.tcgdex.net/pt/swsh/swsh4/43/high.webp'),
  ('pokemon','pokemon:pt:sv03.5-150','pokemon:sv03.5-150','Mewtwo','Mewtwo','sv03.5','151','150','pt','Rara','https://assets.tcgdex.net/pt/sv/sv03.5/150/high.webp'),
  ('pokemon','pokemon:pt:sv03.5-094','pokemon:sv03.5-094','Gengar','Gengar','sv03.5','151','094','pt','Rara','https://assets.tcgdex.net/pt/sv/sv03.5/094/high.webp'),
  ('pokemon','pokemon:pt:sv01-196','pokemon:sv01-196','Gardevoir ex','Gardevoir ex','sv01','Escarlate e Violeta','196','pt','Rara Dupla','https://assets.tcgdex.net/pt/sv/sv01/196/high.webp'),
  ('pokemon','pokemon:en:base1-4','pokemon:base1-4','Charizard',NULL,'base1','Base Set','4','en','Rare Holo','https://assets.tcgdex.net/en/base/base1/4/high.webp');
