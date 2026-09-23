/*
 * FUNÇÕES COMPARTILHADAS DO WORKER
 * =================================
 *
 * Este arquivo reúne pequenas ferramentas usadas por vários módulos.
 *
 * Uma boa regra para iniciantes:
 *   se a mesma lógica aparece em vários arquivos, vale perguntar se ela deveria
 *   virar uma função compartilhada aqui.
 */

// Valores permitidos pela regra de negócio.
export const CONDITIONS = new Set(["NM", "SP", "MP", "HP", "DMG"]);
export const LISTING_MODES = new Set(["venda", "troca", "ambos"]);
export const WANT_MODES = new Set(["compra", "troca", "ambos"]);

export const BRAZIL_STATES = new Set([
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
  "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
  "SP", "SE", "TO"
]);

// Uma sessão dura 7 dias. O valor abaixo está em segundos.
const SESSION_TTL_SECONDS = 7 * 24 * 60 * 60;

// Novas senhas usam PBKDF2-SHA256 com 100 mil iterações.
const PASSWORD_ITERATIONS = 100000;

/*
 * Cria uma resposta JSON padronizada.
 *
 * data         -> objeto que será transformado em texto JSON;
 * status       -> código HTTP, por exemplo 200, 400 ou 404;
 * extraHeaders -> cabeçalhos adicionais, como Set-Cookie.
 */
export function json(data, status = 200, extraHeaders = {}) {
  const headers = new Headers(extraHeaders);

  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", "no-store");
  headers.set("x-content-type-options", "nosniff");

  return new Response(JSON.stringify(data), { status, headers });
}

export function badRequest(message) {
  return json({ error: message }, 400);
}

/*
 * Transforma o cabeçalho Cookie em um objeto JavaScript.
 *
 * Exemplo:
 *   "a=1; b=2"
 *
 * vira:
 *   { a: "1", b: "2" }
 */
export function parseCookies(request) {
  const cookieHeader = request.headers.get("cookie") || "";
  const cookies = {};

  for (const piece of cookieHeader.split(";")) {
    const equalsIndex = piece.indexOf("=");

    if (equalsIndex < 0) {
      continue;
    }

    const name = piece.slice(0, equalsIndex).trim();
    const value = piece.slice(equalsIndex + 1).trim();

    if (name) {
      cookies[name] = value;
    }
  }

  return cookies;
}

/*
 * Os tokens são bytes aleatórios. Para caberem com segurança em URLs/cookies,
 * convertemos esses bytes para Base64 URL-safe.
 */
function bytesToBase64Url(bytes) {
  let binary = "";

  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function base64UrlToBytes(value) {
  const regularBase64 = value
    .replace(/-/g, "+")
    .replace(/_/g, "/");

  const paddingSize = (4 - regularBase64.length % 4) % 4;
  const padded = regularBase64 + "=".repeat(paddingSize);

  return Uint8Array.from(
    atob(padded),
    character => character.charCodeAt(0)
  );
}

/*
 * Gera um token criptograficamente aleatório.
 *
 * Não usamos Math.random() para sessão porque ele não foi feito para segurança.
 */
export function randomToken(size = 32) {
  const bytes = new Uint8Array(size);
  crypto.getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

/*
 * Calcula SHA-256 e devolve o resultado como texto hexadecimal.
 */
export async function sha256Hex(value) {
  const bytes = new TextEncoder().encode(String(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);

  return [...new Uint8Array(digest)]
    .map(byte => byte.toString(16).padStart(2, "0"))
    .join("");
}

/*
 * Compara duas strings sem sair do laço assim que encontra uma diferença.
 *
 * Isso é usado em valores de segurança, como CSRF e hashes.
 */
export function safeEqual(left, right) {
  const leftText = String(left || "");
  const rightText = String(right || "");

  if (leftText.length !== rightText.length) {
    return false;
  }

  let difference = 0;

  for (let index = 0; index < leftText.length; index += 1) {
    difference |= leftText.charCodeAt(index) ^ rightText.charCodeAt(index);
  }

  return difference === 0;
}

/*
 * PBKDF2 transforma a senha em uma chave derivada.
 *
 * O salt impede que duas pessoas com a mesma senha tenham o mesmo hash.
 * As iterações tornam cada tentativa mais custosa.
 */
async function derivePassword(password, salt, iterations) {
  const passwordBytes = new TextEncoder().encode(password);

  const importedKey = await crypto.subtle.importKey(
    "raw",
    passwordBytes,
    "PBKDF2",
    false,
    ["deriveBits"]
  );

  const derivedBits = await crypto.subtle.deriveBits(
    {
      name: "PBKDF2",
      hash: "SHA-256",
      salt,
      iterations
    },
    importedKey,
    256
  );

  return new Uint8Array(derivedBits);
}

/*
 * Cria o texto que vai para users.password_hash.
 *
 * Guardamos também o algoritmo, quantidade de iterações e salt. Assim o
 * verificador sabe exatamente como reproduzir o cálculo no login.
 */
export async function hashPassword(password) {
  const salt = new Uint8Array(16);
  crypto.getRandomValues(salt);

  const derived = await derivePassword(
    password,
    salt,
    PASSWORD_ITERATIONS
  );

  return [
    "pbkdf2",
    "sha256",
    String(PASSWORD_ITERATIONS),
    bytesToBase64Url(salt),
    bytesToBase64Url(derived)
  ].join("$");
}

/*
 * Verifica uma senha sem nunca precisar guardar a senha original.
 */
export async function verifyPassword(password, encodedHash) {
  try {
    const parts = String(encodedHash || "").split("$");

    if (
      parts.length !== 5 ||
      parts[0] !== "pbkdf2" ||
      parts[1] !== "sha256"
    ) {
      return false;
    }

    const iterations = Number(parts[2]);

    // Aceitamos hashes antigos com mais iterações, até este teto de segurança.
    if (
      !Number.isInteger(iterations) ||
      iterations < 100000 ||
      iterations > 1000000
    ) {
      return false;
    }

    const salt = base64UrlToBytes(parts[3]);
    const expectedHash = parts[4];

    const derived = await derivePassword(password, salt, iterations);
    const actualHash = bytesToBase64Url(derived);

    return safeEqual(actualHash, expectedHash);
  } catch {
    // Hash quebrado ou em formato inesperado é simplesmente inválido.
    return false;
  }
}

/*
 * Regra mínima para uma senha de cadastro.
 */
export function validPassword(password) {
  if (typeof password !== "string") {
    return false;
  }

  const hasValidLength = password.length >= 12 && password.length <= 128;
  const hasLowercase = /[a-z]/.test(password);
  const hasUppercase = /[A-Z]/.test(password);
  const hasNumber = /\d/.test(password);
  const hasSymbol = /[^\p{L}\p{N}]/u.test(password);

  return (
    hasValidLength &&
    hasLowercase &&
    hasUppercase &&
    hasNumber &&
    hasSymbol
  );
}

/*
 * Guarda telefone somente como dígitos.
 *
 * null significa que o usuário escolheu não informar telefone.
 */
export function normalizePhone(value) {
  if (value == null || String(value).trim() === "") {
    return null;
  }

  const digits = String(value).replace(/\D/g, "");

  if (digits.length < 10 || digits.length > 15) {
    throw new Error("Celular deve ter de 10 a 15 dígitos");
  }

  return digits;
}

/*
 * Lê um inteiro positivo com valor padrão e teto.
 *
 * É útil para paginação:
 *   page  -> página atual;
 *   limit -> quantidade de itens por página.
 */
export function positiveInt(value, fallback, maximum) {
  const parsed = Number(value || fallback);

  if (!Number.isInteger(parsed) || parsed <= 0) {
    return fallback;
  }

  return Math.min(parsed, maximum);
}

/*
 * A interface aceita preços em reais, mas o banco trabalha com centavos.
 *
 * Exemplo:
 *   "12,50" -> 1250
 */
export function priceToCents(value) {
  if (value == null || value === "") {
    return null;
  }

  const number = Number(String(value).replace(",", "."));

  if (!Number.isFinite(number) || number < 0) {
    throw new Error("Preço inválido");
  }

  return Math.round(number * 100);
}

/*
 * Lê o corpo JSON de uma requisição.
 *
 * Há um limite simples para evitar corpos exageradamente grandes.
 */
export async function readJson(request) {
  const contentLength = Number(
    request.headers.get("content-length") || "0"
  );

  if (contentLength > 65536) {
    throw new Error("Corpo da requisição é grande demais");
  }

  const text = await request.text();

  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    throw new Error("JSON inválido");
  }
}

/*
 * Procura a sessão representada pelo cookie mp_session.
 *
 * O navegador possui o token bruto.
 * O banco possui apenas SHA-256(token).
 */
export async function currentSession(request, env) {
  const token = parseCookies(request).mp_session;

  if (!token) {
    return null;
  }

  const tokenHash = await sha256Hex(token);
  const now = Math.floor(Date.now() / 1000);

  return env.DB.prepare(
    "SELECT s.user_id,s.csrf_token,s.expires_at," +
    "u.username,u.email,u.display_name,u.phone,u.city,u.state,u.email_verified " +
    "FROM sessions s " +
    "JOIN users u ON u.id=s.user_id " +
    "WHERE s.token_hash=? AND s.expires_at>?"
  )
    .bind(tokenHash, now)
    .first();
}

/*
 * Converte uma linha de sessão no formato devolvido ao frontend.
 */
export function authPayload(session) {
  return {
    user: {
      id: session.user_id,
      username: session.username,
      email: session.email,
      display_name: session.display_name,
      phone: session.phone,
      city: session.city,
      state: session.state,
      email_verified: Boolean(session.email_verified)
    },
    csrf_token: session.csrf_token
  };
}

/*
 * Cria uma nova sessão.
 */
export async function createSession(userId, env) {
  const rawToken = randomToken(32);
  const csrfToken = randomToken(24);

  const now = Math.floor(Date.now() / 1000);
  const expiresAt = now + SESSION_TTL_SECONDS;
  const tokenHash = await sha256Hex(rawToken);

  // D1.batch envia as duas operações juntas para reduzir idas ao banco.
  await env.DB.batch([
    // Limpeza oportunista de sessões vencidas.
    env.DB.prepare(
      "DELETE FROM sessions WHERE expires_at<=?"
    ).bind(now),

    env.DB.prepare(
      "INSERT INTO sessions(" +
      "token_hash,user_id,csrf_token,created_at,expires_at" +
      ") VALUES(?,?,?,?,?)"
    ).bind(tokenHash, userId, csrfToken, now, expiresAt)
  ]);

  return {
    token: rawToken,
    csrfToken,
    expiresAt
  };
}

/*
 * Monta o valor do cabeçalho Set-Cookie.
 */
export function sessionCookie(token, maxAge = SESSION_TTL_SECONDS) {
  return (
    "mp_session=" + token +
    "; Path=/" +
    "; Max-Age=" + maxAge +
    "; HttpOnly" +
    "; Secure" +
    "; SameSite=Lax"
  );
}

/*
 * Atalho para rotas que só funcionam com usuário logado.
 *
 * Em vez de lançar exceção, devolve response quando a sessão não existe.
 */
export async function requireSession(
  request,
  env,
  message = "Faça login para continuar"
) {
  const session = await currentSession(request, env);

  if (!session) {
    return {
      response: json({ error: message }, 401)
    };
  }

  return { session };
}

/*
 * Confere o token CSRF enviado no cabeçalho.
 */
export function csrfValid(request, session) {
  const sentToken = request.headers.get("x-csrf-token");
  const expectedToken = session && session.csrf_token;

  return safeEqual(sentToken, expectedToken);
}
