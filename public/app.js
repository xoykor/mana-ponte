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

// GitHub Pages e arquivos locais não conseguem executar o backend Python.
// Nesses ambientes, a página entra em modo de demonstração automaticamente.
const STATIC_MODE =
  location.hostname.endsWith("github.io") ||
  location.protocol === "file:" ||
  new URLSearchParams(location.search).has("static");

// A chave guarda os anúncios criados localmente no modo demonstração.
const STORAGE_KEY = "manaponte-demo-listings";

// Estado carregado do catálogo e da sessão atual.
let cards = [];
let catalogSets = [];
let staticListings = [];
let mode = "";
let currentUser = null;
let csrfToken = null;
let cardPicker = null;


/**
 * Escapa texto antes de inseri-lo dentro de HTML criado por template string.
 *
 * Os dados das cartas e dos usuários vêm de fontes externas ao navegador.
 * Mesmo em uma tela simples, escapar esses valores evita que um nome com
 * caracteres especiais seja interpretado como marcação HTML.
 */
const esc = value => {
  const node = document.createElement("span");
  node.textContent = value ?? "";
  return node.innerHTML;
};


/**
 * Executa uma requisição que deve retornar JSON.
 *
 * Além de converter a resposta, esta função produz mensagens consistentes
 * quando o servidor responde HTML, erro HTTP ou JSON de erro da API.
 */
async function getJson(url, options) {
  const response = await fetch(url, options);
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
function renderListings(listings) {
  const countLabel = listings.length === 1
    ? "oferta encontrada"
    : "ofertas encontradas";

  $("#status").textContent = `${listings.length} ${countLabel}`;

  if (!listings.length) {
    $("#listings").innerHTML =
      "<p>Nenhuma oferta com esses filtros. Tente ampliar a região.</p>";
    return;
  }

  $("#listings").innerHTML = listings.map(item => `
    <article class="listing">
      <img loading="lazy" src="${esc(item.image_url)}" alt="${esc(item.name)}">
      <div>
        <span class="badge">${esc(item.mode)}</span>
        <h3>${esc(item.name)}</h3>
        <div class="meta">
          ${esc(item.set_code.toUpperCase())} ·
          ${esc(item.condition)} ·
          ${esc(item.language.toUpperCase())}
        </div>
        <div class="price">${money(item.price_cents)}</div>
        <div class="meta">
          ${esc(item.city)} · ${esc(item.state)}<br>
          por ${esc(item.display_name)}
        </div>
      </div>
    </article>
  `).join("");
}


/**
 * Lê os filtros que o visitante escolheu na busca da vitrine.
 */
function filters() {
  return {
    card: $("#search").value.trim(),
    set: $("#set").value,
    state: $("#state").value,
    mode,
  };
}


/**
 * Busca e renderiza as ofertas da comunidade.
 *
 * No modo estático filtramos os JSONs diretamente no navegador. No modo
 * completo enviamos os mesmos filtros para a API do servidor.
 */
async function loadListings() {
  $("#status").textContent = "Buscando na comunidade…";

  try {
    const selected = filters();

    if (STATIC_MODE) {
      // Os anúncios locais aparecem antes dos anúncios de exemplo.
      const all = [...savedListings(), ...staticListings];
      const normalizedCard = selected.card.toLowerCase();
      const filtered = all.filter(item =>
        (!selected.card || item.name.toLowerCase().includes(normalizedCard)) &&
        (!selected.set || item.set_code === selected.set) &&
        (!selected.state || item.state === selected.state) &&
        (!selected.mode || item.mode === selected.mode)
      );

      renderListings(filtered);
      return;
    }

    // URLSearchParams cuida da codificação de espaços e caracteres especiais.
    const query = new URLSearchParams();
    Object.entries(selected).forEach(([key, value]) => {
      if (value) {
        query.set(key, value);
      }
    });

    const data = await getJson(`/api/listings?${query}`);
    renderListings(data.listings);
  } catch (error) {
    // O texto do erro é mostrado no mesmo lugar onde ficaria o resultado.
    $("#status").textContent = error.message;
  }
}


/**
 * Preenche o filtro de coleções e inicializa o seletor de cartas do modal.
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
      source: $("#cardPicker").dataset.source || "/api/cards",
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

// Os chips alteram o filtro de modalidade e destacam o botão ativo.
document.querySelectorAll(".chip").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".chip").forEach(item => {
      item.classList.remove("active");
    });

    button.classList.add("active");
    mode = button.dataset.mode;
    loadListings();
  });
});


// Referências aos dois diálogos modais da página.
const modal = $("#modal");
const authModal = $("#authModal");


/**
 * Abre o formulário de anúncio ou, se necessário, pede autenticação primeiro.
 */
$("#openModal").onclick = () => {
  if (!STATIC_MODE && !currentUser) {
    $("#authStatus").textContent =
      "Entre ou crie uma conta para anunciar.";
    authModal.showModal();
    return;
  }

  // Cada abertura começa com um formulário limpo e sem carta selecionada.
  $("#listingForm").reset();
  $("#formStatus").textContent = "";
  cardPicker?.clear();
  modal.showModal();
  cardPicker?.focus();
};


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
    language: "en",
    mode: form.mode,
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
      await getJson("/api/listings", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(payload),
      });
    }

    $("#formStatus").textContent = STATIC_MODE
      ? "Oferta salva neste navegador."
      : "Oferta publicada no protótipo.";
    await loadListings();

    // Um pequeno atraso permite que o visitante leia a confirmação.
    setTimeout(() => modal.close(), 700);
  } catch (error) {
    $("#formStatus").textContent = error.message;
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
  } catch (error) {
    alert(error.message);
  }
};


// Qualquer falha na carga inicial aparece na área de status da página.
loadData().catch(error => {
  $("#status").textContent = error.message;
});
