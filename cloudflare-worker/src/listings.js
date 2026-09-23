
import {
  CONDITIONS,
  LISTING_MODES,
  csrfValid,
  json,
  priceToCents,
  readJson,
  requireSession
} from "./lib.js";

export async function getListings(request, url, env) {
  const clauses = [];
  const values = [];

  const exact = [
    ["card_id", "l.card_id=?", Number],
    ["set", "c.set_code=? COLLATE NOCASE", String],
    ["lang", "c.language=? COLLATE NOCASE", String],
    ["city", "u.city=? COLLATE NOCASE", String],
    ["state", "u.state=? COLLATE NOCASE", String],
    ["condition", "l.condition=?", String]
  ];

  for (const item of exact) {
    const raw = url.searchParams.get(item[0]);
    if (!raw) continue;
    const value = item[2](raw);
    if (item[0] === "condition" && !CONDITIONS.has(value)) {
      throw new Error("Condição inválida");
    }
    clauses.push(item[1]);
    values.push(value);
  }

  const mine = (url.searchParams.get("mine") || "").toLowerCase();
  if (["1", "true", "yes"].includes(mine)) {
    const auth = await requireSession(request, env, "Faça login para ver seus anúncios");
    if (auth.response) return auth.response;
    clauses.push("l.user_id=?");
    values.push(auth.session.user_id);
  }

  const mode = (url.searchParams.get("mode") || "").trim();
  if (mode === "venda") {
    clauses.push("l.mode IN ('venda','ambos')");
  } else if (mode === "troca") {
    clauses.push("l.mode IN ('troca','ambos')");
  } else if (mode === "ambos") {
    clauses.push("l.mode='ambos'");
  } else if (mode) {
    throw new Error("Modalidade inválida");
  }

  const minPrice = priceToCents(url.searchParams.get("min_price"));
  const maxPrice = priceToCents(url.searchParams.get("max_price"));
  if (minPrice != null) {
    clauses.push("l.price_cents>=?");
    values.push(minPrice);
  }
  if (maxPrice != null) {
    clauses.push("l.price_cents<=?");
    values.push(maxPrice);
  }
  if (minPrice != null && maxPrice != null && minPrice > maxPrice) {
    throw new Error("Preço mínimo não pode ser maior que o máximo");
  }

  const cardSearch = (url.searchParams.get("card") || "").trim().slice(0, 100);
  if (cardSearch) {
    clauses.push("(c.name LIKE ? COLLATE NOCASE OR c.printed_name LIKE ? COLLATE NOCASE)");
    values.push("%" + cardSearch + "%", "%" + cardSearch + "%");
  }

  const sort = (url.searchParams.get("sort") || "recent").toLowerCase();
  const sorts = {
    recent: "l.created_at DESC,l.id DESC",
    oldest: "l.created_at ASC,l.id ASC",
    price_asc: "(l.price_cents IS NULL),l.price_cents ASC,l.id DESC",
    price_desc: "(l.price_cents IS NULL),l.price_cents DESC,l.id DESC"
  };
  const sortSql = sorts[sort];
  if (!sortSql) throw new Error("Ordenação inválida");

  const pageRaw = Number(url.searchParams.get("page") || "1");
  const limitRaw = Number(url.searchParams.get("limit") || "24");
  const page = Number.isInteger(pageRaw) && pageRaw > 0 ? Math.min(pageRaw, 100000) : 1;
  const limit = Number.isInteger(limitRaw) && limitRaw > 0 ? Math.min(limitRaw, 100) : 24;
  const where = clauses.length ? " WHERE " + clauses.join(" AND ") : "";

  const count = await env.DB.prepare(
    "SELECT COUNT(*) AS total FROM listings l " +
    "JOIN cards c ON c.id=l.card_id " +
    "JOIN users u ON u.id=l.user_id" + where
  ).bind(...values).first();

  const result = await env.DB.prepare(
    "SELECT l.id,l.card_id,l.user_id," +
    "c.name,c.printed_name,c.set_code,c.set_name,c.collector_number," +
    "c.image_url,c.language AS language," +
    "u.username,u.display_name,u.city,u.state," +
    "l.title,l.description,l.price_cents,l.condition,l.mode,l.contact_url,l.created_at " +
    "FROM listings l " +
    "JOIN cards c ON c.id=l.card_id " +
    "JOIN users u ON u.id=l.user_id" + where + " " +
    "ORDER BY " + sortSql + " LIMIT ? OFFSET ?"
  ).bind(...values, limit, (page - 1) * limit).all();

  return json({
    listings: result.results || [],
    total: Number((count && count.total) || 0),
    page,
    limit,
    sort
  });
}

export async function getListing(id, env) {
  const listing = await env.DB.prepare(
    "SELECT l.id,l.card_id,l.user_id,l.title,l.description,l.price_cents," +
    "l.condition,l.mode,l.contact_url,l.created_at," +
    "c.name,c.printed_name,c.set_code,c.set_name,c.collector_number,c.language,c.image_url," +
    "u.username,u.display_name,u.phone,u.city,u.state " +
    "FROM listings l " +
    "JOIN cards c ON c.id=l.card_id " +
    "JOIN users u ON u.id=l.user_id WHERE l.id=?"
  ).bind(id).first();

  if (!listing) {
    return json({ error: "Anúncio não encontrado" }, 404);
  }
  return json({ listing });
}

export async function createListing(request, env) {
  const auth = await requireSession(request, env, "Faça login para anunciar");
  if (auth.response) return auth.response;

  if (!csrfValid(request, auth.session)) {
    return json({ error: "Token CSRF inválido" }, 403);
  }

  const data = await readJson(request);
  const cardId = Number(data.card_id);
  const title = String(data.title || "").trim();
  const description = String(data.description || "").trim();
  const condition = String(data.condition || "");
  const mode = String(data.mode || "");
  const priceCents = data.price_cents == null || data.price_cents === ""
    ? null
    : Number(data.price_cents);

  if (!Number.isInteger(cardId) || cardId <= 0) {
    throw new Error("Carta inválida");
  }
  if (title.length < 3 || title.length > 120 || description.length > 1000) {
    throw new Error("Título deve ter 3–120 caracteres e descrição no máximo 1000");
  }
  if (!CONDITIONS.has(condition) || !LISTING_MODES.has(mode)) {
    throw new Error("Condição ou modalidade inválida");
  }
  if (priceCents != null && (!Number.isInteger(priceCents) || priceCents < 0)) {
    throw new Error("Preço inválido");
  }

  const card = await env.DB.prepare(
    "SELECT language FROM cards WHERE id=?"
  ).bind(cardId).first();
  if (!card) throw new Error("Carta não encontrada");

  const result = await env.DB.prepare(
    "INSERT INTO listings(" +
    "card_id,user_id,title,description,price_cents,condition,language,mode" +
    ") VALUES(?,?,?,?,?,?,?,?)"
  ).bind(
    cardId,
    auth.session.user_id,
    title,
    description,
    priceCents,
    condition,
    card.language || "en",
    mode
  ).run();

  return json({
    id: Number(result.meta && result.meta.last_row_id),
    message: "Oferta publicada"
  }, 201);
}

export async function updateListing(request, id, env) {
  const auth = await requireSession(request, env, "Faça login para editar anúncios");
  if (auth.response) return auth.response;

  if (!csrfValid(request, auth.session)) {
    return json({ error: "Token CSRF inválido" }, 403);
  }

  const current = await env.DB.prepare(
    "SELECT * FROM listings WHERE id=? AND user_id=?"
  ).bind(id, auth.session.user_id).first();

  if (!current) {
    return json({ error: "Anúncio não encontrado" }, 404);
  }

  const data = await readJson(request);
  const cardId = Number(data.card_id == null ? current.card_id : data.card_id);
  const title = String(data.title == null ? current.title : data.title).trim();
  const description = String(
    data.description == null ? current.description : data.description
  ).trim();
  const condition = String(
    data.condition == null ? current.condition : data.condition
  );
  const mode = String(data.mode == null ? current.mode : data.mode);
  const rawPrice = data.price_cents == null ? current.price_cents : data.price_cents;
  const priceCents = rawPrice == null || rawPrice === "" ? null : Number(rawPrice);

  if (title.length < 3 || title.length > 120 || description.length > 1000) {
    throw new Error("Título deve ter 3–120 caracteres e descrição no máximo 1000");
  }
  if (!CONDITIONS.has(condition) || !LISTING_MODES.has(mode)) {
    throw new Error("Condição ou modalidade inválida");
  }
  if (priceCents != null && (!Number.isInteger(priceCents) || priceCents < 0)) {
    throw new Error("Preço inválido");
  }

  const card = await env.DB.prepare(
    "SELECT language FROM cards WHERE id=?"
  ).bind(cardId).first();
  if (!card) throw new Error("Carta não encontrada");

  await env.DB.prepare(
    "UPDATE listings SET " +
    "card_id=?,title=?,description=?,price_cents=?,condition=?,language=?,mode=? " +
    "WHERE id=? AND user_id=?"
  ).bind(
    cardId,
    title,
    description,
    priceCents,
    condition,
    card.language || "en",
    mode,
    id,
    auth.session.user_id
  ).run();

  return json({ id, message: "Anúncio atualizado" });
}

export async function deleteListing(request, id, env) {
  const auth = await requireSession(request, env, "Faça login para remover anúncios");
  if (auth.response) return auth.response;

  if (!csrfValid(request, auth.session)) {
    return json({ error: "Token CSRF inválido" }, 403);
  }

  const current = await env.DB.prepare(
    "SELECT id FROM listings WHERE id=? AND user_id=?"
  ).bind(id, auth.session.user_id).first();

  if (!current) {
    return json({ error: "Anúncio não encontrado" }, 404);
  }

  await env.DB.prepare(
    "DELETE FROM listings WHERE id=? AND user_id=?"
  ).bind(id, auth.session.user_id).run();

  return json({ message: "Anúncio removido" });
}
