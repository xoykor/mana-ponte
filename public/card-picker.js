(function (global) {
  "use strict";

  const esc = value => String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[character]));

  function create(options) {
    const root = options.root;
    const search = root.querySelector("[data-card-search]");
    const results = root.querySelector("[data-card-results]");
    const selectedView = root.querySelector("[data-card-selected]");
    const hidden = root.querySelector("[data-card-id]") || root.querySelector("input[name='card_id']");
    const hint = root.querySelector("[data-card-hint]");
    const source = options.source || "/api/cards";
    let staticCards = Array.isArray(options.staticCards) ? options.staticCards : null;
    let selectedCard = null;
    let resultCards = [];
    let timer = null;
    let controller = null;
    let requestId = 0;

    function label(card) {
      const set = String(card.set_code || card.setCode || "").toUpperCase();
      const number = card.collector_number || card.collectorNumber || "";
      return `${card.name || "Carta"} — ${set}${number ? ` #${number}` : ""}`;
    }

    function renderSelected() {
      if (!selectedCard) {
        selectedView.hidden = true;
        selectedView.innerHTML = "";
        hidden.value = "";
        return;
      }
      selectedView.hidden = false;
      selectedView.innerHTML = `<strong>Selecionada:</strong> ${esc(label(selectedCard))}<button type="button" data-card-clear aria-label="Remover carta">×</button>`;
      hidden.value = selectedCard.id ?? "";
      selectedView.querySelector("[data-card-clear]").onclick = clear;
    }

    function renderResults(cards, message) {
      resultCards = cards;
      if (!cards.length) {
        results.innerHTML = message ? `<p class="card-picker-empty">${esc(message)}</p>` : "";
        return;
      }
      results.innerHTML = cards.map((card, index) => {
        const image = card.image_url || card.imageUrl || "";
        const set = String(card.set_code || card.setCode || "").toUpperCase();
        return `<button type="button" class="card-picker-result" data-card-index="${index}" role="option"><span class="card-picker-thumb">${image ? `<img src="${esc(image)}" alt="" loading="lazy">` : ""}</span><span><strong>${esc(card.name)}</strong><small>${esc(set)}${card.collector_number ? ` · #${esc(card.collector_number)}` : ""}${card.language ? ` · ${esc(card.language.toUpperCase())}` : ""}</small></span></button>`;
      }).join("");
      results.querySelectorAll("[data-card-index]").forEach(button => {
        button.onclick = () => select(resultCards[Number(button.dataset.cardIndex)]);
      });
    }

    function select(card) {
      selectedCard = card || null;
      renderSelected();
      renderResults([], "");
      search.value = selectedCard ? label(selectedCard) : "";
      if (hint) hint.textContent = selectedCard ? "A impressão selecionada será vinculada à oferta." : "Digite pelo menos 2 caracteres para buscar no catálogo.";
      root.dispatchEvent(new CustomEvent("cardselected", { detail: selectedCard }));
    }

    function clear() {
      selectedCard = null;
      renderSelected();
      search.value = "";
      renderResults([], "");
      if (hint) hint.textContent = "Digite pelo menos 2 caracteres para buscar no catálogo.";
    }

    function staticSearch(query) {
      const normalized = query.toLocaleLowerCase();
      return staticCards.filter(card => `${card.name} ${card.set_code} ${card.collector_number}`.toLocaleLowerCase().includes(normalized)).slice(0, 20);
    }

    async function searchCards() {
      const query = search.value.trim();
      if (query.length < 2) {
        renderResults([], query ? "Digite mais caracteres para buscar." : "");
        return;
      }
      if (staticCards) {
        const found = staticSearch(query);
        renderResults(found, found.length ? "" : "Nenhuma carta encontrada no catálogo local.");
        return;
      }
      if (controller) controller.abort();
      controller = new AbortController();
      const currentRequest = ++requestId;
      renderResults([], "Buscando no catálogo…");
      try {
        const url = new URL(source, global.location.href);
        url.searchParams.set("q", query);
        url.searchParams.set("page", "1");
        url.searchParams.set("limit", "20");
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error("Não foi possível consultar o catálogo.");
        const payload = await response.json();
        if (currentRequest !== requestId) return;
        const found = payload.cards || payload.data || [];
        renderResults(found, found.length ? "" : "Nenhuma carta encontrada.");
      } catch (error) {
        if (error.name !== "AbortError") renderResults([], error.message || "Erro ao buscar carta.");
      }
    }

    search.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(searchCards, 220);
    });
    search.addEventListener("keydown", event => {
      if (event.key === "Escape") { clear(); search.blur(); }
    });

    return {
      clear,
      focus: () => search.focus(),
      getSelectedCard: () => selectedCard,
      setStaticCards: cards => { staticCards = Array.isArray(cards) ? cards : null; },
      search: searchCards,
      select
    };
  }

  global.ManaBridgeCardPicker = { create };
}(window));
