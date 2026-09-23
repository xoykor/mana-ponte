
import {
  BRAZIL_STATES,
  authPayload,
  createSession,
  csrfValid,
  currentSession,
  hashPassword,
  json,
  normalizePhone,
  parseCookies,
  readJson,
  requireSession,
  sessionCookie,
  sha256Hex,
  validPassword,
  verifyPassword
} from "./lib.js";

export async function register(request, env) {
  const data = await readJson(request);
  const username = String(data.username || "").trim().toLowerCase();
  const email = String(data.email || "").trim().toLowerCase();
  const password = data.password;
  const displayName = String(data.display_name || "").trim();
  const phone = normalizePhone(data.phone);
  const city = String(data.city || "").trim();
  const state = String(data.state || "").trim().toUpperCase();

  if (!/^[a-z0-9_.-]{3,30}$/.test(username)) {
    throw new Error("Usuário deve ter 3–30 caracteres: letras, números, _, . ou -");
  }
  if (!/^[^\s@]{1,64}@[a-z0-9.-]{1,190}\.[a-z]{2,63}$/i.test(email) || email.length > 254) {
    throw new Error("E-mail inválido");
  }
  if (!validPassword(password)) {
    throw new Error("Senha deve ter 12–128 caracteres, maiúscula, minúscula, número e símbolo");
  }
  if (
    displayName.length < 2 ||
    displayName.length > 80 ||
    city.length < 2 ||
    city.length > 80 ||
    !BRAZIL_STATES.has(state)
  ) {
    throw new Error("Nome, cidade ou UF inválidos");
  }

  const passwordHash = await hashPassword(password);
  let result;

  try {
    result = await env.DB.prepare(
      "INSERT INTO users(" +
      "username,email,display_name,phone,city,state,password_hash,email_verified,updated_at" +
      ") VALUES(?,?,?,?,?,?,?,0,CURRENT_TIMESTAMP)"
    ).bind(
      username,
      email,
      displayName,
      phone,
      city,
      state,
      passwordHash
    ).run();
  } catch (error) {
    const message = String(error && error.message ? error.message : error);
    if (/UNIQUE|constraint/i.test(message)) {
      return json({ error: "Já existe uma conta com esses dados" }, 409);
    }
    throw error;
  }

  const userId = Number(result.meta && result.meta.last_row_id);
  const sessionData = await createSession(userId, env);
  const sessionRequest = new Request(request.url, {
    headers: { cookie: "mp_session=" + sessionData.token }
  });
  const session = await currentSession(sessionRequest, env);

  return json(
    authPayload(session),
    201,
    { "set-cookie": sessionCookie(sessionData.token) }
  );
}

async function loginRateInfo(request, identifier, env) {
  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  const key = await sha256Hex(ip + ":" + identifier);
  const now = Math.floor(Date.now() / 1000);
  const row = await env.DB.prepare(
    "SELECT failures,window_started,blocked_until FROM login_attempts WHERE key=?"
  ).bind(key).first();

  return {
    key,
    now,
    row,
    blocked: Number((row && row.blocked_until) || 0) > now
  };
}

async function recordFailure(info, env) {
  const currentStart = Number((info.row && info.row.window_started) || 0);
  const reset = !currentStart || info.now - currentStart >= 900;
  const failures = reset
    ? 1
    : Number((info.row && info.row.failures) || 0) + 1;
  const blockedUntil = failures >= 5 ? info.now + 900 : 0;
  const windowStarted = reset ? info.now : currentStart;

  await env.DB.prepare(
    "INSERT INTO login_attempts(key,failures,window_started,blocked_until) " +
    "VALUES(?,?,?,?) " +
    "ON CONFLICT(key) DO UPDATE SET " +
    "failures=excluded.failures," +
    "window_started=excluded.window_started," +
    "blocked_until=excluded.blocked_until"
  ).bind(
    info.key,
    failures,
    windowStarted,
    blockedUntil
  ).run();

  return failures;
}

export async function login(request, env) {
  const data = await readJson(request);
  const identifier = String(data.identifier || "").trim().toLowerCase().slice(0, 254);
  const password = String(data.password || "");
  const rate = await loginRateInfo(request, identifier, env);

  if (rate.blocked) {
    return json({ error: "Muitas tentativas. Aguarde 15 minutos." }, 429);
  }

  const user = await env.DB.prepare(
    "SELECT id,password_hash FROM users " +
    "WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE"
  ).bind(identifier, identifier).first();

  const valid = user
    ? await verifyPassword(password, user.password_hash)
    : false;

  if (!user || !valid) {
    const failures = await recordFailure(rate, env);
    if (failures >= 5) {
      return json({ error: "Muitas tentativas. Aguarde 15 minutos." }, 429);
    }
    return json({ error: "Credenciais inválidas" }, 401);
  }

  await env.DB.prepare(
    "DELETE FROM login_attempts WHERE key=?"
  ).bind(rate.key).run();

  const sessionData = await createSession(user.id, env);
  const sessionRequest = new Request(request.url, {
    headers: { cookie: "mp_session=" + sessionData.token }
  });
  const session = await currentSession(sessionRequest, env);

  return json(
    authPayload(session),
    200,
    { "set-cookie": sessionCookie(sessionData.token) }
  );
}

export async function logout(request, env) {
  const auth = await requireSession(request, env, "Não autenticado");
  if (auth.response) return auth.response;

  if (!csrfValid(request, auth.session)) {
    return json({ error: "Token CSRF inválido" }, 403);
  }

  const token = parseCookies(request).mp_session;
  if (token) {
    await env.DB.prepare(
      "DELETE FROM sessions WHERE token_hash=?"
    ).bind(await sha256Hex(token)).run();
  }

  return json(
    { message: "Sessão encerrada" },
    200,
    { "set-cookie": sessionCookie("", 0) }
  );
}

export async function updateProfile(request, env) {
  const auth = await requireSession(request, env, "Não autenticado");
  if (auth.response) return auth.response;

  if (!csrfValid(request, auth.session)) {
    return json({ error: "Token CSRF inválido" }, 403);
  }

  const data = await readJson(request);
  const displayName = String(
    data.display_name == null ? auth.session.display_name : data.display_name
  ).trim();
  const phone = normalizePhone(
    data.phone == null ? auth.session.phone : data.phone
  );
  const city = String(
    data.city == null ? auth.session.city : data.city
  ).trim();
  const state = String(
    data.state == null ? auth.session.state : data.state
  ).trim().toUpperCase();

  if (
    displayName.length < 2 ||
    displayName.length > 80 ||
    city.length < 2 ||
    city.length > 80 ||
    !BRAZIL_STATES.has(state)
  ) {
    throw new Error("Nome, cidade ou UF inválidos");
  }

  await env.DB.prepare(
    "UPDATE users SET display_name=?,phone=?,city=?,state=?,updated_at=CURRENT_TIMESTAMP " +
    "WHERE id=?"
  ).bind(
    displayName,
    phone,
    city,
    state,
    auth.session.user_id
  ).run();

  const session = await currentSession(request, env);
  return json(authPayload(session));
}
