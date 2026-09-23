/*
 * PONTO DE ENTRADA DO BACKEND DE PRODUÇÃO
 * =======================================
 *
 * Pense neste arquivo como a "recepção" do ManaPonte.
 *
 * Toda requisição HTTP chega aqui primeiro. O trabalho deste arquivo é:
 *   1. descobrir qual rota foi pedida;
 *   2. chamar a função responsável por essa rota;
 *   3. transformar erros inesperados em uma resposta JSON compreensível.
 *
 * Regras de negócio ficam em outros arquivos:
 *   - auth.js      -> contas e login;
 *   - catalog.js   -> cartas;
 *   - listings.js  -> anúncios;
 *   - wants.js     -> desejos e matches.
 *
 * Isso deixa cada arquivo com uma responsabilidade mais fácil de entender.
 */

import { authPayload, badRequest, currentSession, json } from "./lib.js";
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

/*
 * Algumas rotas terminam em um número, por exemplo:
 *
 *   /api/listings/42
 *
 * Esta função pega somente o último pedaço da URL e tenta transformá-lo
 * em um inteiro positivo.
 */
function readPositiveIdFromPath(path) {
  const lastPart = path.split("/").pop();
  const id = Number(lastPart);

  if (!Number.isInteger(id) || id <= 0) {
    return null;
  }

  return id;
}

/*
 * Responde ao preflight OPTIONS.
 *
 * Navegadores podem enviar OPTIONS antes de certas requisições para perguntar
 * quais métodos e cabeçalhos a API aceita.
 */
function optionsResponse() {
  return new Response(null, {
    status: 204,
    headers: {
      "access-control-allow-methods": "GET, POST, PATCH, DELETE, OPTIONS",
      "access-control-allow-headers": "Content-Type, X-CSRF-Token",
      "access-control-max-age": "600"
    }
  });
}

/*
 * Centraliza a tradução de exceções para respostas HTTP.
 *
 * Erros de banco não devem entregar detalhes internos ao visitante.
 * Outros erros, em geral, são erros de entrada e retornam HTTP 400.
 */
function errorResponse(error) {
  console.error(error);

  const message = error instanceof Error
    ? error.message
    : String(error);

  if (/D1|SQL|database|binding/i.test(message)) {
    return json({ error: "Erro interno do banco" }, 500);
  }

  return badRequest(message);
}

/*
 * Roteador da API.
 *
 * Cada bloco abaixo pode ser lido como:
 *
 *   "SE o método for X E o caminho for Y,
 *    ENTÃO chame a função Z".
 *
 * Usamos await de propósito. Sem ele, uma exceção assíncrona pode escapar do
 * try/catch e a Cloudflare devolver um erro genérico em vez de JSON.
 */
async function handleApi(request, env) {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;

  try {
    if (method === "OPTIONS") {
      return optionsResponse();
    }

    // ---------- Rotas GET ----------

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

      if (!session) {
        return json({ error: "Não autenticado" }, 401);
      }

      return json(authPayload(session));
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
      const listingId = readPositiveIdFromPath(path);
      return await getListing(listingId, env);
    }

    if (method === "GET" && path === "/api/wants") {
      return await getWants(request, url, env);
    }

    if (method === "GET" && path === "/api/matches") {
      return await getMatches(request, url, env);
    }

    if (method === "GET" && /^\/api\/users\/\d+$/.test(path)) {
      const userId = readPositiveIdFromPath(path);
      return await getPublicUser(userId, env);
    }

    // ---------- Rotas POST ----------

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

    // ---------- Rotas PATCH ----------

    if (method === "PATCH" && path === "/api/profile") {
      return await updateProfile(request, env);
    }

    if (method === "PATCH" && /^\/api\/listings\/\d+$/.test(path)) {
      const listingId = readPositiveIdFromPath(path);
      return await updateListing(request, listingId, env);
    }

    // ---------- Rotas DELETE ----------

    if (method === "DELETE" && /^\/api\/listings\/\d+$/.test(path)) {
      const listingId = readPositiveIdFromPath(path);
      return await deleteListing(request, listingId, env);
    }

    if (method === "DELETE" && /^\/api\/wants\/\d+$/.test(path)) {
      const wantId = readPositiveIdFromPath(path);
      return await deleteWant(request, wantId, env);
    }

    return json({ error: "Rota não encontrada" }, 404);
  } catch (error) {
    return errorResponse(error);
  }
}

/*
 * Objeto exigido pelo Cloudflare Workers.
 *
 * Se o caminho começa com /api/, entregamos a requisição ao nosso backend.
 * Qualquer outro caminho é um arquivo estático de public/.
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname.startsWith("/api/")) {
      return await handleApi(request, env);
    }

    return env.ASSETS.fetch(request);
  }
};
