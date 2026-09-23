/*
 * DESEJOS, MATCHES E PERFIS PÚBLICOS
 * ===================================
 *
 * "want" é uma carta que o usuário procura.
 *
 * "match" é um anúncio de outra pessoa que combina com algum desejo.
 */

import {
  CONDITIONS,
  WANT_MODES,
  csrfValid,
  json,
  positiveInt,
  readJson,
  requireSession
} from "./lib.js";

function csrfErrorResponse(request, session) {
  if (csrfValid(request, session)) {
    return null;
  }

  return json(
    { error: "Token CSRF inválido" },
    403
  );
}

/*
 * Converte o corpo do formulário em valores simples.
 */
function wantInput(data) {
  const cardId = Number(data.card_id);

  const maxPrice =
    data.max_price_cents == null ||
    data.max_price_cents === ""
      ? null
      : Number(data.max_price_cents);

  const condition = data.desired_condition
    ? String(data.desired_condition)
    : null;

  const language = data.desired_language
    ? String(data.desired_language)
        .trim()
        .slice(0, 8)
    : null;

  const mode = String(data.mode || "ambos");

  return {
    cardId,
    maxPrice,
    condition,
    language,
    mode
  };
}

function validateWantInput(input) {
  if (
    !Number.isInteger(input.cardId) ||
    input.cardId <= 0
  ) {
    throw new Error("Carta inválida");
  }

  if (
    input.maxPrice != null &&
    (
      !Number.isInteger(input.maxPrice) ||
      input.maxPrice < 0
    )
  ) {
    throw new Error("Preço máximo inválido");
  }

  if (
    input.condition &&
    !CONDITIONS.has(input.condition)
  ) {
    throw new Error("Condição desejada inválida");
  }

  if (!WANT_MODES.has(input.mode)) {
    throw new Error("Modalidade inválida");
  }
}

/*
 * GET /api/wants
 */
export async function getWants(request, url, env) {
  const auth = await requireSession(
    request,
    env,
    "Faça login para ver seus desejos"
  );

  if (auth.response) {
    return auth.response;
  }

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

  const countRow = await env.DB.prepare(
    "SELECT COUNT(*) AS total " +
    "FROM wants WHERE user_id=?"
  )
    .bind(auth.session.user_id)
    .first();

  const offset = (page - 1) * limit;

  const result = await env.DB.prepare(
    "SELECT " +
    "w.id,w.card_id,w.user_id,w.max_price_cents," +
    "w.desired_condition,w.desired_language,w.mode,w.created_at," +
    "c.name,c.printed_name,c.set_code,c.set_name," +
    "c.collector_number,c.language,c.image_url " +
    "FROM wants w " +
    "JOIN cards c ON c.id=w.card_id " +
    "WHERE w.user_id=? " +
    "ORDER BY w.id DESC " +
    "LIMIT ? OFFSET ?"
  )
    .bind(
      auth.session.user_id,
      limit,
      offset
    )
    .all();

  return json({
    wants: result.results || [],
    total: Number((countRow && countRow.total) || 0),
    page,
    limit
  });
}

/*
 * POST /api/wants
 */
export async function createWant(request, env) {
  const auth = await requireSession(
    request,
    env,
    "Faça login para salvar desejos"
  );

  if (auth.response) {
    return auth.response;
  }

  const csrfError = csrfErrorResponse(
    request,
    auth.session
  );

  if (csrfError) {
    return csrfError;
  }

  const data = await readJson(request);
  const input = wantInput(data);

  validateWantInput(input);

  const card = await env.DB.prepare(
    "SELECT id FROM cards WHERE id=?"
  )
    .bind(input.cardId)
    .first();

  if (!card) {
    throw new Error("Carta não encontrada");
  }

  /*
   * Existe UNIQUE(card_id, user_id).
   *
   * Por isso, se a pessoa salvar a mesma carta novamente, atualizamos o desejo
   * existente em vez de criar uma linha duplicada.
   */
  await env.DB.prepare(
    "INSERT INTO wants(" +
    "card_id,user_id,max_price_cents,desired_condition," +
    "desired_language,mode" +
    ") VALUES(?,?,?,?,?,?) " +
    "ON CONFLICT(card_id,user_id) DO UPDATE SET " +
    "max_price_cents=excluded.max_price_cents," +
    "desired_condition=excluded.desired_condition," +
    "desired_language=excluded.desired_language," +
    "mode=excluded.mode," +
    "created_at=CURRENT_TIMESTAMP"
  )
    .bind(
      input.cardId,
      auth.session.user_id,
      input.maxPrice,
      input.condition,
      input.language,
      input.mode
    )
    .run();

  return json(
    { message: "Desejo salvo" },
    201
  );
}

/*
 * DELETE /api/wants/:id
 */
export async function deleteWant(request, id, env) {
  const auth = await requireSession(
    request,
    env,
    "Faça login para remover desejos"
  );

  if (auth.response) {
    return auth.response;
  }

  const csrfError = csrfErrorResponse(
    request,
    auth.session
  );

  if (csrfError) {
    return csrfError;
  }

  const current = await env.DB.prepare(
    "SELECT id FROM wants " +
    "WHERE id=? AND user_id=?"
  )
    .bind(id, auth.session.user_id)
    .first();

  if (!current) {
    return json(
      { error: "Desejo não encontrado" },
      404
    );
  }

  await env.DB.prepare(
    "DELETE FROM wants " +
    "WHERE id=? AND user_id=?"
  )
    .bind(id, auth.session.user_id)
    .run();

  return json({
    message: "Desejo removido"
  });
}

/*
 * Busca anúncios equivalentes a uma carta específica.
 *
 * oracle_id permite encontrar reimpressões da mesma carta.
 */
async function matchesForCard(cardId, env) {
  const result = await env.DB.prepare(
    "SELECT " +
    "l.id AS listing_id,l.card_id," +
    "c.oracle_id,c.name,c.set_code,c.set_name,c.image_url," +
    "l.title,l.price_cents,l.condition,l.mode,l.contact_url," +
    "u.id AS user_id,u.username,u.display_name,u.city,u.state " +
    "FROM cards target " +
    "JOIN cards c ON " +
    "c.id=target.id OR " +
    "(target.oracle_id IS NOT NULL AND c.oracle_id=target.oracle_id) " +
    "JOIN listings l ON l.card_id=c.id " +
    "JOIN users u ON u.id=l.user_id " +
    "WHERE target.id=? " +
    "ORDER BY u.state,u.city,l.id DESC"
  )
    .bind(cardId)
    .all();

  const matches = result.results || [];

  return json({
    matches,
    total: matches.length,
    basis: "oracle_id"
  });
}

/*
 * Cruza todos os desejos do usuário com anúncios de outras pessoas.
 */
async function matchesForCurrentUser(request, env) {
  const auth = await requireSession(
    request,
    env,
    "Faça login para ver matches dos seus desejos"
  );

  if (auth.response) {
    return auth.response;
  }

  /*
   * Esta é a query mais complexa do projeto.
   *
   * Leia de cima para baixo:
   *   wants   -> o que eu quero;
   *   wanted  -> a carta desejada;
   *   offered -> uma impressão compatível;
   *   listings-> anúncio dessa impressão;
   *   users   -> dono do anúncio.
   *
   * Depois, o WHERE elimina combinações incompatíveis.
   */
  const result = await env.DB.prepare(
    "SELECT " +
    "w.id AS want_id," +
    "w.card_id AS wanted_card_id," +
    "wanted.name AS wanted_name," +
    "w.mode AS want_mode," +
    "w.max_price_cents," +
    "w.desired_condition," +
    "w.desired_language," +
    "l.id AS listing_id," +
    "l.card_id," +
    "offered.name," +
    "offered.set_code," +
    "offered.set_name," +
    "offered.language," +
    "offered.image_url," +
    "l.title," +
    "l.price_cents," +
    "l.condition," +
    "l.mode," +
    "l.contact_url," +
    "u.id AS user_id," +
    "u.username," +
    "u.display_name," +
    "u.city," +
    "u.state " +
    "FROM wants w " +
    "JOIN cards wanted ON wanted.id=w.card_id " +
    "JOIN cards offered ON " +
    "offered.id=wanted.id OR " +
    "(wanted.oracle_id IS NOT NULL AND offered.oracle_id=wanted.oracle_id) " +
    "JOIN listings l ON l.card_id=offered.id " +
    "JOIN users u ON u.id=l.user_id " +
    "WHERE w.user_id=? " +

    // Nunca mostrar o próprio anúncio como match.
    "AND l.user_id<>w.user_id " +

    // Compatibilidade da modalidade.
    "AND (" +
    "w.mode='ambos' " +
    "OR (w.mode='compra' AND l.mode IN ('venda','ambos')) " +
    "OR (w.mode='troca' AND l.mode IN ('troca','ambos'))" +
    ") " +

    // Idioma é opcional no desejo.
    "AND (" +
    "w.desired_language IS NULL " +
    "OR offered.language=w.desired_language COLLATE NOCASE" +
    ") " +

    // Anúncio sem preço continua compatível com uma proposta/troca.
    "AND (" +
    "w.max_price_cents IS NULL " +
    "OR l.price_cents IS NULL " +
    "OR l.price_cents<=w.max_price_cents" +
    ") " +

    // Convertemos as condições em números para poder compará-las.
    "AND (" +
    "w.desired_condition IS NULL OR " +
    "CASE l.condition " +
    "WHEN 'NM' THEN 5 " +
    "WHEN 'SP' THEN 4 " +
    "WHEN 'MP' THEN 3 " +
    "WHEN 'HP' THEN 2 " +
    "ELSE 1 END >= " +
    "CASE w.desired_condition " +
    "WHEN 'NM' THEN 5 " +
    "WHEN 'SP' THEN 4 " +
    "WHEN 'MP' THEN 3 " +
    "WHEN 'HP' THEN 2 " +
    "ELSE 1 END" +
    ") " +

    "ORDER BY w.id DESC,u.state,u.city,l.id DESC"
  )
    .bind(auth.session.user_id)
    .all();

  const matches = result.results || [];

  return json({
    matches,
    total: matches.length,
    basis: "wants"
  });
}

/*
 * GET /api/matches
 *
 * Com card_id -> busca pública para uma carta.
 * Sem card_id -> matches dos desejos do usuário logado.
 */
export async function getMatches(request, url, env) {
  const rawCardId = url.searchParams.get("card_id");

  if (rawCardId) {
    const cardId = Number(rawCardId);

    if (!Number.isInteger(cardId) || cardId <= 0) {
      throw new Error("Carta inválida");
    }

    return matchesForCard(cardId, env);
  }

  return matchesForCurrentUser(request, env);
}

/*
 * GET /api/users/:id
 */
export async function getPublicUser(id, env) {
  const user = await env.DB.prepare(
    "SELECT " +
    "id,username,display_name,phone,city,state,created_at " +
    "FROM users WHERE id=?"
  )
    .bind(id)
    .first();

  if (!user) {
    return json(
      { error: "Usuário não encontrado" },
      404
    );
  }

  /*
   * Estas quatro consultas são independentes.
   * Promise.all permite esperar todas juntas.
   */
  const [
    listingCountRow,
    wantCountRow,
    listingsResult,
    wantsResult
  ] = await Promise.all([
    env.DB.prepare(
      "SELECT COUNT(*) AS count " +
      "FROM listings WHERE user_id=?"
    ).bind(id).first(),

    env.DB.prepare(
      "SELECT COUNT(*) AS count " +
      "FROM wants WHERE user_id=?"
    ).bind(id).first(),

    env.DB.prepare(
      "SELECT " +
      "l.id,l.card_id,l.title,l.description,l.price_cents," +
      "l.condition,l.mode,l.created_at," +
      "c.name,c.printed_name,c.set_code,c.set_name," +
      "c.language,c.image_url " +
      "FROM listings l " +
      "JOIN cards c ON c.id=l.card_id " +
      "WHERE l.user_id=? " +
      "ORDER BY l.id DESC LIMIT 100"
    ).bind(id).all(),

    env.DB.prepare(
      "SELECT " +
      "w.id,w.card_id,w.max_price_cents,w.desired_condition," +
      "w.desired_language,w.mode,w.created_at," +
      "c.name,c.printed_name,c.set_code,c.set_name," +
      "c.language,c.image_url " +
      "FROM wants w " +
      "JOIN cards c ON c.id=w.card_id " +
      "WHERE w.user_id=? " +
      "ORDER BY w.id DESC LIMIT 100"
    ).bind(id).all()
  ]);

  return json({
    user,
    stats: {
      listing_count: Number(
        (listingCountRow && listingCountRow.count) || 0
      ),
      want_count: Number(
        (wantCountRow && wantCountRow.count) || 0
      )
    },
    listings: listingsResult.results || [],
    wants: wantsResult.results || []
  });
}
