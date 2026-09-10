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
     * Produz a identificação curta exibida para uma impressão.
     */
    function label(card) {
      const set = String(card.set_code || card.setCode || "").toUpperCase();
      const number = card.collector_number || card.collectorNumber || "";
      return `${card.name || "Carta"} — ${set}${number ? ` #${number}` : ""}`;
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
        const language = card.language
          ? ` · ${esc(card.language.toUpperCase())}`
          : "";

        return `
          <button
            type="button"
            class="card-picker-result"
            data-card-index="${index}"
            role="option"
          >
            <span class="card-picker-thumb">
              ${image
                ? `<img src="${esc(image)}" alt="" loading="lazy">`
                : ""}
            </span>
            <span>
              <strong>${esc(card.name)}</strong>
              <small>${esc(set)}${number}${language}</small>
            </span>
          </button>
        `;
      }).join("");

      // Cada botão precisa apontar para o objeto da mesma posição no array.
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
      selectedCard = card || null;
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
      selectedCard = null;
      hasMore = false;
      renderSelected();
      search.value = "";
      renderResults([], "");

      if (hint) {
        hint.textContent = "Digite pelo menos 2 caracteres para buscar no catálogo.";
      }
    }


    /**
     * Filtra os cards que já estão na memória em modo estático.
     */
    function staticSearch(query) {
      const normalized = query.toLocaleLowerCase();

      return staticCards
        .filter(card =>
          `${card.name} ${card.set_code} ${card.collector_number}`
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
        url.searchParams.set("page", String(page));
        url.searchParams.set("limit", "20");

        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) {
          throw new Error("Não foi possível consultar o catálogo.");
        }

        const payload = await response.json();

        // Uma busca nova pode ter terminado enquanto esta resposta chegava.
        if (currentRequest !== requestId) {
          return;
        }

        const found = payload.cards || payload.data || [];
        const returnedPage = Number(payload.page) || page;
        const limit = Number(payload.limit) || 20;
        const total = Number(payload.total) || 0;

        nextPage = returnedPage + 1;
        hasMore = found.length > 0 && total > returnedPage * limit;
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

        hasMore = append;
        renderResults(
          append ? resultCards : [],
          error.message || "Erro ao buscar carta."
        );
      }
    }


    // O pequeno atraso evita uma requisição a cada tecla digitada.
    search.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(searchCards, 220);
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
        staticCards = Array.isArray(cards) ? cards : null;
      },
      search: searchCards,
      select,
    };
  }


  // Expõe somente o construtor do componente no objeto global da página.
  global.ManaBridgeCardPicker = { create };
}(window));
