/*
 * JavaScript principal da página pública do ManaPonte.
 *
 * Este arquivo coordena três grupos de responsabilidades:
 *
 * 1. carregar cartas, coleções e ofertas;
 * 2. renderizar os filtros e a vitrine;
 * 3. conversar com a autenticação e o formulário de anúncios.
 *
 * O mesmo HTML funciona em dois ambientes:
 *
 * - no servidor Python, usando as rotas ``/api/...``;
 * - no GitHub Pages, usando arquivos JSON e localStorage.
 */

// Atalho para encontrar um elemento do documento por seletor CSS.
const $ = selector => document.querySelector(selector);

// Uma API pública pode ser configurada em config.js. Sem ela, o GitHub Pages
// continua funcionando como demonstração estática.
const API_BASE = String(window.MANAPONTE_API_BASE || "")
  .trim()
  .replace(/\/+$/, "");
const queryFlags = new URLSearchParams(location.search);
const STATIC_MODE =
  queryFlags.has("static") ||
  (
    !API_BASE &&
    (location.hostname.endsWith("github.io") || location.protocol === "file:")
  );

function apiUrl(path) {
  return API_BASE && String(path).startsWith("/api/")
    ? `${API_BASE}${path}`
    : path;
}

// A chave guarda os anúncios criados localmente no modo demonstração.
const STORAGE_KEY = "manaponte-demo-listings";
const BRAZIL_STATES = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
  "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
  "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
];

// Estado carregado do catálogo e da sessão atual.
let cards = [];
let catalogSets = [];
let staticListings = [];
let mode = "";
let currentUser = null;
let csrfToken = null;
let cardPicker = null;
let wantCardPicker = null;
let editingListingId = null;
let myListingsById = new Map();
const LISTINGS_PAGE_SIZE = 24;
let listingsPage = 1;
let listingsTotal = 0;
let listingsLimit = LISTINGS_PAGE_SIZE;
let listingsRequestId = 0;
let listingsController = null;


/**
 * Escapa texto antes de inseri-lo dentro de HTML criado por template string.
 *
 * Os dados das cartas e dos usuários vêm de fontes externas ao navegador.
 * Mesmo em uma tela simples, escapar esses valores evita que um nome com
 * caracteres especiais seja interpretado como marcação HTML.
 */
const esc = value => String(value ?? "").replace(/[&<>"']/g, character => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#039;",
}[character]));


/**
 * Aceita somente URLs de contato com protocolo web e host não vazio.
 *
 * O backend faz a mesma validação. Repeti-la aqui impede que uma resposta
 * malformada ou um anúncio salvo por uma versão antiga vire um link perigoso
 * no navegador.
 */
function safeContactUrl(value) {
  const input = String(value ?? "").trim();

  if (!input) {
    return "";
  }

  if ([...input].some(character =>
    character === "\\" ||
    /\s/.test(character) ||
    character.charCodeAt(0) < 0x20 ||
    character.charCodeAt(0) === 0x7f
  )) {
    return null;
  }

  try {
    const url = new URL(input);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      !url.hostname ||
      url.hostname.replace(/\./g, "") === ""
    ) {
      return null;
    }

    return url.href;
  } catch {
    return null;
  }
}


function cardLanguage(card) {
  return String(card?.language || card?.lang || "en").trim() || "en";
}


/**
 * Executa uma requisição que deve retornar JSON.
 *
 * Além de converter a resposta, esta função produz mensagens consistentes
 * quando o servidor responde HTML, erro HTTP ou JSON de erro da API.
 */
async function getJson(url, options) {
  const response = await fetch(apiUrl(url), {
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


/**
 * Lê anúncios salvos pelo visitante no navegador.
 *
 * Um localStorage corrompido não deve impedir que o restante da página abra;
 * nesse caso começamos com uma lista vazia.
 */
function savedListings() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
}


/**
 * Converte centavos para o formato monetário usado pela interface.
 *
 * ``null`` representa uma oferta de troca ou uma proposta sem preço fixo.
 */
function money(cents) {
  if (cents == null) {
    return "Proposta / troca";
  }

  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(cents / 100);
}


/**
 * Desenha a lista de ofertas depois que os filtros terminam de carregar.
 */
function renderListings(listings, pagination = {}) {
  const entries = Array.isArray(listings) ? listings : [];
  const rawTotal = Number(pagination.total);
  const total = Number.isFinite(rawTotal) && rawTotal >= 0
    ? rawTotal
    : entries.length;
  const rawPage = Number(pagination.page);
  const page = Number.isFinite(rawPage) && rawPage > 0
    ? Math.floor(rawPage)
    : 1;
  const rawLimit = Number(pagination.limit);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0
    ? Math.floor(rawLimit)
    : Math.max(entries.length, LISTINGS_PAGE_SIZE);

  listingsPage = page;
  listingsTotal = total;
  listingsLimit = limit;

  const countLabel = total === 1
    ? "oferta encontrada"
    : "ofertas encontradas";

  $("#status").textContent = `${total} ${countLabel}`;

  const paginationView = $("#listingPagination");
  if (paginationView) {
    const pageCount = total ? Math.ceil(total / limit) : 1;
    paginationView.hidden = pageCount <= 1;
    $("#previousListings").disabled = page <= 1;
    $("#nextListings").disabled = page >= pageCount;
    $("#listingPage").textContent = `Página ${page} de ${pageCount}`;
  }

  if (!entries.length) {
    $("#listings").innerHTML =
      "<p>Nenhuma oferta com esses filtros. Tente ampliar a região.</p>";
    return;
  }

  $("#listings").innerHTML = entries.map(item => {
    const name = String(item.name ?? "").trim();
    const title = String(item.title ?? "").trim();
    const description = String(item.description ?? "").trim();
    const contact = safeContactUrl(item.contact_url);
    const heading = title || name || "Oferta";
    const cardName = title && name && title !== name
      ? `<p class="card-name">${esc(name)}</p>`
      : "";
    const descriptionMarkup = description
      ? `<p class="description">${esc(description)}</p>`
      : "";
    const contactMarkup = contact
      ? `<a
          class="contact"
          href="${esc(contact)}"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Abrir contato"
        >${esc(contact)}</a>`
      : "";
    const setCode = String(item.set_code ?? "").toUpperCase();
    const language = String(item.language || "en").toUpperCase();

    return `
      <article class="listing">
        <img loading="lazy" src="${esc(item.image_url)}" alt="${esc(name)}">
        <div>
          <span class="badge">${esc(item.mode)}</span>
          <h3>${esc(heading)}</h3>
          ${cardName}
          <div class="meta">
            ${esc(setCode)} ·
            ${esc(item.condition)} ·
            ${esc(language)}
          </div>
          <div class="price">${money(item.price_cents)}</div>
          ${descriptionMarkup}
          <div class="meta">
            ${esc(item.city)} · ${esc(item.state)}<br>
            por ${esc(item.display_name)}
          </div>
          ${contactMarkup}
        </div>
      </article>
    `;
  }).join("");
}


/**
 * Lê os filtros que o visitante escolheu na busca da vitrine.
 */
function filters() {
  return {
    card: $("#search").value.trim(),
    set: $("#set").value,
    city: $("#city").value.trim(),
    state: $("#state").value,
    mode,
  };
}


/**
 * "Ambos" representa uma oferta compatível com venda e com troca.
 */
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


/**
 * Busca e renderiza as ofertas da comunidade.
 *
 * No modo estático filtramos os JSONs diretamente no navegador. No modo
 * completo enviamos os mesmos filtros para a API do servidor.
 */
async function loadListings({ page = 1 } = {}) {
  $("#status").textContent = "Buscando na comunidade…";

  const selected = filters();
  const requestedPage = Math.max(1, Math.floor(Number(page) || 1));
  const currentRequest = ++listingsRequestId;

  if (listingsController) {
    listingsController.abort();
    listingsController = null;
  }

  try {
    if (STATIC_MODE) {
      // Os anúncios locais aparecem antes dos anúncios de exemplo.
      const all = [...savedListings(), ...staticListings];
      const normalizedCard = selected.card.toLocaleLowerCase();
      const filtered = all.filter(item =>
        (!selected.card ||
          String(item.name || "").toLocaleLowerCase().includes(normalizedCard)) &&
        (!selected.set || item.set_code === selected.set) &&
        (!selected.city ||
          String(item.city || "").toLocaleLowerCase() ===
            selected.city.toLocaleLowerCase()) &&
        (!selected.state || item.state === selected.state) &&
        listingModeMatches(item.mode, selected.mode)
      );

      listingsPage = 1;
      renderListings(filtered, {
        page: 1,
        limit: Math.max(filtered.length, LISTINGS_PAGE_SIZE),
        total: filtered.length,
      });
      return;
    }

    // URLSearchParams cuida da codificação de espaços e caracteres especiais.
    const query = new URLSearchParams();
    Object.entries(selected).forEach(([key, value]) => {
      if (value) {
        query.set(key, value);
      }
    });
    query.set("page", String(requestedPage));
    query.set("limit", String(LISTINGS_PAGE_SIZE));

    const controller = new AbortController();
    listingsController = controller;
    const data = await getJson(`/api/listings?${query}`, {
      signal: controller.signal,
    });

    // Uma busca nova pode ter terminado enquanto esta resposta chegava.
    if (currentRequest !== listingsRequestId) {
      return;
    }

    if (listingsController === controller) {
      listingsController = null;
    }
    renderListings(data.listings, data);
  } catch (error) {
    if (error.name === "AbortError" || currentRequest !== listingsRequestId) {
      return;
    }

    listingsController = null;
    // O texto do erro é mostrado no mesmo lugar onde ficaria o resultado.
    $("#status").textContent = error.message;
  }
}


function populateBrazilStates() {
  document.querySelectorAll("[data-brazil-states]").forEach(select => {
    const selected = select.value;
    select.querySelectorAll("option:not([value=''])").forEach(option => {
      option.remove();
    });

    for (const state of BRAZIL_STATES) {
      const option = document.createElement("option");
      option.value = state;
      option.textContent = state;
      select.append(option);
    }
    select.value = selected;
  });
}


/**
 * Preenche o filtro de coleções e inicializa os seletores de cartas.
 */
function populateCatalog() {
  // A API fornece uma lista completa de sets. O fallback usa os cards já
  // carregados para manter a demonstração funcionando com arquivos estáticos.
  const sourceSets = catalogSets.length ? catalogSets : cards;

  // Map elimina coleções repetidas mantendo ``código -> nome``.
  const sets = [
    ...new Map(
      sourceSets.map(item => [item.set_code, item.set_name])
    ).entries(),
  ].sort((a, b) => a[1].localeCompare(b[1]));

  for (const [code, name] of sets) {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = `${name} (${code.toUpperCase()})`;
    $("#set").append(option);
  }

  // O seletor é um componente separado porque também é usado pelo formulário.
  if (window.ManaBridgeCardPicker) {
    cardPicker = window.ManaBridgeCardPicker.create({
      root: $("#cardPicker"),
      source: apiUrl($("#cardPicker").dataset.source || "/api/cards"),
      staticCards: STATIC_MODE ? cards : null,
    });

    wantCardPicker = window.ManaBridgeCardPicker.create({
      root: $("#wantCardPicker"),
      source: apiUrl("/api/cards"),
      staticCards: STATIC_MODE ? cards : null,
    });
  }
}


/**
 * Atualiza a parte visual da página que depende da sessão autenticada.
 */
function setAuth(data) {
  currentUser = data?.user || null;
  csrfToken = data?.csrf_token || null;

  // Os três controles abaixo representam estados mutuamente exclusivos.
  $("#userBadge").hidden = !currentUser;
  $("#logoutButton").hidden = !currentUser;
  $("#accountButton").hidden = !currentUser;
  $("#authButton").hidden = !!currentUser;
  $("#userBadge").textContent = currentUser
    ? `Olá, ${currentUser.display_name}`
    : "";
}


/**
 * Descobre se já existe uma sessão no backend.
 */
async function loadSession() {
  if (STATIC_MODE) {
    setAuth(null);
    return;
  }

  try {
    setAuth(await getJson("/api/auth/me"));
  } catch (error) {
    // 401 significa apenas que o visitante ainda não entrou.
    if (error.status === 401) {
      setAuth(null);
      return;
    }

    throw error;
  }
}


/**
 * Carrega os dados iniciais adequados ao ambiente atual.
 */
async function loadData() {
  populateBrazilStates();

  if (STATIC_MODE) {
    // O visitante do Pages recebe uma indicação explícita sobre as limitações.
    $("#staticNotice").hidden = false;

    const [catalog, offers] = await Promise.all([
      getJson("data/cards.json"),
      getJson("data/listings.json"),
    ]);

    cards = catalog.cards;
    catalogSets = [];
    staticListings = offers.listings;
  } else {
    // A lista de sets vem de uma rota própria para não depender dos primeiros
    // 100 cards retornados pela paginação inicial.
    const [catalog, sets] = await Promise.all([
      getJson("/api/cards?limit=100"),
      getJson("/api/sets"),
    ]);

    cards = catalog.cards;
    catalogSets = sets.sets || [];
  }

  populateCatalog();
  await loadSession();
  await loadListings();
}


// Submeter a busca não recarrega a página; apenas atualiza a vitrine.
$("#searchForm").addEventListener("submit", event => {
  event.preventDefault();
  loadListings();
});

$("#previousListings")?.addEventListener("click", () => {
  if (listingsPage > 1) {
    loadListings({ page: listingsPage - 1 });
  }
});

$("#nextListings")?.addEventListener("click", () => {
  const pageCount = listingsTotal
    ? Math.ceil(listingsTotal / listingsLimit)
    : 1;
  if (listingsPage < pageCount) {
    loadListings({ page: listingsPage + 1 });
  }
});

// Somente os chips da vitrine alteram o filtro de modalidade.
document.querySelectorAll(".chips .chip[data-mode]").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".chips .chip[data-mode]").forEach(item => {
      item.classList.remove("active");
    });

    button.classList.add("active");
    mode = button.dataset.mode || "";
    loadListings();
  });
});


// Referências aos diálogos da página.
const modal = $("#modal");
const authModal = $("#authModal");
const accountModal = $("#accountModal");
const wantModal = $("#wantModal");


/**
 * Abre um anúncio novo ou reutiliza o mesmo formulário para edição.
 */
function openNewListing() {
  if (!STATIC_MODE && !currentUser) {
    $("#authStatus").textContent =
      "Entre ou crie uma conta para anunciar.";
    authModal.showModal();
    return;
  }

  editingListingId = null;
  $("#listingForm").reset();
  $("#listingModalTitle").textContent = "Anunciar carta";
  $("#listingSubmitButton").textContent = "Publicar oferta";
  $("#formStatus").textContent = "";
  cardPicker?.clear();
  modal.showModal();
  cardPicker?.focus();
}

function openListingForEdit(item) {
  editingListingId = item.id;
  const form = $("#listingForm");
  form.reset();
  $("#listingModalTitle").textContent = "Editar anúncio";
  $("#listingSubmitButton").textContent = "Salvar alterações";
  $("#formStatus").textContent = "";

  cardPicker?.select({
    id: item.card_id,
    name: item.name,
    set_code: item.set_code,
    set_name: item.set_name,
    image_url: item.image_url,
    language: item.language,
  });
  form.elements.title.value = item.title || "";
  form.elements.description.value = item.description || "";
  form.elements.price.value = item.price_cents == null
    ? ""
    : (item.price_cents / 100).toFixed(2);
  form.elements.condition.value = item.condition;
  form.elements.mode.value = item.mode;
  form.elements.contact_url.value = item.contact_url || "";

  accountModal.close();
  modal.showModal();
}

$("#openModal").onclick = openNewListing;


// O botão de fechar usa o comportamento nativo do elemento <dialog>.
$("#closeModal").onclick = () => modal.close();


/**
 * Publica uma oferta no backend ou a salva no navegador em modo estático.
 */
$("#listingForm").addEventListener("submit", async event => {
  event.preventDefault();

  // FormData transforma os campos do formulário em um objeto simples.
  const form = Object.fromEntries(new FormData(event.target));
  const card = cardPicker?.getSelectedCard() ||
    cards.find(item => item.id === Number(form.card_id));

  if (!card) {
    $("#formStatus").textContent =
      "Busque e selecione uma carta antes de publicar.";
    cardPicker?.focus();
    return;
  }

  const contactUrl = safeContactUrl(form.contact_url);
  if (contactUrl === null) {
    $("#formStatus").textContent =
      "Informe um contato HTTP(S) válido com endereço de host, " +
      "ou deixe o campo vazio.";
    $("[name='contact_url']")?.focus();
    return;
  }

  // A API armazena preço como inteiro em centavos para evitar arredondamento
  // inesperado de números decimais no banco.
  const payload = {
    card_id: Number(form.card_id),
    title: form.title,
    description: form.description,
    price_cents: form.price
      ? Math.round(Number(form.price) * 100)
      : null,
    condition: form.condition,
    language: cardLanguage(card),
    mode: form.mode,
    contact_url: contactUrl,
  };

  try {
    if (STATIC_MODE) {
      // No GitHub Pages não existe banco compartilhado; o anúncio é pessoal
      // ao navegador e aparece junto dos dados de demonstração.
      const entry = {
        ...payload,
        id: Date.now(),
        name: card.name,
        set_code: card.set_code,
        set_name: card.set_name,
        image_url: card.image_url,
        display_name: "Você (demonstração)",
        city: "Natal",
        state: "RN",
      };

      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify([entry, ...savedListings()])
      );
    } else {
      // O token CSRF acompanha operações que alteram dados no backend.
      const endpoint = editingListingId
        ? `/api/listings/${editingListingId}`
        : "/api/listings";
      await getJson(endpoint, {
        method: editingListingId ? "PATCH" : "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(payload),
      });
    }

    $("#formStatus").textContent = STATIC_MODE
      ? "Oferta salva neste navegador."
      : editingListingId
        ? "Anúncio atualizado."
        : "Oferta publicada.";
    editingListingId = null;
    await loadListings();
    if (accountModal.open) {
      await loadAccountData();
    }

    // Um pequeno atraso permite que o visitante leia a confirmação.
    setTimeout(() => modal.close(), 700);
  } catch (error) {
    $("#formStatus").textContent = error.message;
  }
});



// ---------- Área autenticada ----------

function renderAccountListings(listings) {
  const entries = Array.isArray(listings) ? listings : [];
  myListingsById = new Map(entries.map(item => [Number(item.id), item]));

  if (!entries.length) {
    $("#myListings").innerHTML =
      '<p class="empty-state">Você ainda não publicou anúncios.</p>';
    return;
  }

  $("#myListings").innerHTML = entries.map(item => `
    <article class="account-item">
      <img src="${esc(item.image_url)}" alt="">
      <div>
        <h4>${esc(item.title || item.name)}</h4>
        <p class="meta">
          ${esc(item.name)} · ${esc(String(item.set_code || "").toUpperCase())}
          · ${esc(item.condition)} · ${money(item.price_cents)}
        </p>
      </div>
      <div class="inline-actions">
        <button class="secondary compact" type="button" data-edit-listing="${item.id}">
          Editar
        </button>
        <button class="secondary compact danger" type="button" data-delete-listing="${item.id}">
          Excluir
        </button>
      </div>
    </article>
  `).join("");

  $("#myListings").querySelectorAll("[data-edit-listing]").forEach(button => {
    button.onclick = () => {
      const item = myListingsById.get(Number(button.dataset.editListing));
      if (item) {
        openListingForEdit(item);
      }
    };
  });

  $("#myListings").querySelectorAll("[data-delete-listing]").forEach(button => {
    button.onclick = async () => {
      const id = Number(button.dataset.deleteListing);
      if (!confirm("Excluir este anúncio?")) {
        return;
      }
      try {
        await getJson(`/api/listings/${id}`, {
          method: "DELETE",
          headers: { "X-CSRF-Token": csrfToken },
        });
        await Promise.all([loadListings(), loadAccountData()]);
      } catch (error) {
        $("#accountStatus").textContent = error.message;
      }
    };
  });
}

function renderWants(wants) {
  const entries = Array.isArray(wants) ? wants : [];
  if (!entries.length) {
    $("#wantsList").innerHTML =
      '<p class="empty-state">Sua lista de desejos está vazia.</p>';
    return;
  }

  $("#wantsList").innerHTML = entries.map(item => `
    <article class="account-item">
      <img src="${esc(item.image_url)}" alt="">
      <div>
        <h4>${esc(item.name)}</h4>
        <p class="meta">
          ${esc(String(item.set_code || "").toUpperCase())}
          · ${esc(item.mode)}
          · máximo: ${money(item.max_price_cents)}
        </p>
      </div>
      <div class="inline-actions">
        <button class="secondary compact danger" type="button" data-delete-want="${item.id}">
          Remover
        </button>
      </div>
    </article>
  `).join("");

  $("#wantsList").querySelectorAll("[data-delete-want]").forEach(button => {
    button.onclick = async () => {
      try {
        await getJson(`/api/wants/${button.dataset.deleteWant}`, {
          method: "DELETE",
          headers: { "X-CSRF-Token": csrfToken },
        });
        await loadAccountData();
      } catch (error) {
        $("#accountStatus").textContent = error.message;
      }
    };
  });
}

function renderMatches(matches) {
  const entries = Array.isArray(matches) ? matches : [];
  if (!entries.length) {
    $("#matchesList").innerHTML =
      '<p class="empty-state">Nenhuma oferta compatível por enquanto.</p>';
    return;
  }

  $("#matchesList").innerHTML = entries.map(item => {
    const contact = safeContactUrl(item.contact_url);
    const contactMarkup = contact
      ? `<a class="contact" href="${esc(contact)}" target="_blank" rel="noopener noreferrer">Contato</a>`
      : "";
    return `
      <article class="account-item">
        <img src="${esc(item.image_url)}" alt="">
        <div>
          <h4>${esc(item.wanted_name || item.name)}</h4>
          <p class="meta">
            ${esc(item.title || "Oferta compatível")}
            · ${esc(item.city)} / ${esc(item.state)}
            · ${money(item.price_cents)}
          </p>
        </div>
        <div class="inline-actions">${contactMarkup}</div>
      </article>
    `;
  }).join("");
}

async function loadAccountData() {
  if (!currentUser || STATIC_MODE) {
    return;
  }

  $("#accountStatus").textContent = "Atualizando…";
  try {
    const [listings, wants, matches] = await Promise.all([
      getJson("/api/listings?mine=1&limit=100"),
      getJson("/api/wants?limit=100"),
      getJson("/api/matches"),
    ]);

    renderAccountListings(listings.listings);
    renderWants(wants.wants);
    renderMatches(matches.matches);
    $("#accountStatus").textContent = "";
  } catch (error) {
    $("#accountStatus").textContent = error.message;
  }
}

$("#accountButton").onclick = async () => {
  if (!currentUser) {
    return;
  }

  const form = $("#profileForm");
  form.elements.display_name.value = currentUser.display_name || "";
  form.elements.city.value = currentUser.city || "";
  form.elements.state.value = currentUser.state || "";
  $("#profileStatus").textContent = "";
  accountModal.showModal();
  await loadAccountData();
};

$("#closeAccount").onclick = () => accountModal.close();

$("#accountNewListing").onclick = () => {
  accountModal.close();
  openNewListing();
};

$("#profileForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("#profileStatus").textContent = "Salvando…";
  try {
    const data = await getJson("/api/profile", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(Object.fromEntries(new FormData(event.target))),
    });
    setAuth(data);
    $("#profileStatus").textContent = "Perfil atualizado.";
    await loadListings();
  } catch (error) {
    $("#profileStatus").textContent = error.message;
  }
});

$("#openWantModal").onclick = () => {
  $("#wantForm").reset();
  $("#wantStatus").textContent = "";
  wantCardPicker?.clear();
  wantModal.showModal();
  wantCardPicker?.focus();
};

$("#closeWantModal").onclick = () => wantModal.close();

$("#wantForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = Object.fromEntries(new FormData(event.target));
  const card = wantCardPicker?.getSelectedCard();

  if (!card) {
    $("#wantStatus").textContent = "Selecione uma carta.";
    wantCardPicker?.focus();
    return;
  }

  $("#wantStatus").textContent = "Salvando…";
  try {
    await getJson("/api/wants", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({
        card_id: Number(form.card_id),
        max_price_cents: form.max_price
          ? Math.round(Number(form.max_price) * 100)
          : null,
        desired_condition: form.desired_condition || null,
        mode: form.mode,
      }),
    });
    $("#wantStatus").textContent = "Desejo salvo.";
    await loadAccountData();
    setTimeout(() => wantModal.close(), 500);
  } catch (error) {
    $("#wantStatus").textContent = error.message;
  }
});

// Abre a tela de autenticação com o painel correto para o ambiente.
$("#authButton").onclick = () => {
  $("#authStaticWarning").hidden = !STATIC_MODE;
  $("#authInteractive").hidden = STATIC_MODE;
  authModal.showModal();
};

// Fecha o diálogo de autenticação.
$("#closeAuth").onclick = () => authModal.close();


// Alterna entre os formulários de login e criação de conta.
document.querySelectorAll("[data-auth-tab]").forEach(button => {
  button.addEventListener("click", () => {
    const login = button.dataset.authTab === "login";

    document.querySelectorAll("[data-auth-tab]").forEach(item => {
      item.classList.toggle("active", item === button);
    });

    $("#loginForm").hidden = !login;
    $("#registerForm").hidden = login;
    $("#authTitle").textContent = login ? "Entrar" : "Criar conta";
    $("#authStatus").textContent = "";
  });
});


// Envia o formulário de login para o backend.
$("#loginForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("#authStatus").textContent = "Verificando…";

  try {
    const data = await getJson("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(event.target))),
    });

    setAuth(data);
    event.target.reset();
    $("#authStatus").textContent = "Login realizado.";
    setTimeout(() => authModal.close(), 500);
  } catch (error) {
    $("#authStatus").textContent = error.message;
  }
});


// Envia o formulário de cadastro para o backend.
$("#registerForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("#authStatus").textContent = "Criando conta…";

  try {
    const data = await getJson("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(event.target))),
    });

    setAuth(data);
    event.target.reset();
    $("#authStatus").textContent = "Conta criada com segurança.";
    setTimeout(() => authModal.close(), 600);
  } catch (error) {
    $("#authStatus").textContent = error.message;
  }
});


// Logout também altera estado no backend e, portanto, envia o token CSRF.
$("#logoutButton").onclick = async () => {
  try {
    await getJson("/api/auth/logout", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    });
    setAuth(null);
    accountModal.close();
  } catch (error) {
    alert(error.message);
  }
};


// Qualquer falha na carga inicial aparece na área de status da página.
loadData().catch(error => {
  $("#status").textContent = error.message;
});
