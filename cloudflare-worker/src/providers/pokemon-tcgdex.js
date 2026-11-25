/*
 * PROVEDOR POKÉMON TCG (TCGDEX GRAPHQL V2)
 * ========================================
 *
 * Consulta o TCGdex (gratuito, open-source e multilíngue) em uma única
 * chamada GraphQL, retornando metadados em português/inglês/outros idiomas
 * e URLs externas diretas da CDN oficial do TCGdex.
 *
 * Nenhum byte de imagem é armazenado no D1.
 */

const TCGDEX_GRAPHQL_URL = "https://api.tcgdex.net/v2/graphql";
const ITEMS_PER_LOCALE = 50;
const CACHE_TTL_SECONDS = 86400;

/*
 * Mapa estrito entre os códigos de idioma da interface e os locales aceitos
 * pela diretiva @locale(lang: "...") do TCGdex.
 */
const TCGDEX_LOCALES = {
  pt: "pt",
  en: "en",
  es: "es",
  fr: "fr",
  de: "de",
  it: "it",
  ja: "ja",
  ko: "ko",
  zht: "zh-tw",
  zhs: "zh-cn"
};

function formatImageUrl(rawUrl) {
  const clean = String(rawUrl || "").trim();
  if (!clean) {
    return null;
  }

  if (/\.(webp|png|jpe?g)$/i.test(clean)) {
    return clean;
  }

  return `${clean.replace(/\/+$/, "")}/high.webp`;
}

function mapPokemonCard(card, langCode, enFallback) {
  if (!card || !card.id) {
    return null;
  }

  const rawId = String(card.id).trim();
  const setCode = String(
    (card.set && card.set.id) || rawId.split("-")[0] || "pkm"
  ).toLowerCase();
  const setName = String(
    (card.set && card.set.name) ||
    (enFallback && enFallback.set && enFallback.set.name) ||
    setCode.toUpperCase()
  );
  const localName = String(card.name || "").trim();
  const canonicalName = String(
    (enFallback && enFallback.name) || localName || "Carta Pokémon"
  ).trim();
  const imageUrl =
    formatImageUrl(card.image) ||
    formatImageUrl(enFallback && enFallback.image);
  const rarity =
    card.rarity && card.rarity !== "None"
      ? String(card.rarity)
      : "common";

  return {
    game: "pokemon",
    // Cada idioma recebe sua própria chave única para não sobrescrever traduções.
    scryfall_id: `pokemon:${langCode}:${rawId}`,
    // oracle_id sem o idioma agrupa traduções da mesma carta/coleção nos matches.
    oracle_id: `pokemon:${rawId}`,
    name: canonicalName,
    printed_name: langCode === "en" ? null : (localName || null),
    set_code: setCode,
    set_name: setName,
    collector_number: String(card.localId || "0"),
    language: langCode,
    rarity,
    image_url: imageUrl
  };
}

async function queryTcgdexGraphql(cleanSearch, primaryLangCode, primaryLocale, includeEnBoth) {
  const cacheUrl = new URL("https://cache.manaponte.internal/tcgdex-v2");
  cacheUrl.searchParams.set("q", cleanSearch.toLowerCase());
  cacheUrl.searchParams.set("lang", primaryLangCode || "all");

  const edgeCache = typeof caches !== "undefined" ? caches.default : null;
  const cacheKey = edgeCache
    ? new Request(cacheUrl.toString(), { method: "GET" })
    : null;

  if (edgeCache && cacheKey) {
    const hit = await edgeCache.match(cacheKey);
    if (hit) {
      return await hit.json();
    }
  }

  const fields = "id localId name rarity image set { id name }";
  const query = primaryLocale === "en"
    ? `query($name: String) {
        en: cards(filters: { name: $name }, pagination: { page: 1, itemsPerPage: ${ITEMS_PER_LOCALE} }) @locale(lang: "en") { ${fields} }
      }`
    : `query($name: String) {
        primary: cards(filters: { name: $name }, pagination: { page: 1, itemsPerPage: ${ITEMS_PER_LOCALE} }) @locale(lang: "${primaryLocale}") { ${fields} }
        en: cards(filters: { name: $name }, pagination: { page: 1, itemsPerPage: ${ITEMS_PER_LOCALE} }) @locale(lang: "en") { ${fields} }
      }`;

  const response = await fetch(TCGDEX_GRAPHQL_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "User-Agent": "MyTradeBox/1.0 (Cloudflare Worker)"
    },
    body: JSON.stringify({
      query,
      variables: { name: cleanSearch }
    })
  });

  if (!response.ok) {
    throw new Error("TCGdex respondeu HTTP " + response.status);
  }

  const payload = await response.json();
  if (payload.errors && payload.errors.length > 0 && !payload.data) {
    throw new Error("Erro na consulta TCGdex");
  }

  const data = payload.data || {};
  const result = {
    primary: Array.isArray(data.primary) ? data.primary : [],
    en: Array.isArray(data.en) ? data.en : [],
    includeEnBoth: Boolean(includeEnBoth)
  };

  if (edgeCache && cacheKey) {
    const cachedResponse = new Response(JSON.stringify(result), {
      status: 200,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": `public, max-age=${CACHE_TTL_SECONDS}`
      }
    });
    edgeCache.put(cacheKey, cachedResponse).catch(() => {});
  }

  return result;
}

/*
 * Consulta o TCGdex e normaliza impressões de Pokémon para o formato do D1.
 */
export async function fetchPokemonCards(search, _setCode, language) {
  const cleanSearch = String(search || "")
    .replace(/["\\]/g, " ")
    .trim();

  if (cleanSearch.length < 2) {
    return [];
  }

  const normalizedLang = String(language || "").trim().toLowerCase();

  if (normalizedLang && !Object.hasOwn(TCGDEX_LOCALES, normalizedLang)) {
    // Idiomas exclusivos de Magic (ex.: Phyrexiano/Quenya) não existem no Pokémon.
    return [];
  }

  // Sem filtro de idioma, trazemos Português e Inglês na mesma requisição.
  const primaryLangCode = normalizedLang || "pt";
  const primaryLocale = TCGDEX_LOCALES[primaryLangCode];
  const includeEnBoth = !normalizedLang;

  const { primary, en } = await queryTcgdexGraphql(
    cleanSearch,
    normalizedLang,
    primaryLocale,
    includeEnBoth
  );

  const enById = new Map(
    en.filter(item => item && item.id).map(item => [item.id, item])
  );

  const mapped = [];

  if (primaryLocale === "en") {
    for (const card of en) {
      const entry = mapPokemonCard(card, "en", card);
      if (entry) {
        mapped.push(entry);
      }
    }
    return mapped;
  }

  for (const card of primary) {
    const entry = mapPokemonCard(card, primaryLangCode, enById.get(card.id));
    if (entry) {
      mapped.push(entry);
    }
  }

  if (includeEnBoth) {
    for (const card of en) {
      const entry = mapPokemonCard(card, "en", card);
      if (entry) {
        mapped.push(entry);
      }
    }
  }

  return mapped;
}
