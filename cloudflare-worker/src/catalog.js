/*
 * CATÁLOGO DE CARTAS
 * ==================
 *
 * Estratégia:
 *   1. procurar primeiro no D1;
 *   2. se houver poucos resultados, consultar o Scryfall;
 *   3. salvar somente metadados e URL externa da imagem;
 *   4. reler a página final do D1.
 *
 * O ManaPonte NÃO armazena bytes de imagens.
 */

import { json, positiveInt } from "./lib.js";

const MAX_REMOTE_CARDS = 100;
const UPSERT_BATCH_SIZE = 50;

/*
 * Algumas cartas do Scryfall possuem image_uris diretamente.
 * Cartas de múltiplas faces podem guardar a imagem dentro de card_faces.
 */
function readNormalImageUrl(card) {
  if (card.image_uris && card.image_uris.normal) {
    return card.image_uris.normal;
  }

  if (Array.isArray(card.card_faces)) {
    const faceWithImage = card.card_faces.find(
      face => face.image_uris && face.image_uris.normal
    );

    if (faceWithImage) {
      return faceWithImage.image_uris.normal;
    }
  }

  return null;
}

/*
 * Converte o formato grande do Scryfall no formato pequeno que nosso banco usa.
 */
function mapScryfallCard(card) {
  return {
    scryfall_id: card.id,
    oracle_id: card.oracle_id || null,
    name: card.name,
    printed_name: card.printed_name || null,
    set_code: card.set,
    set_name: card.set_name,
    collector_number: card.collector_number,
    language: card.lang || "en",
    rarity: card.rarity || "common",
    image_url: readNormalImageUrl(card)
  };
}

/*
 * Monta a expressão de busca aceita pela API do Scryfall.
 */
function buildScryfallQuery(search, setCode, language) {
  const cleanSearch = search
    .replace(/["\\]/g, " ")
    .trim();

  if (cleanSearch.length < 3) {
    return null;
  }

  const terms = [
    'name:"' + cleanSearch + '"',
    "unique:prints"
  ];

  if (setCode) {
    const safeSetCode = setCode.replace(/[^a-z0-9]/gi, "");
    terms.push("set:" + safeSetCode);
  }

  if (language) {
    const safeLanguage = language.replace(/[^a-z]/gi, "");
    terms.push("lang:" + safeLanguage);
  }

  return terms.join(" ");
}

/*
 * Consulta o Scryfall e percorre páginas até chegar ao nosso teto.
 */
async function fetchScryfall(search, setCode, language) {
  const query = buildScryfallQuery(
    search,
    setCode,
    language
  );

  if (!query) {
    return [];
  }

  const firstUrl = new URL(
    "https://api.scryfall.com/cards/search"
  );

  firstUrl.searchParams.set("q", query);
  firstUrl.searchParams.set("include_extras", "false");
  firstUrl.searchParams.set("include_multilingual", "true");

  const cards = [];
  let nextUrl = firstUrl;

  while (nextUrl && cards.length < MAX_REMOTE_CARDS) {
    const response = await fetch(nextUrl, {
      headers: {
        "Accept": "application/json",
        "User-Agent": "ManaPonte/1.0 (Cloudflare Worker)"
      }
    });

    // O Scryfall usa 404 para "nenhuma carta encontrada".
    if (response.status === 404) {
      break;
    }

    if (!response.ok) {
      throw new Error(
        "Scryfall respondeu HTTP " + response.status
      );
    }

    const payload = await response.json();

    for (const card of payload.data || []) {
      // O ManaPonte anuncia cartas físicas.
      if (card.digital) {
        continue;
      }

      cards.push(mapScryfallCard(card));

      if (cards.length >= MAX_REMOTE_CARDS) {
        break;
      }
    }

    nextUrl =
      payload.has_more && payload.next_page
        ? new URL(payload.next_page)
        : null;
  }

  return cards;
}

/*
 * Insere cartas novas e atualiza cartas que já existem.
 *
 * "upsert" = update + insert.
 */
async function upsertCards(env, cards) {
  const statements = cards.map(card => {
    return env.DB.prepare(
      "INSERT INTO cards(" +
      "scryfall_id,oracle_id,name,printed_name,set_code,set_name," +
      "collector_number,language,rarity,image_url,updated_at" +
      ") VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) " +
      "ON CONFLICT(scryfall_id) DO UPDATE SET " +
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

  const search = (url.searchParams.get("q") || "")
    .trim()
    .slice(0, 100);

  const setCode = (url.searchParams.get("set") || "")
    .trim()
    .slice(0, 16);

  const language = (url.searchParams.get("lang") || "")
    .trim()
    .slice(0, 8);

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
    "id,scryfall_id,oracle_id,name,printed_name,set_code,set_name," +
    "collector_number,language,rarity,image_url " +
    "FROM cards" +
    filters.where + " " +
    "ORDER BY name COLLATE NOCASE,set_code,collector_number " +
    "LIMIT ? OFFSET ?"
  )
    .bind(...filters.values, limit, offset)
    .all();

  return result.results || [];
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

  const shouldTryScryfall =
    filters.search.length >= 3 &&
    total < limit;

  if (shouldTryScryfall) {
    try {
      const remoteCards = await fetchScryfall(
        filters.search,
        filters.setCode,
        filters.language
      );

      if (remoteCards.length > 0) {
        await upsertCards(env, remoteCards);

        source = "scryfall";

        // O total pode ter mudado depois do upsert.
        total = await countCards(env, filters);
      }
    } catch (error) {
      /*
       * O Scryfall é enriquecimento. Se estiver fora do ar, ainda devolvemos
       * o que já existe no nosso D1.
       */
      console.log(
        "Scryfall search failed:",
        error && error.message ? error.message : error
      );
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
 */
export async function getSets(env) {
  const result = await env.DB.prepare(
    "SELECT set_code,set_name,COUNT(*) AS card_count " +
    "FROM cards " +
    "GROUP BY set_code,set_name " +
    "ORDER BY set_name COLLATE NOCASE"
  ).all();

  return json({
    sets: result.results || []
  });
}
