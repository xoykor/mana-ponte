/*
 * AUTENTICAÇÃO E PERFIL
 * =====================
 *
 * Fluxos deste arquivo:
 *   - criar conta;
 *   - entrar;
 *   - sair;
 *   - alterar perfil.
 *
 * A regra geral é:
 *   entrada -> normalização -> validação -> banco -> resposta.
 */

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

const LOGIN_WINDOW_SECONDS = 15 * 60;
const LOGIN_BLOCK_SECONDS = 15 * 60;
const MAX_LOGIN_FAILURES = 5;

/*
 * Valida os campos de perfil usados tanto no cadastro quanto na edição.
 */
function validateProfile(displayName, city, state) {
  const validDisplayName =
    displayName.length >= 2 &&
    displayName.length <= 80;

  const validCity =
    city.length >= 2 &&
    city.length <= 80;

  const validState = BRAZIL_STATES.has(state);

  if (!validDisplayName || !validCity || !validState) {
    throw new Error("Nome, cidade ou UF inválidos");
  }
}

/*
 * Cria um Request artificial que carrega o token recém-criado.
 *
 * Isso nos permite reutilizar currentSession() e devolver exatamente o mesmo
 * formato de sessão usado nas outras rotas.
 */
function requestWithSessionCookie(originalRequest, token) {
  return new Request(originalRequest.url, {
    headers: {
      cookie: "mp_session=" + token
    }
  });
}

/*
 * Cria sessão e monta a resposta de autenticação.
 *
 * Cadastro e login faziam quase o mesmo bloco de código. Colocá-lo numa
 * função evita duplicação e reduz chance de um fluxo ficar diferente do outro.
 */
async function authenticatedResponse(request, userId, env, status) {
  const sessionData = await createSession(userId, env);

  const sessionRequest = requestWithSessionCookie(
    request,
    sessionData.token
  );

  const session = await currentSession(sessionRequest, env);

  return json(
    authPayload(session),
    status,
    {
      "set-cookie": sessionCookie(sessionData.token)
    }
  );
}

/*
 * POST /api/auth/register
 */
export async function register(request, env) {
  const data = await readJson(request);

  // Normalizar significa colocar entradas equivalentes no mesmo formato.
  const username = String(data.username || "")
    .trim()
    .toLowerCase();

  const email = String(data.email || "")
    .trim()
    .toLowerCase();

  const password = data.password;

  const displayName = String(data.display_name || "")
    .trim();

  const phone = normalizePhone(data.phone);

  const city = String(data.city || "")
    .trim();

  const state = String(data.state || "")
    .trim()
    .toUpperCase();

  if (!/^[a-z0-9_.-]{3,30}$/.test(username)) {
    throw new Error(
      "Usuário deve ter 3–30 caracteres: letras, números, _, . ou -"
    );
  }

  const emailLooksValid =
    /^[^\s@]{1,64}@[a-z0-9.-]{1,190}\.[a-z]{2,63}$/i.test(email);

  if (!emailLooksValid || email.length > 254) {
    throw new Error("E-mail inválido");
  }

  if (!validPassword(password)) {
    throw new Error(
      "Senha deve ter 12–128 caracteres, maiúscula, minúscula, número e símbolo"
    );
  }

  validateProfile(displayName, city, state);

  // Nunca gravamos a senha original.
  const passwordHash = await hashPassword(password);

  let insertResult;

  try {
    insertResult = await env.DB.prepare(
      "INSERT INTO users(" +
      "username,email,display_name,phone,city,state," +
      "password_hash,email_verified,updated_at" +
      ") VALUES(?,?,?,?,?,?,?,0,CURRENT_TIMESTAMP)"
    )
      .bind(
        username,
        email,
        displayName,
        phone,
        city,
        state,
        passwordHash
      )
      .run();
  } catch (error) {
    const message = String(
      error && error.message ? error.message : error
    );

    // Username e e-mail são UNIQUE no D1.
    if (/UNIQUE|constraint/i.test(message)) {
      return json(
        { error: "Já existe uma conta com esses dados" },
        409
      );
    }

    throw error;
  }

  const userId = Number(
    insertResult.meta && insertResult.meta.last_row_id
  );

  return authenticatedResponse(
    request,
    userId,
    env,
    201
  );
}

/*
 * Lê o estado atual do limitador de tentativas de login.
 */
async function loginRateInfo(request, identifier, env) {
  const ip = request.headers.get("cf-connecting-ip") || "unknown";

  // Não precisamos guardar IP + e-mail em texto no banco.
  const key = await sha256Hex(ip + ":" + identifier);
  const now = Math.floor(Date.now() / 1000);

  const row = await env.DB.prepare(
    "SELECT failures,window_started,blocked_until " +
    "FROM login_attempts WHERE key=?"
  )
    .bind(key)
    .first();

  const blockedUntil = Number(
    (row && row.blocked_until) || 0
  );

  return {
    key,
    now,
    row,
    blocked: blockedUntil > now
  };
}

/*
 * Registra uma tentativa de login que falhou.
 */
async function recordLoginFailure(info, env) {
  const previousWindowStart = Number(
    (info.row && info.row.window_started) || 0
  );

  const windowExpired =
    !previousWindowStart ||
    info.now - previousWindowStart >= LOGIN_WINDOW_SECONDS;

  const previousFailures = Number(
    (info.row && info.row.failures) || 0
  );

  const failures = windowExpired
    ? 1
    : previousFailures + 1;

  const windowStarted = windowExpired
    ? info.now
    : previousWindowStart;

  const blockedUntil = failures >= MAX_LOGIN_FAILURES
    ? info.now + LOGIN_BLOCK_SECONDS
    : 0;

  await env.DB.prepare(
    "INSERT INTO login_attempts(" +
    "key,failures,window_started,blocked_until" +
    ") VALUES(?,?,?,?) " +
    "ON CONFLICT(key) DO UPDATE SET " +
    "failures=excluded.failures," +
    "window_started=excluded.window_started," +
    "blocked_until=excluded.blocked_until"
  )
    .bind(
      info.key,
      failures,
      windowStarted,
      blockedUntil
    )
    .run();

  return failures;
}

/*
 * POST /api/auth/login
 */
export async function login(request, env) {
  const data = await readJson(request);

  const identifier = String(data.identifier || "")
    .trim()
    .toLowerCase()
    .slice(0, 254);

  const password = String(data.password || "");

  const rate = await loginRateInfo(
    request,
    identifier,
    env
  );

  if (rate.blocked) {
    return json(
      { error: "Muitas tentativas. Aguarde 15 minutos." },
      429
    );
  }

  const user = await env.DB.prepare(
    "SELECT id,password_hash FROM users " +
    "WHERE username=? COLLATE NOCASE " +
    "OR email=? COLLATE NOCASE"
  )
    .bind(identifier, identifier)
    .first();

  const passwordIsValid = user
    ? await verifyPassword(password, user.password_hash)
    : false;

  if (!user || !passwordIsValid) {
    const failures = await recordLoginFailure(rate, env);

    if (failures >= MAX_LOGIN_FAILURES) {
      return json(
        { error: "Muitas tentativas. Aguarde 15 minutos." },
        429
      );
    }

    return json({ error: "Credenciais inválidas" }, 401);
  }

  // Login correto: a contagem de falhas daquela chave deixa de ser útil.
  await env.DB.prepare(
    "DELETE FROM login_attempts WHERE key=?"
  )
    .bind(rate.key)
    .run();

  return authenticatedResponse(
    request,
    user.id,
    env,
    200
  );
}

/*
 * POST /api/auth/logout
 */
export async function logout(request, env) {
  const auth = await requireSession(
    request,
    env,
    "Não autenticado"
  );

  if (auth.response) {
    return auth.response;
  }

  if (!csrfValid(request, auth.session)) {
    return json({ error: "Token CSRF inválido" }, 403);
  }

  const rawToken = parseCookies(request).mp_session;

  if (rawToken) {
    const tokenHash = await sha256Hex(rawToken);

    await env.DB.prepare(
      "DELETE FROM sessions WHERE token_hash=?"
    )
      .bind(tokenHash)
      .run();
  }

  // Max-Age=0 manda o navegador remover o cookie.
  return json(
    { message: "Sessão encerrada" },
    200,
    {
      "set-cookie": sessionCookie("", 0)
    }
  );
}

/*
 * PATCH /api/profile
 */
export async function updateProfile(request, env) {
  const auth = await requireSession(
    request,
    env,
    "Não autenticado"
  );

  if (auth.response) {
    return auth.response;
  }

  if (!csrfValid(request, auth.session)) {
    return json({ error: "Token CSRF inválido" }, 403);
  }

  const data = await readJson(request);

  /*
   * Em PATCH, campo ausente significa "mantenha o valor atual".
   */
  const displayName = String(
    data.display_name == null
      ? auth.session.display_name
      : data.display_name
  ).trim();

  const phone = normalizePhone(
    data.phone == null
      ? auth.session.phone
      : data.phone
  );

  const city = String(
    data.city == null
      ? auth.session.city
      : data.city
  ).trim();

  const state = String(
    data.state == null
      ? auth.session.state
      : data.state
  )
    .trim()
    .toUpperCase();

  validateProfile(displayName, city, state);

  await env.DB.prepare(
    "UPDATE users SET " +
    "display_name=?,phone=?,city=?,state=?,updated_at=CURRENT_TIMESTAMP " +
    "WHERE id=?"
  )
    .bind(
      displayName,
      phone,
      city,
      state,
      auth.session.user_id
    )
    .run();

  // Relê a sessão para devolver o perfil já atualizado.
  const updatedSession = await currentSession(request, env);

  return json(authPayload(updatedSession));
}
