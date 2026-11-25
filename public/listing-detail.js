/*
 * DETALHE DE UM ANÚNCIO
 * =====================
 *
 * Lê ?id=ID da URL, busca o anúncio e apresenta carta, preço, condição
 * e dados públicos do vendedor.
 */

(function () {
  "use strict";

  const {
    STATIC_MODE,
    getJson,
    esc,
    money,
    formatPhone,
    phoneHref,
    whatsappHref,
    gameShort,
    finishLabel,
    cardImageUrl,
  } = window.ManaPontePage;

  const $ = selector => document.querySelector(selector);

  /* Formata a data de criação do anúncio. */
  function formatDate(value) {
    if (!value) {
      return "";
    }
    const date = new Date(String(value).replace(" ", "T") + "Z");
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "medium",
    }).format(date);
  }

  /* Busca o anúncio indicado na URL e preenche a página. */
  async function load() {
    if (STATIC_MODE) {
      throw new Error("A página individual do anúncio exige a API.");
    }

    const listingId = Number(new URLSearchParams(location.search).get("id"));
    if (!Number.isInteger(listingId) || listingId <= 0) {
      throw new Error("Anúncio inválido.");
    }

    const data = await getJson(`/api/listings/${listingId}`);
    const item = data.listing;
    const cardName = String(item.name || "Carta");
    const itemGame = String(item.game || "mtg").toLowerCase();
    const extraFinish = item.finish && item.finish !== "normal"
      ? ` · ${finishLabel(item.finish)}`
      : "";

    document.title = `${item.title || cardName} — My Trade Box`;
    const art = $("#listingDetailCardImage");
    art.src = cardImageUrl(item.image_url);
    art.alt = cardName;
    if (item.image_url) {
      art.dataset.cardLabel = cardName;
    } else {
      art.removeAttribute("data-card-image");
    }

    const gameBadge = $("#listingDetailGame");
    if (gameBadge) {
      gameBadge.textContent = gameShort(itemGame);
      gameBadge.className = `badge game-badge game-${itemGame}`;
    }

    $("#listingDetailMode").textContent = item.mode;
    $("#listingDetailTitle").textContent = item.title || cardName;
    $("#listingDetailCardName").textContent = cardName;
    $("#listingDetailMeta").textContent =
      `${String(item.set_code || "").toUpperCase()} · #${item.collector_number} · ` +
      `${String(item.language || "en").toUpperCase()} · ${item.condition}${extraFinish}`;
    $("#listingDetailPrice").textContent = money(item.price_cents);
    $("#listingDetailDescription").textContent =
      item.description || "Sem descrição adicional.";

    const date = formatDate(item.created_at);
    $("#listingDetailDate").textContent = date ? `Publicado em ${date}` : "";

    $("#listingSellerName").textContent = item.display_name;
    $("#listingSellerLocation").textContent =
      `@${item.username} · ${item.city} / ${item.state}`;
    $("#listingSellerProfile").href =
      `perfil.html?user=${encodeURIComponent(item.user_id)}`;

    const phone = String(item.phone || "").trim();
    if (phone) {
      const phoneLink = $("#listingSellerPhone");
      phoneLink.hidden = false;
      phoneLink.href = phoneHref(phone);
      phoneLink.textContent = `Ligar: ${formatPhone(phone)}`;

      const whatsapp = $("#listingSellerWhatsapp");
      whatsapp.hidden = false;
      whatsapp.href = whatsappHref(
        phone,
        `Olá! Vi seu anúncio "${item.title || cardName}" no My Trade Box.`,
      );
    }

    $("#listingDetailContent").hidden = false;
    $("#listingDetailStatus").textContent = "";
  }

  load().catch(error => {
    $("#listingDetailStatus").textContent = error.message;
  });
}());
