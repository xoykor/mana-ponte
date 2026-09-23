/*
 * PERFIL PÚBLICO
 * ==============
 *
 * Lê ?user=ID, busca /api/users/ID e desenha dados públicos, anúncios e desejos.
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
  } = window.ManaPontePage;

  const $ = selector => document.querySelector(selector);

  /* Transforma a data do banco em formato amigável. */
  function formatDate(value) {
    if (!value) {
      return "—";
    }
    const date = new Date(String(value).replace(" ", "T") + "Z");
    if (Number.isNaN(date.getTime())) {
      return "—";
    }
    return new Intl.DateTimeFormat("pt-BR", {
      month: "long",
      year: "numeric",
    }).format(date);
  }

  /* Desenha os anúncios publicados pelo perfil. */
  function renderListings(listings) {
    const entries = Array.isArray(listings) ? listings : [];

    if (!entries.length) {
      $("#profilePageListings").innerHTML =
        '<p class="empty-state">Este jogador não tem anúncios ativos.</p>';
      return;
    }

    $("#profilePageListings").innerHTML = entries.map(item => {
      const name = String(item.name || "Carta");
      return `
        <article class="listing">
          <img
            loading="lazy"
            src="${esc(item.image_url)}"
            alt="${esc(name)}"
            data-card-image
            data-card-label="${esc(name)}"
            tabindex="0"
            role="button"
          >
          <div>
            <span class="badge">${esc(item.mode)}</span>
            <h3>
              <a class="listing-title-link" href="anuncio.html?id=${encodeURIComponent(item.id)}">
                ${esc(item.title || name)}
              </a>
            </h3>
            <p class="card-name">${esc(name)}</p>
            <div class="meta">
              ${esc(String(item.set_code || "").toUpperCase())}
              · ${esc(item.condition)}
              · ${esc(String(item.language || "en").toUpperCase())}            </div>
            <div class="price">${money(item.price_cents)}</div>
            ${item.description
              ? `<p class="description">${esc(item.description)}</p>`
              : ""}
          </div>
        </article>
      `;
    }).join("");
  }

  /* Desenha as cartas procuradas pelo perfil. */
  function renderWants(wants) {
    const entries = Array.isArray(wants) ? wants : [];
    if (!entries.length) {
      $("#profilePageWants").innerHTML =
        '<p class="empty-state">Este jogador não publicou cartas procuradas.</p>';
      return;
    }

    $("#profilePageWants").innerHTML = entries.map(item => `
      <article class="account-item">
        <img
          src="${esc(item.image_url)}"
          alt="${esc(item.name)}"
          data-card-image
          data-card-label="${esc(item.name)}"
          tabindex="0"
          role="button"
        >
        <div>
          <h4>${esc(item.name)}</h4>
          <p class="meta">
            ${esc(String(item.set_code || "").toUpperCase())}
            · ${esc(item.mode)}
            · idioma: ${esc(String(item.desired_language || "qualquer").toUpperCase())}
            · condição mínima: ${esc(item.desired_condition || "qualquer")}
            · máximo: ${money(item.max_price_cents)}
          </p>
        </div>
      </article>
    `).join("");
  }

  /* Busca o perfil da URL e preenche a página. */
  async function loadProfile() {
    if (STATIC_MODE) {
      throw new Error(
        "Perfis públicos exigem a API. Configure MANAPONTE_API_BASE para usar esta página no Pages."
      );
    }

    const userId = Number(new URLSearchParams(location.search).get("user"));
    if (!Number.isInteger(userId) || userId <= 0) {
      throw new Error("Perfil inválido: informe um usuário na URL.");
    }

    const data = await getJson(`/api/users/${userId}`);
    const user = data.user;
    const stats = data.stats || {};

    document.title = `${user.display_name} — ManaPonte`;
    $("#profilePageName").textContent = user.display_name;
    $("#profilePageHandle").textContent = `@${user.username}`;
    $("#profilePageLocation").textContent = `${user.city} / ${user.state}`;
    $("#profilePageJoined").textContent = formatDate(user.created_at);
    $("#profilePageListingCount").textContent = String(stats.listing_count || 0);
    $("#profilePageWantCount").textContent = String(stats.want_count || 0);

    const phone = String(user.phone || "").trim();
    if (phone) {
      const phoneLink = $("#profilePagePhone");
      phoneLink.hidden = false;
      phoneLink.href = phoneHref(phone);
      phoneLink.textContent = `Ligar: ${formatPhone(phone)}`;

      const whatsapp = $("#profilePageWhatsapp");
      whatsapp.hidden = false;
      whatsapp.href = whatsappHref(
        phone,
        `Olá, ${user.display_name}! Encontrei seu perfil no ManaPonte.`,
      );
      $("#profilePageNoPhone").hidden = true;
    }

    renderListings(data.listings);
    renderWants(data.wants);
    $("#profilePageStatus").textContent = "";
  }

  loadProfile().catch(error => {
    $("#profilePageName").textContent = "Perfil indisponível";
    $("#profilePageStatus").textContent = error.message;
    $("#profilePageListings").innerHTML = "";
    $("#profilePageWants").innerHTML = "";
  });
}());
