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
  } = window.ManaPontePage;

  const $ = selector => document.querySelector(selector);

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

    document.title = `${item.title || cardName} — ManaPonte`;
    $("#listingDetailCardImage").src = item.image_url;
    $("#listingDetailCardImage").alt = cardName;
    $("#listingDetailCardImage").dataset.cardLabel = cardName;
    $("#listingDetailMode").textContent = item.mode;
    $("#listingDetailTitle").textContent = item.title || cardName;
    $("#listingDetailCardName").textContent = cardName;
    $("#listingDetailMeta").textContent =
      `${String(item.set_code || "").toUpperCase()} · #${item.collector_number} · ` +
      `${String(item.language || "en").toUpperCase()} · ${item.condition}`;
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
        `Olá! Vi seu anúncio "${item.title || cardName}" no ManaPonte.`,
      );
    }

    $("#listingDetailContent").hidden = false;
    $("#listingDetailStatus").textContent = "";
  }

  load().catch(error => {
    $("#listingDetailStatus").textContent = error.message;
  });
}());
