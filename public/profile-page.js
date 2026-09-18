(function () {
  "use strict";

  const {
    STATIC_MODE,
    getJson,
    esc,
    money,
    formatPhone,
    phoneHref,
  } = window.ManaPontePage;

  const $ = selector => document.querySelector(selector);

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
            <h3>${esc(item.title || name)}</h3>
            <p class="card-name">${esc(name)}</p>
            <div class="meta">
              ${esc(String(item.set_code || "").toUpperCase())}
              · ${esc(item.condition)}
              · ${esc(String(item.language || "en").toUpperCase())}
            </div>
            <div class="price">${money(item.price_cents)}</div>
            ${item.description
              ? `<p class="description">${esc(item.description)}</p>`
              : ""}
          </div>
        </article>
      `;
    }).join("");
  }

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

    document.title = `${user.display_name} — ManaPonte`;
    $("#profilePageName").textContent = user.display_name;
    $("#profilePageHandle").textContent = `@${user.username}`;
    $("#profilePageLocation").textContent = `${user.city} / ${user.state}`;

    const phone = String(user.phone || "").trim();
    if (phone) {
      const phoneLink = $("#profilePagePhone");
      phoneLink.hidden = false;
      phoneLink.href = phoneHref(phone);
      phoneLink.textContent = formatPhone(phone);
      $("#profilePageNoPhone").hidden = true;
    }

    renderListings(data.listings);
    $("#profilePageStatus").textContent = "";
  }

  loadProfile().catch(error => {
    $("#profilePageName").textContent = "Perfil indisponível";
    $("#profilePageStatus").textContent = error.message;
    $("#profilePageListings").innerHTML = "";
  });
}());
