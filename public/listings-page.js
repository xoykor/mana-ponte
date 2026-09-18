(function () {
  "use strict";

  const {
    STATIC_MODE,
    getJson,
    esc,
    money,
  } = window.ManaPontePage;

  const $ = selector => document.querySelector(selector);
  const STORAGE_KEY = "manaponte-demo-listings";
  const PAGE_SIZE = 24;
  const STATES = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
    "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
    "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
  ];

  let page = 1;
  let total = 0;
  let staticListings = [];

  function savedListings() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    } catch {
      return [];
    }
  }

  function listingModeMatches(itemMode, selectedMode) {
    if (!selectedMode) {
      return true;
    }
    if (selectedMode === "venda") {
      return itemMode === "venda" || itemMode === "ambos";
    }
    if (selectedMode === "troca") {
      return itemMode === "troca" || itemMode === "ambos";
    }
    return itemMode === selectedMode;
  }

  function populateStates() {
    const select = $("#listingState");
    for (const state of STATES) {
      const option = document.createElement("option");
      option.value = state;
      option.textContent = state;
      select.append(option);
    }
  }

  function populateSets(source) {
    const select = $("#listingSet");
    const sets = [
      ...new Map(
        source
          .filter(item => item.set_code)
          .map(item => [item.set_code, item.set_name || item.set_code])
      ).entries(),
    ].sort((a, b) => a[1].localeCompare(b[1]));

    for (const [code, name] of sets) {
      const option = document.createElement("option");
      option.value = code;
      option.textContent = `${name} (${String(code).toUpperCase()})`;
      select.append(option);
    }
  }

  function currentFilters() {
    return {
      card: $("#listingSearch").value.trim(),
      set: $("#listingSet").value,
      city: $("#listingCity").value.trim(),
      state: $("#listingState").value,
      mode: $("#listingMode").value,
    };
  }

  function applyFiltersFromUrl() {
    const params = new URLSearchParams(location.search);

    $("#listingSearch").value = params.get("card") || "";
    $("#listingCity").value = params.get("city") || "";

    const set = params.get("set") || "";
    if ([...$("#listingSet").options].some(option => option.value === set)) {
      $("#listingSet").value = set;
    }

    const state = String(params.get("state") || "").toUpperCase();
    if (STATES.includes(state)) {
      $("#listingState").value = state;
    }

    const requestedMode = params.get("mode") || "";
    if (["", "venda", "troca", "ambos"].includes(requestedMode)) {
      $("#listingMode").value = requestedMode;
    }
  }

  function syncUrlWithFilters() {
    const query = new URLSearchParams();
    Object.entries(currentFilters()).forEach(([key, value]) => {
      if (value) {
        query.set(key, value);
      }
    });

    if (new URLSearchParams(location.search).has("static")) {
      query.set("static", "1");
    }

    const suffix = query.toString();
    history.replaceState(
      null,
      "",
      suffix ? `anuncios.html?${suffix}` : "anuncios.html",
    );
  }

  function render(entries, meta = {}) {
    const items = Array.isArray(entries) ? entries : [];
    total = Number(meta.total ?? items.length);
    page = Number(meta.page ?? 1);
    const limit = Number(meta.limit ?? PAGE_SIZE);
    const pageCount = Math.max(1, Math.ceil(total / limit));

    $("#listingPageStatus").textContent =
      `${total} ${total === 1 ? "anúncio encontrado" : "anúncios encontrados"}`;
    $("#listingPagePagination").hidden = pageCount <= 1;
    $("#listingPrev").disabled = page <= 1;
    $("#listingNext").disabled = page >= pageCount;
    $("#listingPageNumber").textContent = `Página ${page} de ${pageCount}`;

    if (!items.length) {
      $("#listingPageGrid").innerHTML =
        '<p class="empty-state">Nenhum anúncio encontrado com esses filtros.</p>';
      return;
    }

    $("#listingPageGrid").innerHTML = items.map(item => {
      const name = String(item.name || "Carta");
      const profile = !STATIC_MODE && item.user_id
        ? `<a class="secondary compact profile-link" href="perfil.html?user=${encodeURIComponent(item.user_id)}">Ver perfil</a>`
        : "";

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
            ${item.description ? `<p class="description">${esc(item.description)}</p>` : ""}
            <div class="meta">
              ${esc(item.city || "")} · ${esc(item.state || "")}<br>
              por ${esc(item.display_name || "Jogador")}
            </div>
            ${profile}
          </div>
        </article>
      `;
    }).join("");
  }

  async function load(targetPage = 1) {
    $("#listingPageStatus").textContent = "Buscando anúncios…";
    const filters = currentFilters();

    try {
      if (STATIC_MODE) {
        const normalizedCard = filters.card.toLocaleLowerCase();
        const filtered = [...savedListings(), ...staticListings].filter(item =>
          (!filters.card ||
            String(item.name || "").toLocaleLowerCase().includes(normalizedCard)) &&
          (!filters.set || item.set_code === filters.set) &&
          (!filters.city ||
            String(item.city || "").toLocaleLowerCase() ===
              filters.city.toLocaleLowerCase()) &&
          (!filters.state || item.state === filters.state) &&
          listingModeMatches(item.mode, filters.mode)
        );

        render(filtered, {
          total: filtered.length,
          page: 1,
          limit: Math.max(filtered.length, PAGE_SIZE),
        });
        return;
      }

      const query = new URLSearchParams();
      Object.entries(filters).forEach(([key, value]) => {
        if (value) {
          query.set(key, value);
        }
      });
      query.set("page", String(targetPage));
      query.set("limit", String(PAGE_SIZE));

      const data = await getJson(`/api/listings?${query}`);
      render(data.listings, data);
    } catch (error) {
      $("#listingPageStatus").textContent = error.message;
      $("#listingPageGrid").innerHTML = "";
    }
  }

  async function initialize() {
    populateStates();

    if (STATIC_MODE) {
      const [cardsPayload, listingsPayload] = await Promise.all([
        getJson("data/cards.json"),
        getJson("data/listings.json"),
      ]);
      staticListings = listingsPayload.listings || [];
      populateSets(cardsPayload.cards || staticListings);
    } else {
      const sets = await getJson("/api/sets");
      populateSets(sets.sets || []);
    }

    // Os parâmetros vindos da home só são aplicados depois que UF e coleções
    // já existem nos selects.
    applyFiltersFromUrl();
    await load(1);
  }

  $("#listingFilters").addEventListener("submit", event => {
    event.preventDefault();
    syncUrlWithFilters();
    load(1);
  });

  $("#listingPrev").addEventListener("click", () => {
    if (page > 1) {
      load(page - 1);
    }
  });

  $("#listingNext").addEventListener("click", () => {
    load(page + 1);
  });

  initialize().catch(error => {
    $("#listingPageStatus").textContent = error.message;
  });
}());
