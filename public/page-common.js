/*
 * Utilidades das páginas públicas independentes do ManaPonte.
 */
(function (global) {
  "use strict";

  const API_BASE = String(global.MANAPONTE_API_BASE || "")
    .trim()
    .replace(/\/+$/, "");

  const query = new URLSearchParams(global.location.search);
  const STATIC_MODE =
    query.has("static") ||
    (
      !API_BASE &&
      (
        global.location.hostname.endsWith("github.io") ||
        global.location.protocol === "file:"
      )
    );

  function apiUrl(path) {
    return API_BASE && String(path).startsWith("/api/")
      ? `${API_BASE}${path}`
      : path;
  }

  async function getJson(path, options) {
    const response = await fetch(apiUrl(path), {
      credentials: "include",
      ...(options || {}),
    });

    const type = response.headers.get("content-type") || "";
    if (!type.includes("application/json")) {
      throw Object.assign(
        new Error("Resposta inesperada do servidor"),
        { status: response.status },
      );
    }

    const data = await response.json();
    if (!response.ok) {
      throw Object.assign(
        new Error(data.error || "Falha na requisição"),
        { status: response.status },
      );
    }

    return data;
  }

  const esc = value => String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[character]));

  function money(cents) {
    if (cents == null) {
      return "Proposta / troca";
    }

    return new Intl.NumberFormat("pt-BR", {
      style: "currency",
      currency: "BRL",
    }).format(cents / 100);
  }

  function formatPhone(value) {
    const raw = String(value || "").trim();
    if (!raw) {
      return "";
    }

    const digits = raw.replace(/\D/g, "");
    if (digits.length === 11) {
      return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
    }
    if (digits.length === 13 && digits.startsWith("55")) {
      return `+55 (${digits.slice(2, 4)}) ${digits.slice(4, 9)}-${digits.slice(9)}`;
    }
    return raw;
  }

  function phoneHref(value) {
    const raw = String(value || "").trim();
    if (!raw) {
      return "";
    }
    const digits = raw.replace(/\D/g, "");
    return raw.startsWith("+") ? `tel:+${digits}` : `tel:${digits}`;
  }

  function whatsappHref(value, message = "") {
    const raw = String(value || "").trim();
    if (!raw) {
      return "";
    }

    let digits = raw.replace(/\D/g, "");
    // Perfis brasileiros normalmente informam DDD + número. O WhatsApp exige
    // DDI, então acrescentamos 55 quando não foi informado.
    if (!raw.startsWith("+") && [10, 11].includes(digits.length)) {
      digits = `55${digits}`;
    }

    const text = String(message || "").trim();
    return `https://wa.me/${digits}${text ? `?text=${encodeURIComponent(text)}` : ""}`;
  }

  global.ManaPontePage = {
    API_BASE,
    STATIC_MODE,
    apiUrl,
    getJson,
    esc,
    money,
    formatPhone,
    phoneHref,
    whatsappHref,
  };
}(window));
