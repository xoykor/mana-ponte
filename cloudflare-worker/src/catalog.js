
import { json, positiveInt } from "./lib.js";

const MAX_REMOTE_CARDS = 100;

function mapScryfallCard(card) {
  let imageUrl = null;
  if (card.image_uris && card.image_uris.normal) {
    imageUrl = card.image_uris.normal;
  } else if (Array.isArray(card.card_faces)) {
    const face = card.card_faces.find(item => item.image_uris && item.image_uris.normal);
    if (face) imageUrl = face.image_uris.normal;
  }

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
    image_url: imageUrl
  };
}

async function fetchScryfall(search, setCode, language) {
  const clean = search.replace(/["\\]/g, " ").trim();
  if (clean.length < 3) return [];

  const terms = ['name:"' + clean + '"', "unique:prints"];
  if (setCode) terms.push("set:" + setCode.replace(/[^a-z0-9]/gi, ""));
  if (language) terms.push("lang:" + language.replace(/[^a-z]/gi, ""));

  const first = new URL("https://api.scryfall.com/cards/search");
  first.searchParams.set("q", terms.join(" "));
  first.searchParams.set("include_extras", "false");
  first.searchParams.set("include_multilingual", "true");

  const cards = [];
  let next = first;

  while (next && cards.length < MAX_REMOTE_CARDS) {
    const response = await fetch(next, {
      headers: {
        "Accept": "application/json",
        "User-Agent": "ManaPonte/1.0 (Cloudflare Worker)"
      }
    });

    if (response.status === 404) break;
    if (!response.ok) {
      throw new Error("Scryfall respondeu HTTP " + response.status);
    }

    const payload = await response.json();
    for (const card of payload.data || []) {
      if (card.digital) continue;
      cards.push(mapScryfallCard(card));
      if (cards.length >= MAX_REMOTE_CARDS) break;
    }

    next = payload.has_more && payload.next_page
      ? new URL(payload.next_page)
      : null;
  }

  return cards;
}

async function upsertCards(env, cards) {
  const statements = cards.map(card => env.DB.prepare(
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
  ));

  for (let i = 0; i < statements.length; i += 50) {
    await env.DB.batch(statements.slice(i, i + 50));
  }
}

function filtersFromUrl(url) {
  const clauses = [];
  const values = [];

  const search = (url.searchParams.get("q") || "").trim().slice(0, 100);
  const setCode = (url.searchParams.get("set") || "").trim().slice(0, 16);
  const language = (url.searchParams.get("lang") || "").trim().slice(0, 8);

  if (search) {
    clauses.push("(name LIKE ? COLLATE NOCASE OR printed_name LIKE ? COLLATE NOCASE)");
    values.push("%" + search + "%", "%" + search + "%");
  }
  if (setCode) {
    clauses.push("set_code=? COLLATE NOCASE");
    values.push(setCode);
  }
  if (language) {
    clauses.push("language=? COLLATE NOCASE");
    values.push(language);
  }

  return {
    search,
    setCode,
    language,
    where: clauses.length ? " WHERE " + clauses.join(" AND ") : "",
    values
  };
}

export async function getCards(url, env) {
  const page = positiveInt(url.searchParams.get("page"), 1, 100000);
  const limit = positiveInt(url.searchParams.get("limit"), 24, 100);
  const filters = filtersFromUrl(url);
  let source = "local";

  let count = await env.DB.prepare(
    "SELECT COUNT(*) AS total FROM cards" + filters.where
  ).bind(...filters.values).first();
  let total = Number((count && count.total) || 0);

  if (filters.search.length >= 3 && total < limit) {
    try {
      const remote = await fetchScryfall(
        filters.search,
        filters.setCode,
        filters.language
      );
      if (remote.length) {
        await upsertCards(env, remote);
        source = "scryfall";
        count = await env.DB.prepare(
          "SELECT COUNT(*) AS total FROM cards" + filters.where
        ).bind(...filters.values).first();
        total = Number((count && count.total) || 0);
      }
    } catch (error) {
      console.log("Scryfall search failed:", error && error.message ? error.message : error);
    }
  }

  const result = await env.DB.prepare(
    "SELECT id,scryfall_id,oracle_id,name,printed_name,set_code,set_name," +
    "collector_number,language,rarity,image_url " +
    "FROM cards" + filters.where + " " +
    "ORDER BY name COLLATE NOCASE,set_code,collector_number LIMIT ? OFFSET ?"
  ).bind(...filters.values, limit, (page - 1) * limit).all();

  return json({
    cards: result.results || [],
    page,
    limit,
    total,
    source
  });
}

export async function getSets(env) {
  const result = await env.DB.prepare(
    "SELECT set_code,set_name,COUNT(*) AS card_count " +
    "FROM cards GROUP BY set_code,set_name ORDER BY set_name COLLATE NOCASE"
  ).all();
  return json({ sets: result.results || [] });
}
