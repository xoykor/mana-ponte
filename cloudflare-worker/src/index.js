
import { badRequest, currentSession, authPayload, json } from "./lib.js";
import { getCards, getSets } from "./catalog.js";
import { login, logout, register, updateProfile } from "./auth.js";
import {
  createListing,
  deleteListing,
  getListing,
  getListings,
  updateListing
} from "./listings.js";
import {
  createWant,
  deleteWant,
  getMatches,
  getPublicUser,
  getWants
} from "./wants.js";

function numericTail(path) {
  const value = Number(path.split("/").pop());
  return Number.isInteger(value) && value > 0 ? value : null;
}

async function handleApi(request, env) {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;

  try {
    if (method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-methods": "GET, POST, PATCH, DELETE, OPTIONS",
          "access-control-allow-headers": "Content-Type, X-CSRF-Token",
          "access-control-max-age": "600"
        }
      });
    }

    if (method === "GET" && path === "/api/health") {
      return json({
        status: "ok",
        service: "ManaPonte",
        runtime: "cloudflare-workers-d1",
        image_storage: "none"
      });
    }

    if (method === "GET" && path === "/api/auth/me") {
      const session = await currentSession(request, env);
      return session
        ? json(authPayload(session))
        : json({ error: "Não autenticado" }, 401);
    }

    if (method === "GET" && path === "/api/cards") {
      return await getCards(url, env);
    }

    if (method === "GET" && path === "/api/sets") {
      return await getSets(env);
    }

    if (method === "GET" && path === "/api/listings") {
      return await getListings(request, url, env);
    }

    if (method === "GET" && /^\/api\/listings\/\d+$/.test(path)) {
      return await getListing(numericTail(path), env);
    }

    if (method === "GET" && path === "/api/wants") {
      return await getWants(request, url, env);
    }

    if (method === "GET" && path === "/api/matches") {
      return await getMatches(request, url, env);
    }

    if (method === "GET" && /^\/api\/users\/\d+$/.test(path)) {
      return await getPublicUser(numericTail(path), env);
    }

    if (method === "POST" && path === "/api/auth/register") {
      return await register(request, env);
    }

    if (method === "POST" && path === "/api/auth/login") {
      return await login(request, env);
    }

    if (method === "POST" && path === "/api/auth/logout") {
      return await logout(request, env);
    }

    if (method === "POST" && path === "/api/listings") {
      return await createListing(request, env);
    }

    if (method === "POST" && path === "/api/wants") {
      return await createWant(request, env);
    }

    if (method === "PATCH" && path === "/api/profile") {
      return await updateProfile(request, env);
    }

    if (method === "PATCH" && /^\/api\/listings\/\d+$/.test(path)) {
      return await updateListing(request, numericTail(path), env);
    }

    if (method === "DELETE" && /^\/api\/listings\/\d+$/.test(path)) {
      return await deleteListing(request, numericTail(path), env);
    }

    if (method === "DELETE" && /^\/api\/wants\/\d+$/.test(path)) {
      return await deleteWant(request, numericTail(path), env);
    }

    return json({ error: "Rota não encontrada" }, 404);
  } catch (error) {
    console.error(error);
    const message = error instanceof Error ? error.message : String(error);
    if (/D1|SQL|database|binding/i.test(message)) {
      return json({ error: "Erro interno do banco" }, 500);
    }
    return badRequest(message);
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      return handleApi(request, env);
    }
    return env.ASSETS.fetch(request);
  }
};
