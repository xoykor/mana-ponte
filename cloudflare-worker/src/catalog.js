/*
 * CATÁLOGO DE CARTAS (MULTI-TCG: MAGIC & POKÉMON)
 * ===============================================
 *
 * Estratégia:
 *   1. procurar primeiro no D1;
 *   2. se houver poucos resultados, consultar Scryfall (Magic) e/ou TCGdex (Pokémon);
 *   3. salvar somente metadados e URL externa da imagem;
 *   4. reler a página final do D1.
 *
 * O projeto NÃO armazena bytes de imagens.
 */

import { GAMES, badRequest, json, positiveInt } from "./lib.js";
import { fetchScryfallCards } from "./providers/mtg-scryfall.js";
import { fetchPokemonCards } from "./providers/pokemon-tcgdex.js";

const UPSERT_BATCH_SIZE = 50;

/*
 * Insere cartas novas e atualiza cartas que já existem.
 *
 * "upsert" = update + insert.
 */
async function upsertCards(env, cards) {
  const statements = cards.map(card => {
    return env.DB.prepare(
      "INSERT INTO cards(" +
      "game,scryfall_id,oracle_id,name,printed_name,set_code,set_name," +
      "collector_number,language,rarity,image_url,updated_at" +
      ") VALUES(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) " +
      "ON CONFLICT(scryfall_id) DO UPDATE SET " +
      "game=excluded.game," +
      "oracle_id=excluded.oracle_id," +
      "name=excluded.name," +
      "printed_name=excluded.printed_name," +
      "set_code=excluded.set_code," +
      "set_name=excluded.set_name," +
      "collector_number=excluded.collector_number," +
      "language=excluded.language," +
      "rarity=excluded.rarity," +
      "image_url=excluded.image_url," +
      "updated_at=CURRENT_TIMESTAMP"
    ).bind(
      card.game || "mtg",
      card.scryfall_id,
      card.oracle_id,
      card.name,
      card.printed_name,
      card.set_code,
      card.set_name,
      card.collector_number,
      card.language,
      card.rarity,
      card.image_url
    );
  });

  /*
   * Mandamos blocos de 50 statements por vez.
   * Isso evita criar um batch enorme de uma só vez.
   */
  for (
    let start = 0;
    start < statements.length;
    start += UPSERT_BATCH_SIZE
  ) {
    const batch = statements.slice(
      start,
      start + UPSERT_BATCH_SIZE
    );

    await env.DB.batch(batch);
  }
}

/*
 * Traduz parâmetros da URL em:
 *   - cláusulas SQL;
 *   - valores para bind().
 *
 * O SQL usa ? e bind() para evitar concatenar entrada do usuário diretamente.
 */
function filtersFromUrl(url) {
  const clauses = [];
  const values = [];

  const game = (url.searchParams.get("game") || "")
    .trim()
    .toLowerCase();

  if (game && !GAMES.has(game)) {
    throw new Error("Jogo inválido");
  }

  const search = (url.searchParams.get("q") || "")
    .trim()
    .slice(0, 100);

  const setCode = (url.searchParams.get("set") || "")
    .trim()
    .slice(0, 24);

  const language = (url.searchParams.get("lang") || "")
    .trim()
    .slice(0, 8);

  if (game) {
    clauses.push("game=?");
    values.push(game);
  }

  if (search) {
    clauses.push(
      "(name LIKE ? COLLATE NOCASE " +
      "OR printed_name LIKE ? COLLATE NOCASE)"
    );

    values.push(
      "%" + search + "%",
      "%" + search + "%"
    );
  }

  if (setCode) {
    clauses.push("set_code=? COLLATE NOCASE");
    values.push(setCode);
  }

  if (language) {
    clauses.push("language=? COLLATE NOCASE");
    values.push(language);
  }

  const where = clauses.length
    ? " WHERE " + clauses.join(" AND ")
    : "";

  return {
    game,
    search,
    setCode,
    language,
    where,
    values
  };
}

async function countCards(env, filters) {
  const row = await env.DB.prepare(
    "SELECT COUNT(*) AS total FROM cards" + filters.where
  )
    .bind(...filters.values)
    .first();

  return Number((row && row.total) || 0);
}

async function readCardsPage(env, filters, page, limit) {
  const offset = (page - 1) * limit;

  const result = await env.DB.prepare(
    "SELECT " +
    "id,game,scryfall_id,oracle_id,name,printed_name,set_code,set_name," +
    "collector_number,language,rarity,image_url " +
    "FROM cards" +
    filters.where + " " +
    "ORDER BY (image_url IS NULL),name COLLATE NOCASE,set_code,collector_number " +
    "LIMIT ? OFFSET ?"
  )
    .bind(...filters.values, limit, offset)
    .all();

  return result.results || [];
}

async function enrichFromProviders(filters) {
  const tasks = [];
  const sources = [];

  const wantMtg = !filters.game || filters.game === "mtg";
  const wantPokemon = !filters.game || filters.game === "pokemon";

  if (wantMtg && filters.search.length >= 3) {
    tasks.push(
      fetchScryfallCards(
        filters.search,
        filters.setCode,
        filters.language
      ).then(cards => ({ name: "scryfall", cards }))
    );
  }

  if (wantPokemon && filters.search.length >= 2) {
    tasks.push(
      fetchPokemonCards(
        filters.search,
        filters.setCode,
        filters.language
      ).then(cards => ({ name: "tcgdex", cards }))
    );
  }

  if (!tasks.length) {
    return { cards: [], sources: [] };
  }

  const settled = await Promise.allSettled(tasks);
  const collected = [];

  for (const outcome of settled) {
    if (outcome.status === "fulfilled") {
      if (outcome.value.cards.length > 0) {
        collected.push(...outcome.value.cards);
        sources.push(outcome.value.name);
      }
    } else {
      console.log(
        "Remote catalog enrichment failed:",
        outcome.reason && outcome.reason.message
          ? outcome.reason.message
          : outcome.reason
      );
    }
  }

  return { cards: collected, sources };
}

/*
 * GET /api/cards
 */
export async function getCards(url, env) {
  const page = positiveInt(
    url.searchParams.get("page"),
    1,
    100000
  );

  const limit = positiveInt(
    url.searchParams.get("limit"),
    24,
    100
  );

  const filters = filtersFromUrl(url);

  let source = "local";
  let total = await countCards(env, filters);

  const minQueryLength = filters.game === "pokemon" ? 2 : 2;
  const shouldEnrich =
    filters.search.length >= minQueryLength &&
    total < limit;

  if (shouldEnrich) {
    const { cards: remoteCards, sources } = await enrichFromProviders(filters);

    if (remoteCards.length > 0) {
      await upsertCards(env, remoteCards);
      source = sources.join("+") || "remote";
      total = await countCards(env, filters);
    }
  }

  const cards = await readCardsPage(
    env,
    filters,
    page,
    limit
  );

  return json({
    cards,
    page,
    limit,
    total,
    source
  });
}

/*
 * GET /api/sets
 *
 * Só aparecem coleções que já possuem alguma impressão no D1.
 * Aceita filtro opcional ?game=mtg|pokemon.
 */
export async function getSets(url, env) {
  const game = (url && url.searchParams
    ? url.searchParams.get("game") || ""
    : ""
  )
    .trim()
    .toLowerCase();

  if (game && !GAMES.has(game)) {
    return badRequest("Jogo inválido");
  }

  const where = game ? "WHERE game=? " : "";
  const statement = env.DB.prepare(
    "SELECT game,set_code,set_name,COUNT(*) AS card_count " +
    "FROM cards " +
    where +
    "GROUP BY game,set_code,set_name " +
    "ORDER BY set_name COLLATE NOCASE"
  );

  const result = game
    ? await statement.bind(game).all()
    : await statement.all();

  return json({
    sets: result.results || []
  });
}
