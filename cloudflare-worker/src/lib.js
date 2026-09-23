
export const CONDITIONS = new Set(["NM", "SP", "MP", "HP", "DMG"]);
export const LISTING_MODES = new Set(["venda", "troca", "ambos"]);
export const WANT_MODES = new Set(["compra", "troca", "ambos"]);
export const BRAZIL_STATES = new Set([
  "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA",
  "PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
]);
const SESSION_TTL = 7 * 24 * 60 * 60;
const PASSWORD_ITERATIONS = 120000;

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

export function parseCookies(request) {
  const raw = request.headers.get("cookie") || "";
  const out = {};
  for (const part of raw.split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    const key = part.slice(0, i).trim();
    const value = part.slice(i + 1).trim();
    if (key) out[key] = value;
  }
  return out;
}

function bytesToBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlToBytes(value) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") +
    "=".repeat((4 - value.length % 4) % 4);
  return Uint8Array.from(atob(padded), ch => ch.charCodeAt(0));
}

export function randomToken(size = 32) {
  const bytes = new Uint8Array(size);
  crypto.getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

export async function sha256Hex(value) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(String(value))
  );
  return [...new Uint8Array(digest)]
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");
}

export function safeEqual(left, right) {
  left = String(left || "");
  right = String(right || "");
  if (left.length !== right.length) return false;
  let diff = 0;
  for (let i = 0; i < left.length; i++) {
    diff |= left.charCodeAt(i) ^ right.charCodeAt(i);
  }
  return diff === 0;
}

async function derivePassword(password, salt, iterations) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations },
    key,
    256
  );
  return new Uint8Array(bits);
}

export async function hashPassword(password) {
  const salt = new Uint8Array(16);
  crypto.getRandomValues(salt);
  const derived = await derivePassword(password, salt, PASSWORD_ITERATIONS);
  return [
    "pbkdf2",
    "sha256",
    String(PASSWORD_ITERATIONS),
    bytesToBase64Url(salt),
    bytesToBase64Url(derived)
  ].join("$");
}

export async function verifyPassword(password, encoded) {
  try {
    const parts = String(encoded || "").split("$");
    if (parts.length !== 5 || parts[0] !== "pbkdf2" || parts[1] !== "sha256") {
      return false;
    }
    const iterations = Number(parts[2]);
    if (!Number.isInteger(iterations) || iterations < 100000 || iterations > 1000000) {
      return false;
    }
    const actual = await derivePassword(
      password,
      base64UrlToBytes(parts[3]),
      iterations
    );
    return safeEqual(bytesToBase64Url(actual), parts[4]);
  } catch {
    return false;
  }
}

export function validPassword(password) {
  return typeof password === "string" &&
    password.length >= 12 &&
    password.length <= 128 &&
    /[a-z]/.test(password) &&
    /[A-Z]/.test(password) &&
    /\d/.test(password) &&
    /[^\p{L}\p{N}]/u.test(password);
}

export function normalizePhone(value) {
  if (value == null || String(value).trim() === "") return null;
  const digits = String(value).replace(/\D/g, "");
  if (digits.length < 10 || digits.length > 15) {
    throw new Error("Celular deve ter de 10 a 15 dígitos");
  }
  return digits;
}

export function positiveInt(value, fallback, max) {
  const parsed = Number(value || fallback);
  if (!Number.isInteger(parsed) || parsed <= 0) return fallback;
  return Math.min(parsed, max);
}

export function priceToCents(value) {
  if (value == null || value === "") return null;
  const number = Number(String(value).replace(",", "."));
  if (!Number.isFinite(number) || number < 0) {
    throw new Error("Preço inválido");
  }
  return Math.round(number * 100);
}

export async function readJson(request) {
  const length = Number(request.headers.get("content-length") || "0");
  if (length > 65536) throw new Error("Corpo da requisição é grande demais");
  const text = await request.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("JSON inválido");
  }
}

export async function currentSession(request, env) {
  const token = parseCookies(request).mp_session;
  if (!token) return null;
  const tokenHash = await sha256Hex(token);
  const now = Math.floor(Date.now() / 1000);
  return env.DB.prepare(
    "SELECT s.user_id,s.csrf_token,s.expires_at," +
    "u.username,u.email,u.display_name,u.phone,u.city,u.state,u.email_verified " +
    "FROM sessions s JOIN users u ON u.id=s.user_id " +
    "WHERE s.token_hash=? AND s.expires_at>?"
  ).bind(tokenHash, now).first();
}

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

export async function createSession(userId, env) {
  const token = randomToken(32);
  const csrfToken = randomToken(24);
  const now = Math.floor(Date.now() / 1000);
  const expiresAt = now + SESSION_TTL;
  const tokenHash = await sha256Hex(token);
  await env.DB.batch([
    env.DB.prepare("DELETE FROM sessions WHERE expires_at<=?").bind(now),
    env.DB.prepare(
      "INSERT INTO sessions(token_hash,user_id,csrf_token,created_at,expires_at) " +
      "VALUES(?,?,?,?,?)"
    ).bind(tokenHash, userId, csrfToken, now, expiresAt)
  ]);
  return { token, csrfToken, expiresAt };
}

export function sessionCookie(token, maxAge = SESSION_TTL) {
  return "mp_session=" + token +
    "; Path=/; Max-Age=" + maxAge +
    "; HttpOnly; Secure; SameSite=Lax";
}

export async function requireSession(request, env, message = "Faça login para continuar") {
  const session = await currentSession(request, env);
  if (!session) return { response: json({ error: message }, 401) };
  return { session };
}

export function csrfValid(request, session) {
  return safeEqual(request.headers.get("x-csrf-token"), session && session.csrf_token);
}
