/*
 * ANÚNCIOS
 * ========
 *
 * Este módulo cuida de:
 *   - pesquisar anúncios;
 *   - ver um anúncio;
 *   - criar;
 *   - editar;
 *   - excluir.
 *
 * Importante: o user_id nunca vem do formulário.
 * Ele sempre vem da sessão autenticada.
 */

import {
  CONDITIONS,
  LISTING_MODES,
  csrfValid,
  json,
  positiveInt,
  priceToCents,
  readJson,
  requireSession
} from "./lib.js";

const DEFAULT_PAGE_SIZE = 24;
const MAX_PAGE_SIZE = 100;

/*
 * Regras de ordenação permitidas.
 *
 * O valor SQL vem de uma lista fixa criada por nós, nunca da entrada direta
 * do visitante. Isso evita SQL injection na cláusula ORDER BY.
 */
const SORT_SQL = {
  recent: "l.created_at DESC,l.id DESC",
  oldest: "l.created_at ASC,l.id ASC",
  price_asc: "(l.price_cents IS NULL),l.price_cents ASC,l.id DESC",
  price_desc: "(l.price_cents IS NULL),l.price_cents DESC,l.id DESC"
};

function addExactFilters(url, clauses, values) {
  const exactFilters = [
    ["card_id", "l.card_id=?", Number],
    ["set", "c.set_code=? COLLATE NOCASE", String],
    ["lang", "c.language=? COLLATE NOCASE", String],
    ["city", "u.city=? COLLATE NOCASE", String],
    ["state", "u.state=? COLLATE NOCASE", String],
    ["condition", "l.condition=?", String]
  ];

  for (const [parameter, sql, convert] of exactFilters) {
    const rawValue = url.searchParams.get(parameter);

    if (!rawValue) {
      continue;
    }

    const value = convert(rawValue);

    if (
      parameter === "condition" &&
      !CONDITIONS.has(value)
    ) {
      throw new Error("Condição inválida");
    }

    clauses.push(sql);
    values.push(value);
  }
}

async function addOwnerFilter(request, url, env, clauses, values) {
  const mine = (url.searchParams.get("mine") || "")
    .toLowerCase();

  const wantsOnlyOwnListings =
    mine === "1" ||
    mine === "true" ||
    mine === "yes";

  if (!wantsOnlyOwnListings) {
    return null;
  }

  const auth = await requireSession(
    request,
    env,
    "Faça login para ver seus anúncios"
  );

  if (auth.response) {
    return auth.response;
  }

  clauses.push("l.user_id=?");
  values.push(auth.session.user_id);

  return null;
}

function addModeFilter(url, clauses) {
  const mode = (url.searchParams.get("mode") || "")
    .trim();

  if (!mode) {
    return;
  }

  if (mode === "venda") {
    clauses.push("l.mode IN ('venda','ambos')");
    return;
  }

  if (mode === "troca") {
    clauses.push("l.mode IN ('troca','ambos')");
    return;
  }

  if (mode === "ambos") {
    clauses.push("l.mode='ambos'");
    return;
  }

  throw new Error("Modalidade inválida");
}

function addPriceFilters(url, clauses, values) {
  const minPrice = priceToCents(
    url.searchParams.get("min_price")
  );

  const maxPrice = priceToCents(
    url.searchParams.get("max_price")
  );

  if (
    minPrice != null &&
    maxPrice != null &&
    minPrice > maxPrice
  ) {
    throw new Error(
      "Preço mínimo não pode ser maior que o máximo"
    );
  }

  if (minPrice != null) {
    clauses.push("l.price_cents>=?");
    values.push(minPrice);
  }

  if (maxPrice != null) {
    clauses.push("l.price_cents<=?");
    values.push(maxPrice);
  }
}

function addCardNameFilter(url, clauses, values) {
  const cardSearch = (url.searchParams.get("card") || "")
    .trim()
    .slice(0, 100);

  if (!cardSearch) {
    return;
  }

  clauses.push(
    "(c.name LIKE ? COLLATE NOCASE " +
    "OR c.printed_name LIKE ? COLLATE NOCASE)"
  );

  values.push(
    "%" + cardSearch + "%",
    "%" + cardSearch + "%"
  );
}

/*
 * Constrói filtros da pesquisa de anúncios.
 */
async function buildListingFilters(request, url, env) {
  const clauses = [];
  const values = [];

  addExactFilters(url, clauses, values);

  const authResponse = await addOwnerFilter(
    request,
    url,
    env,
    clauses,
    values
  );

  if (authResponse) {
    return { response: authResponse };
  }

  addModeFilter(url, clauses);
  addPriceFilters(url, clauses, values);
  addCardNameFilter(url, clauses, values);

  const sort = (
    url.searchParams.get("sort") || "recent"
  ).toLowerCase();

  const sortSql = SORT_SQL[sort];

  if (!sortSql) {
    throw new Error("Ordenação inválida");
  }

  const page = positiveInt(
    url.searchParams.get("page"),
    1,
    100000
  );

  const limit = positiveInt(
    url.searchParams.get("limit"),
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE
  );

  return {
    where: clauses.length
      ? " WHERE " + clauses.join(" AND ")
      : "",
    values,
    sort,
    sortSql,
    page,
    limit
  };
}

/*
 * Transforma JSON do formulário em um objeto consistente.
 *
 * current é usado no PATCH. Se um campo não veio na requisição, preservamos
 * o valor existente.
 */
function listingInput(data, current = null) {
  const fallback = current || {};

  const cardId = Number(
    data.card_id == null
      ? fallback.card_id
      : data.card_id
  );

  const title = String(
    data.title == null
      ? fallback.title || ""
      : data.title
  ).trim();

  const description = String(
    data.description == null
      ? fallback.description || ""
      : data.description
  ).trim();

  const condition = String(
    data.condition == null
      ? fallback.condition || ""
      : data.condition
  );

  const mode = String(
    data.mode == null
      ? fallback.mode || ""
      : data.mode
  );

  const rawPrice =
    data.price_cents == null
      ? fallback.price_cents
      : data.price_cents;

  const priceCents =
    rawPrice == null || rawPrice === ""
      ? null
      : Number(rawPrice);

  return {
    cardId,
    title,
    description,
    condition,
    mode,
    priceCents
  };
}

function validateListingInput(input) {
  if (
    !Number.isInteger(input.cardId) ||
    input.cardId <= 0
  ) {
    throw new Error("Carta inválida");
  }

  if (
    input.title.length < 3 ||
    input.title.length > 120 ||
    input.description.length > 1000
  ) {
    throw new Error(
      "Título deve ter 3–120 caracteres e descrição no máximo 1000"
    );
  }

  if (
    !CONDITIONS.has(input.condition) ||
    !LISTING_MODES.has(input.mode)
  ) {
    throw new Error("Condição ou modalidade inválida");
  }

  if (
    input.priceCents != null &&
    (
      !Number.isInteger(input.priceCents) ||
      input.priceCents < 0
    )
  ) {
    throw new Error("Preço inválido");
  }
}

async function cardLanguage(env, cardId) {
  const card = await env.DB.prepare(
    "SELECT language FROM cards WHERE id=?"
  )
    .bind(cardId)
    .first();

  if (!card) {
    throw new Error("Carta não encontrada");
  }

  return card.language || "en";
}

function validCsrfResponse(request, session) {
  if (csrfValid(request, session)) {
    return null;
  }

  return json({ error: "Token CSRF inválido" }, 403);
}

/*
 * GET /api/listings
 */
export async function getListings(request, url, env) {
  const filters = await buildListingFilters(
    request,
    url,
    env
  );

  if (filters.response) {
    return filters.response;
  }

  const countRow = await env.DB.prepare(
    "SELECT COUNT(*) AS total " +
    "FROM listings l " +
    "JOIN cards c ON c.id=l.card_id " +
    "JOIN users u ON u.id=l.user_id" +
    filters.where
  )
    .bind(...filters.values)
    .first();

  const offset = (filters.page - 1) * filters.limit;

  const result = await env.DB.prepare(
    "SELECT " +
    "l.id,l.card_id,l.user_id," +
    "c.name,c.printed_name,c.set_code,c.set_name,c.collector_number," +
    "c.image_url,c.language AS language," +
    "u.username,u.display_name,u.city,u.state," +
    "l.title,l.description,l.price_cents,l.condition,l.mode," +
    "l.contact_url,l.created_at " +
    "FROM listings l " +
    "JOIN cards c ON c.id=l.card_id " +
    "JOIN users u ON u.id=l.user_id" +
    filters.where + " " +
    "ORDER BY " + filters.sortSql + " " +
    "LIMIT ? OFFSET ?"
  )
    .bind(
      ...filters.values,
      filters.limit,
      offset
    )
    .all();

  return json({
    listings: result.results || [],
    total: Number((countRow && countRow.total) || 0),
    page: filters.page,
    limit: filters.limit,
    sort: filters.sort
  });
}

/*
 * GET /api/listings/:id
 */
export async function getListing(id, env) {
  const listing = await env.DB.prepare(
    "SELECT " +
    "l.id,l.card_id,l.user_id,l.title,l.description,l.price_cents," +
    "l.condition,l.mode,l.contact_url,l.created_at," +
    "c.name,c.printed_name,c.set_code,c.set_name,c.collector_number," +
    "c.language,c.image_url," +
    "u.username,u.display_name,u.phone,u.city,u.state " +
    "FROM listings l " +
    "JOIN cards c ON c.id=l.card_id " +
    "JOIN users u ON u.id=l.user_id " +
    "WHERE l.id=?"
  )
    .bind(id)
    .first();

  if (!listing) {
    return json(
      { error: "Anúncio não encontrado" },
      404
    );
  }

  return json({ listing });
}

/*
 * POST /api/listings
 */
export async function createListing(request, env) {
  const auth = await requireSession(
    request,
    env,
    "Faça login para anunciar"
  );

  if (auth.response) {
    return auth.response;
  }

  const csrfError = validCsrfResponse(
    request,
    auth.session
  );

  if (csrfError) {
    return csrfError;
  }

  const data = await readJson(request);
  const input = listingInput(data);

  validateListingInput(input);

  const language = await cardLanguage(
    env,
    input.cardId
  );

  const insertResult = await env.DB.prepare(
    "INSERT INTO listings(" +
    "card_id,user_id,title,description,price_cents," +
    "condition,language,mode" +
    ") VALUES(?,?,?,?,?,?,?,?)"
  )
    .bind(
      input.cardId,
      auth.session.user_id,
      input.title,
      input.description,
      input.priceCents,
      input.condition,
      language,
      input.mode
    )
    .run();

  return json(
    {
      id: Number(
        insertResult.meta &&
        insertResult.meta.last_row_id
      ),
      message: "Oferta publicada"
    },
    201
  );
}

/*
 * PATCH /api/listings/:id
 */
export async function updateListing(request, id, env) {
  const auth = await requireSession(
    request,
    env,
    "Faça login para editar anúncios"
  );

  if (auth.response) {
    return auth.response;
  }

  const csrfError = validCsrfResponse(
    request,
    auth.session
  );

  if (csrfError) {
    return csrfError;
  }

  /*
   * Procuramos id + user_id juntos.
   * Assim, um usuário não consegue editar anúncio de outra pessoa.
   */
  const current = await env.DB.prepare(
    "SELECT * FROM listings " +
    "WHERE id=? AND user_id=?"
  )
    .bind(id, auth.session.user_id)
    .first();

  if (!current) {
    return json(
      { error: "Anúncio não encontrado" },
      404
    );
  }

  const data = await readJson(request);
  const input = listingInput(data, current);

  validateListingInput(input);

  const language = await cardLanguage(
    env,
    input.cardId
  );

  await env.DB.prepare(
    "UPDATE listings SET " +
    "card_id=?,title=?,description=?,price_cents=?," +
    "condition=?,language=?,mode=? " +
    "WHERE id=? AND user_id=?"
  )
    .bind(
      input.cardId,
      input.title,
      input.description,
      input.priceCents,
      input.condition,
      language,
      input.mode,
      id,
      auth.session.user_id
    )
    .run();

  return json({
    id,
    message: "Anúncio atualizado"
  });
}

/*
 * DELETE /api/listings/:id
 */
export async function deleteListing(request, id, env) {
  const auth = await requireSession(
    request,
    env,
    "Faça login para remover anúncios"
  );

  if (auth.response) {
    return auth.response;
  }

  const csrfError = validCsrfResponse(
    request,
    auth.session
  );

  if (csrfError) {
    return csrfError;
  }

  const current = await env.DB.prepare(
    "SELECT id FROM listings " +
    "WHERE id=? AND user_id=?"
  )
    .bind(id, auth.session.user_id)
    .first();

  if (!current) {
    return json(
      { error: "Anúncio não encontrado" },
      404
    );
  }

  await env.DB.prepare(
    "DELETE FROM listings " +
    "WHERE id=? AND user_id=?"
  )
    .bind(id, auth.session.user_id)
    .run();

  return json({
    message: "Anúncio removido"
  });
}
