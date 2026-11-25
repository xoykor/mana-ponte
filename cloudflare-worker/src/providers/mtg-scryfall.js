/*
 * PROVEDOR MAGIC: THE GATHERING (SCRYFALL)
 * ========================================
 *
 * Consulta o catálogo oficial do Scryfall quando o D1 ainda não possui
 * impressões suficientes para a busca atual.
 *
 * Regra mantida: salvamos apenas metadados e a URL externa da imagem.
 */

const MAX_REMOTE_CARDS = 100;
const CACHE_TTL_SECONDS = 86400;

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
 * Converte o formato grande do Scryfall no formato normalizado do D1.
 */
function mapScryfallCard(card) {
  return {
    game: "mtg",
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
  const cleanSearch = String(search || "")
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
    if (safeSetCode) {
      terms.push("set:" + safeSetCode);
    }
  }

  if (language) {
    const safeLanguage = language.replace(/[^a-z]/gi, "");
    if (safeLanguage) {
      terms.push("lang:" + safeLanguage);
    }
  }

  return terms.join(" ");
}

/*
 * Faz GET no Scryfall aproveitando o cache de borda da Cloudflare quando disponível.
 */
async function cachedFetchJson(targetUrl) {
  const edgeCache = typeof caches !== "undefined" ? caches.default : null;
  const cacheKey = edgeCache
    ? new Request(targetUrl.toString(), { method: "GET" })
    : null;

  if (edgeCache && cacheKey) {
    const hit = await edgeCache.match(cacheKey);
    if (hit) {
      return { status: hit.status, ok: hit.ok, payload: await hit.json() };
    }
  }

  const response = await fetch(targetUrl, {
    headers: {
      "Accept": "application/json",
      "User-Agent": "MyTradeBox/1.0 (Cloudflare Worker)"
    }
  });

  if (response.status === 404) {
    return { status: 404, ok: false, payload: null };
  }

  if (!response.ok) {
    throw new Error("Scryfall respondeu HTTP " + response.status);
  }

  const payload = await response.json();

  if (edgeCache && cacheKey) {
    const cachedResponse = new Response(JSON.stringify(payload), {
      status: 200,
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": `public, max-age=${CACHE_TTL_SECONDS}`
      }
    });
    edgeCache.put(cacheKey, cachedResponse).catch(() => {});
  }

  return { status: 200, ok: true, payload };
}

/*
 * Consulta o Scryfall e percorre páginas até chegar ao teto configurado.
 */
export async function fetchScryfallCards(search, setCode, language) {
  const query = buildScryfallQuery(search, setCode, language);

  if (!query) {
    return [];
  }

  const firstUrl = new URL("https://api.scryfall.com/cards/search");
  firstUrl.searchParams.set("q", query);
  firstUrl.searchParams.set("include_extras", "false");
  firstUrl.searchParams.set("include_multilingual", "true");

  const cards = [];
  let nextUrl = firstUrl;

  while (nextUrl && cards.length < MAX_REMOTE_CARDS) {
    const result = await cachedFetchJson(nextUrl);

    if (result.status === 404 || !result.payload) {
      break;
    }

    for (const card of result.payload.data || []) {
      if (card.digital) {
        continue;
      }

      cards.push(mapScryfallCard(card));

      if (cards.length >= MAX_REMOTE_CARDS) {
        break;
      }
    }

    nextUrl =
      result.payload.has_more && result.payload.next_page
        ? new URL(result.payload.next_page)
        : null;
  }

  return cards;
}
