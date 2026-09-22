/*
 * Componente de busca e seleção de uma impressão de carta.
 *
 * O componente não conhece o restante do formulário. Ele apenas recebe um
 * elemento raiz e devolve pequenas funções para limpar, focar e ler a carta
 * selecionada. Essa separação deixa o código reutilizável e mais fácil de
 * testar mentalmente.
 */
(function (global) {
  "use strict";

  /**
   * Escapa valores que serão inseridos em HTML.
   *
   * O nome da carta e outros metadados vêm do catálogo; nunca devemos assumir
   * que esses textos são seguros para serem colocados em uma template string.
   */
  const esc = value => String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[character]));


  /**
   * Inicializa um seletor dentro de ``options.root``.
   *
   * ``options.staticCards`` é usado pelo GitHub Pages. Quando ele é nulo, as
   * buscas vão para a rota indicada em ``options.source``.
   */
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

    // O endpoint normal é o backend local, mas pode ser substituído por uma
    // rota diferente em uma página incorporada.
    const source = options.source || "/api/cards";

    // Estado privado desta instância do componente.
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


    /**
     * Cancela buscas pendentes e invalida respostas que já estejam a caminho.
     */
    function invalidatePendingRequest() {
      clearTimeout(timer);
      timer = null;

      if (controller) {
        controller.abort();
        controller = null;
      }

      requestId += 1;
    }


    /**
     * Nome visível da impressão; prioriza a tradução quando disponível.
     */
    function displayName(card) {
      return card?.printed_name || card?.printedName || card?.name || "Carta";
    }


    /**
     * Produz a identificação curta exibida para uma impressão.
     */
    function label(card) {
      const set = String(card.set_code || card.setCode || "").toUpperCase();
      const number = card.collector_number || card.collectorNumber || "";
      const lang = String(card.language || card.lang || "").toUpperCase();
      return (
        `${displayName(card)} — ${set}${number ? ` #${number}` : ""}` +
        `${lang ? ` · ${lang}` : ""}`
      );
    }


    /**
     * Encaminha a ampliação para o componente global compartilhado pelo site.
     */
    function showZoom(card) {
      const image = card?.image_url || card?.imageUrl || "";
      if (!image) {
        return;
      }

      global.ManaPonteCardPreview?.open(image, label(card));
    }

    /**
     * Atualiza a área que mostra a carta escolhida e o input escondido.
     */
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


    /**
     * Desenha resultados novos ou acrescenta uma página à lista existente.
     */
    function renderResults(cards, message, append = false) {
      // Quando ``append`` é verdadeiro, preservamos os resultados anteriores.
      resultCards = append ? resultCards.concat(cards) : cards;

      if (!resultCards.length) {
        results.innerHTML = message
          ? `<p class="card-picker-empty">${esc(message)}</p>`
          : "";
        return;
      }

      results.innerHTML = resultCards.map((card, index) => {
        const image = card.image_url || card.imageUrl || "";
        const set = String(card.set_code || card.setCode || "").toUpperCase();
        const number = card.collector_number
          ? ` · #${esc(card.collector_number)}`
          : "";
        const cardLanguage = card.language || card.lang;
        const language = cardLanguage
          ? ` · ${esc(String(cardLanguage).toUpperCase())}`
          : "";

        return `
          <div class="card-picker-result">
            <button
              type="button"
              class="card-picker-zoom"
              data-card-zoom="${index}"
              aria-label="Ampliar ${esc(card.name)}"
              ${image ? "" : "disabled"}
            >
              <span class="card-picker-thumb">
                ${image
                  ? `<img src="${esc(image)}" alt="" loading="lazy" data-card-image data-card-label="${esc(label(card))}">`
                  : ""}
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
                <small>${esc(set)}${number}${language}</small>
              </span>
            </button>
          </div>
        `;
      }).join("");

      // A imagem amplia; o restante da linha seleciona a impressão.
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

      // O botão de paginação fica depois dos resultados, mas dentro da mesma
      // área rolável, para que o usuário possa pedir mais impressões.
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


    /**
     * Marca uma carta como escolhida e limpa a lista de resultados.
     */
    function select(card) {
      invalidatePendingRequest();
      selectedCard = card || null;

      const selectedLanguage = String(
        selectedCard?.language || selectedCard?.lang || ""
      ).toLowerCase();
      if (
        language &&
        selectedLanguage &&
        [...language.options].some(option => option.value === selectedLanguage)
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

      // O formulário principal pode reagir sem conhecer a implementação
      // interna do componente.
      root.dispatchEvent(
        new CustomEvent("cardselected", { detail: selectedCard })
      );
    }


    /**
     * Remove a seleção atual e devolve o campo ao estado inicial.
     */
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


    /**
     * Filtra os cards que já estão na memória em modo estático.
     */
    function staticSearch(query) {
      const normalized = query.toLocaleLowerCase();
      const requestedLanguage = String(language?.value || "").toLowerCase();

      return staticCards
        .filter(card =>
          (!requestedLanguage ||
            String(card.language || card.lang || "").toLowerCase() === requestedLanguage) &&
          `${card.name} ${card.printed_name || card.printedName || ""} ${card.set_code} ${card.collector_number}`
            .toLocaleLowerCase()
            .includes(normalized)
        )
        .slice(0, 20);
    }


    /**
     * Busca uma página no catálogo remoto ou no catálogo estático.
     */
    async function searchCards({ page = 1, append = false } = {}) {
      const query = search.value.trim();

      // Evitamos chamadas muito amplas para entradas vazias ou pouco úteis.
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

      // Uma nova busca invalida a requisição anterior para evitar que uma
      // resposta lenta sobrescreva resultados mais recentes.
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

        // Uma busca nova pode ter terminado enquanto esta resposta chegava.
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
        // AbortError é esperado quando o visitante digita outra busca.
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


    // O pequeno atraso evita uma requisição a cada tecla digitada.
    search.addEventListener("input", () => {
      clearTimeout(timer);
      timer = null;

      // Editar o texto de uma carta selecionada invalida imediatamente o
      // vínculo antigo, antes mesmo de a nova busca terminar.
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

    // Trocar o idioma invalida uma impressão já escolhida e refaz a busca.
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


    // Escape limpa a seleção sem precisar clicar em outro controle.
    search.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        clear();
        search.blur();
      }
    });

    // A página principal usa esta API mínima para controlar o componente.
    return {
      clear,
      focus: () => search.focus(),
      getSelectedCard: () => selectedCard,
      setStaticCards: cards => {
        invalidatePendingRequest();
        staticCards = Array.isArray(cards) ? cards : null;
      },
      search: searchCards,
      select,
    };
  }


  // Expõe somente o construtor do componente no objeto global da página.
  global.ManaBridgeCardPicker = { create };
}(window));
