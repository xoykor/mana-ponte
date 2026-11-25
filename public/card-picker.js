/*
 * SELETOR DE CARTAS (MAGIC & POKÉMON)
 * ===================================
 *
 * Pesquisa cartas, mostra resultados e guarda qual impressão foi escolhida.
 * O estado fica dentro de create(), então várias instâncias podem coexistir.
 */

/*
 * Componente de busca e seleção de uma impressão de carta.
 *
 * O componente não conhece o restante do formulário. Ele apenas recebe um
 * elemento raiz e devolve pequenas funções para limpar, focar, trocar o jogo
 * ativo e ler a carta selecionada.
 */
(function (global) {
  "use strict";

  const POKEMON_LANGUAGES = new Set([
    "",
    "pt",
    "en",
    "es",
    "fr",
    "de",
    "it",
    "ja",
    "ko",
    "zhs",
    "zht",
  ]);

  const esc = value => String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[character]));

  /* Cria uma instância independente do seletor. */
  function create(options) {
    const root = options.root;

    // Cada seletor aponta para uma parte específica do HTML do modal.
    const search = root.querySelector("[data-card-search]");
    const results = root.querySelector("[data-card-results]");
    const selectedView = root.querySelector("[data-card-selected]");
    const hidden =
      root.querySelector("[data-card-id]") ||
      root.querySelector("input[name='card_id']");
    const hint = root.querySelector("[data-card-hint]");
    const language = root.querySelector("[data-card-language]");

    const source = options.source || "/api/cards";

    // Estado privado desta instância do componente.
    let currentGame = String(options.game || root.dataset.game || "mtg")
      .trim()
      .toLowerCase();
    let staticCards = Array.isArray(options.staticCards)
      ? options.staticCards
      : null;
    let selectedCard = null;
    let resultCards = [];
    let timer = null;
    let controller = null;
    let requestId = 0;
    let nextPage = 1;
    let hasMore = false;

    /* Sincroniza opções de idioma e placeholder conforme o TCG ativo. */
    function syncLanguageOptionsForGame() {
      if (search) {
        search.placeholder = currentGame === "pokemon"
          ? "Ex.: Pikachu, Charizard ex…"
          : "Ex.: Sol Ring, Rhystic Study…";
      }

      if (!language) {
        return;
      }

      const isPokemon = currentGame === "pokemon";
      [...language.options].forEach(option => {
        const supported = !isPokemon || POKEMON_LANGUAGES.has(option.value);
        option.hidden = !supported;
        option.disabled = !supported;
      });

      if (isPokemon && !POKEMON_LANGUAGES.has(language.value)) {
        language.value = "";
      }
    }

    /* Cancela/ignora pesquisa antiga quando o texto muda. */
    function invalidatePendingRequest() {
      clearTimeout(timer);
      timer = null;

      if (controller) {
        controller.abort();
        controller = null;
      }

      requestId += 1;
    }

    /* Escolhe o melhor nome para mostrar. */
    function displayName(card) {
      return card?.printed_name || card?.printedName || card?.name || "Carta";
    }

    /* Monta o texto completo de uma opção. */
    function label(card) {
      const set = String(card.set_code || card.setCode || "").toUpperCase();
      const number = card.collector_number || card.collectorNumber || "";
      const lang = String(card.language || card.lang || "").toUpperCase();
      return (
        `${displayName(card)} — ${set}${number ? ` #${number}` : ""}` +
        `${lang ? ` · ${lang}` : ""}`
      );
    }

    /* Abre a imagem ampliada quando disponível. */
    function showZoom(card) {
      const image = card?.image_url || card?.imageUrl || "";
      if (!image) {
        return;
      }

      global.ManaPonteCardPreview?.open(image, label(card));
    }

    /* Atualiza a interface após selecionar uma carta. */
    function renderSelected() {
      if (!selectedCard) {
        selectedView.hidden = true;
        selectedView.innerHTML = "";
        hidden.value = "";
        return;
      }

      selectedView.hidden = false;
      selectedView.innerHTML = `
        <strong>Selecionada:</strong>
        ${esc(label(selectedCard))}
        <button
          type="button"
          data-card-clear
          aria-label="Remover carta"
        >×</button>
      `;
      hidden.value = selectedCard.id ?? "";
      selectedView.querySelector("[data-card-clear]").onclick = clear;
    }

    /* Desenha os resultados da pesquisa. */
    function renderResults(cards, message, append = false) {
      resultCards = append ? resultCards.concat(cards) : cards;

      if (!resultCards.length) {
        results.innerHTML = message
          ? `<p class="card-picker-empty">${esc(message)}</p>`
          : "";
        return;
      }

      results.innerHTML = resultCards.map((card, index) => {
        const image = card.image_url || card.imageUrl || "";
        const thumbSrc = image || "assets/card-placeholder.svg";
        const set = String(card.set_code || card.setCode || "").toUpperCase();
        const setName = card.set_name ? ` (${esc(card.set_name)})` : "";
        const number = card.collector_number
          ? ` · #${esc(card.collector_number)}`
          : "";
        const cardLanguage = card.language || card.lang;
        const langText = cardLanguage
          ? ` · ${esc(String(cardLanguage).toUpperCase())}`
          : "";

        return `
          <div class="card-picker-result">
            <button
              type="button"
              class="card-picker-zoom"
              data-card-zoom="${index}"
              aria-label="Ampliar ${esc(displayName(card))}"
              ${image ? "" : "disabled"}
            >
              <span class="card-picker-thumb">
                <img
                  src="${esc(thumbSrc)}"
                  alt=""
                  loading="lazy"
                  ${image ? `data-card-image data-card-label="${esc(label(card))}"` : ""}
                >
              </span>
            </button>
            <button
              type="button"
              class="card-picker-select"
              data-card-index="${index}"
              role="option"
            >
              <span>
                <strong>${esc(displayName(card))}</strong>
                <small>${esc(set)}${setName}${number}${langText}</small>
              </span>
            </button>
          </div>
        `;
      }).join("");

      results.querySelectorAll("[data-card-zoom]").forEach(button => {
        button.onclick = () => {
          showZoom(resultCards[Number(button.dataset.cardZoom)]);
        };
      });

      results.querySelectorAll("[data-card-index]").forEach(button => {
        button.onclick = () => {
          select(resultCards[Number(button.dataset.cardIndex)]);
        };
      });

      if (hasMore) {
        const more = document.createElement("button");
        more.type = "button";
        more.className = "card-picker-more";
        more.dataset.cardMore = "";
        more.textContent = "Mostrar mais impressões";
        more.onclick = () => searchCards({ page: nextPage, append: true });
        results.appendChild(more);
      }
    }

    /* Marca uma impressão como escolhida. */
    function select(card) {
      invalidatePendingRequest();
      selectedCard = card || null;

      if (selectedCard?.game) {
        currentGame = String(selectedCard.game).toLowerCase();
        syncLanguageOptionsForGame();
      }

      const selectedLanguage = String(
        selectedCard?.language || selectedCard?.lang || ""
      ).toLowerCase();
      if (
        language &&
        selectedLanguage &&
        [...language.options].some(
          option => option.value === selectedLanguage && !option.disabled
        )
      ) {
        language.value = selectedLanguage;
      }

      resultCards = [];
      nextPage = 1;
      hasMore = false;
      renderSelected();
      renderResults([], "");
      search.value = selectedCard ? label(selectedCard) : "";

      if (hint) {
        hint.textContent = selectedCard
          ? "A impressão selecionada será vinculada à oferta."
          : "Digite pelo menos 2 caracteres para buscar no catálogo.";
      }

      root.dispatchEvent(
        new CustomEvent("cardselected", { detail: selectedCard })
      );
    }

    /* Limpa seleção e estado visual. */
    function clear() {
      invalidatePendingRequest();
      selectedCard = null;
      resultCards = [];
      nextPage = 1;
      hasMore = false;
      renderSelected();
      search.value = "";
      renderResults([], "");

      if (hint) {
        hint.textContent = "Digite pelo menos 2 caracteres para buscar no catálogo.";
      }

      root.dispatchEvent(
        new CustomEvent("cardselected", { detail: null })
      );
    }

    /* Altera o jogo ativo (mtg ou pokemon) e limpa seleção incompatível. */
    function setGame(nextGame) {
      const normalized = String(nextGame || "mtg").trim().toLowerCase();
      if (normalized === currentGame) {
        syncLanguageOptionsForGame();
        return;
      }

      currentGame = normalized;
      syncLanguageOptionsForGame();

      if (selectedCard && String(selectedCard.game || "mtg").toLowerCase() !== currentGame) {
        clear();
        return;
      }

      invalidatePendingRequest();
      resultCards = [];
      nextPage = 1;
      hasMore = false;
      renderResults([], "");

      if (search.value.trim().length >= 2) {
        searchCards();
      }
    }

    /* Pesquisa cartas em memória no modo estático. */
    function staticSearch(query) {
      const normalized = query.toLocaleLowerCase();
      const requestedLanguage = String(language?.value || "").toLowerCase();

      return staticCards
        .filter(card =>
          (!currentGame || String(card.game || "mtg").toLowerCase() === currentGame) &&
          (!requestedLanguage ||
            String(card.language || card.lang || "").toLowerCase() === requestedLanguage) &&
          `${card.name} ${card.printed_name || card.printedName || ""} ${card.set_code} ${card.collector_number}`
            .toLocaleLowerCase()
            .includes(normalized)
        )
        .slice(0, 20);
    }

    /* Pesquisa cartas na API ou localmente. */
    async function searchCards({ page = 1, append = false } = {}) {
      const query = search.value.trim();

      if (query.length < 2) {
        invalidatePendingRequest();
        resultCards = [];
        nextPage = 1;
        hasMore = false;
        renderResults(
          [],
          query ? "Digite mais caracteres para buscar." : ""
        );
        return;
      }

      if (staticCards) {
        hasMore = false;
        const found = staticSearch(query);
        renderResults(
          found,
          found.length ? "" : "Nenhuma carta encontrada no catálogo local."
        );
        return;
      }

      if (controller) {
        controller.abort();
        controller = null;
      }
      controller = new AbortController();
      const currentRequest = ++requestId;

      if (append) {
        const more = results.querySelector("[data-card-more]");
        if (more) {
          more.disabled = true;
          more.textContent = "Carregando…";
        }
      } else {
        hasMore = false;
        renderResults([], "Buscando no catálogo…");
      }

      try {
        const url = new URL(source, global.location.href);
        url.searchParams.set("q", query);
        if (currentGame) {
          url.searchParams.set("game", currentGame);
        }
        if (language?.value) {
          url.searchParams.set("lang", language.value);
        }
        url.searchParams.set("page", String(page));
        url.searchParams.set("limit", "20");

        const response = await fetch(url, {
          signal: controller.signal,
          credentials: "include",
        });
        if (!response.ok) {
          throw new Error("Não foi possível consultar o catálogo.");
        }

        const payload = await response.json();

        if (currentRequest !== requestId) {
          return;
        }

        controller = null;

        const found = payload.cards || payload.data || [];
        const returnedPage = Number(payload.page) || page;
        const limit = Number(payload.limit) || 20;
        const total = Number(payload.total);

        nextPage = returnedPage + 1;
        hasMore = found.length > 0 && (
          Number.isFinite(total)
            ? total > returnedPage * limit
            : found.length >= limit
        );
        renderResults(
          found,
          found.length ? "" : "Nenhuma carta encontrada.",
          append
        );
      } catch (error) {
        if (error.name === "AbortError") {
          return;
        }

        if (currentRequest !== requestId) {
          return;
        }

        controller = null;
        if (append) {
          const more = results.querySelector("[data-card-more]");
          if (more) {
            more.disabled = false;
            more.textContent = "Mostrar mais impressões";
          }
          return;
        }

        hasMore = false;
        renderResults([], error.message || "Erro ao buscar carta.");
      }
    }

    search.addEventListener("input", () => {
      clearTimeout(timer);
      timer = null;

      if (selectedCard) {
        selectedCard = null;
        renderSelected();
        root.dispatchEvent(
          new CustomEvent("cardselected", { detail: null })
        );
      }

      invalidatePendingRequest();
      resultCards = [];
      nextPage = 1;
      hasMore = false;
      renderResults([], "");
      timer = setTimeout(() => {
        timer = null;
        searchCards();
      }, 220);
    });

    language?.addEventListener("change", () => {
      const previous = selectedCard;
      if (previous) {
        search.value = displayName(previous);
        selectedCard = null;
        renderSelected();
        root.dispatchEvent(
          new CustomEvent("cardselected", { detail: null })
        );
      }

      invalidatePendingRequest();
      resultCards = [];
      nextPage = 1;
      hasMore = false;
      renderResults([], "");

      if (search.value.trim().length >= 2) {
        searchCards();
      }
    });

    search.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        clear();
        search.blur();
      }
    });

    syncLanguageOptionsForGame();

    return {
      clear,
      focus: () => search.focus(),
      getGame: () => currentGame,
      getSelectedCard: () => selectedCard,
      setGame,
      setStaticCards: cards => {
        invalidatePendingRequest();
        staticCards = Array.isArray(cards) ? cards : null;
      },
      search: searchCards,
      select,
    };
  }

  global.ManaBridgeCardPicker = { create };
}(window));
