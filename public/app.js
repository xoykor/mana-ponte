const $ = selector => document.querySelector(selector);
const STATIC_MODE = location.hostname.endsWith("github.io") || location.protocol === "file:" || new URLSearchParams(location.search).has("static");
const STORAGE_KEY = "manaponte-demo-listings";
let cards = [];
let staticListings = [];
let mode = "";
let currentUser = null;
let csrfToken = null;
let cardPicker = null;

const esc = value => {
  const node = document.createElement("span");
  node.textContent = value ?? "";
  return node.innerHTML;
};

async function getJson(url, options) {
  const response = await fetch(url, options);
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) throw Object.assign(new Error("Resposta inesperada do servidor"), {status: response.status});
  const data = await response.json();
  if (!response.ok) throw Object.assign(new Error(data.error || "Falha na requisição"), {status: response.status});
  return data;
}

function savedListings() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"); }
  catch { return []; }
}

function money(cents) {
  return cents == null ? "Proposta / troca" : new Intl.NumberFormat("pt-BR", {
    style: "currency", currency: "BRL"
  }).format(cents / 100);
}

function renderListings(listings) {
  $("#status").textContent = `${listings.length} ${listings.length === 1 ? "oferta encontrada" : "ofertas encontradas"}`;
  $("#listings").innerHTML = listings.length ? listings.map(item => `
    <article class="listing">
      <img loading="lazy" src="${esc(item.image_url)}" alt="${esc(item.name)}">
      <div><span class="badge">${esc(item.mode)}</span><h3>${esc(item.name)}</h3>
      <div class="meta">${esc(item.set_code.toUpperCase())} · ${esc(item.condition)} · ${esc(item.language.toUpperCase())}</div>
      <div class="price">${money(item.price_cents)}</div>
      <div class="meta">${esc(item.city)} · ${esc(item.state)}<br>por ${esc(item.display_name)}</div></div>
    </article>`).join("") : "<p>Nenhuma oferta com esses filtros. Tente ampliar a região.</p>";
}

function filters() {
  return { card: $("#search").value.trim(), set: $("#set").value, state: $("#state").value, mode };
}

async function loadListings() {
  $("#status").textContent = "Buscando na comunidade…";
  try {
    const selected = filters();
    if (STATIC_MODE) {
      const all = [...savedListings(), ...staticListings];
      const filtered = all.filter(item =>
        (!selected.card || item.name.toLowerCase().includes(selected.card.toLowerCase())) &&
        (!selected.set || item.set_code === selected.set) &&
        (!selected.state || item.state === selected.state) &&
        (!selected.mode || item.mode === selected.mode)
      );
      return renderListings(filtered);
    }
    const query = new URLSearchParams();
    Object.entries(selected).forEach(([key, value]) => value && query.set(key, value));
    const data = await getJson(`/api/listings?${query}`);
    renderListings(data.listings);
  } catch (error) { $("#status").textContent = error.message; }
}

function populateCatalog() {
  const sets = [...new Map(cards.map(card => [card.set_code, card.set_name])).entries()]
    .sort((a, b) => a[1].localeCompare(b[1]));
  for (const [code, name] of sets) {
    const option = document.createElement("option");
    option.value = code; option.textContent = `${name} (${code.toUpperCase()})`; $("#set").append(option);
  }
  if (window.ManaBridgeCardPicker) {
    cardPicker = window.ManaBridgeCardPicker.create({
      root: $("#cardPicker"),
      source: $("#cardPicker").dataset.source || "/api/cards",
      staticCards: STATIC_MODE ? cards : null
    });
  }
}

function setAuth(data) {
  currentUser = data?.user || null;
  csrfToken = data?.csrf_token || null;
  $("#userBadge").hidden = !currentUser;
  $("#logoutButton").hidden = !currentUser;
  $("#authButton").hidden = !!currentUser;
  $("#userBadge").textContent = currentUser ? `Olá, ${currentUser.display_name}` : "";
}

async function loadSession() {
  if (STATIC_MODE) return setAuth(null);
  try { setAuth(await getJson("/api/auth/me")); }
  catch (error) { if (error.status === 401) setAuth(null); else throw error; }
}

async function loadData() {
  if (STATIC_MODE) {
    $("#staticNotice").hidden = false;
    const [catalog, offers] = await Promise.all([getJson("data/cards.json"), getJson("data/listings.json")]);
    cards = catalog.cards; staticListings = offers.listings;
  } else {
    const catalog = await getJson("/api/cards?limit=100");
    cards = catalog.cards;
  }
  populateCatalog();
  await loadSession();
  await loadListings();
}

$("#searchForm").addEventListener("submit", event => { event.preventDefault(); loadListings(); });
document.querySelectorAll(".chip").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".chip").forEach(item => item.classList.remove("active"));
  button.classList.add("active"); mode = button.dataset.mode; loadListings();
}));

const modal = $("#modal");
const authModal = $("#authModal");
$("#openModal").onclick = () => {
  if (!STATIC_MODE && !currentUser) {
    $("#authStatus").textContent = "Entre ou crie uma conta para anunciar.";
    return authModal.showModal();
  }
  $("#listingForm").reset();
  $("#formStatus").textContent = "";
  cardPicker?.clear();
  modal.showModal();
  cardPicker?.focus();
};
$("#closeModal").onclick = () => modal.close();
$("#listingForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = Object.fromEntries(new FormData(event.target));
  const card = cardPicker?.getSelectedCard() || cards.find(item => item.id === Number(form.card_id));
  if (!card) {
    $("#formStatus").textContent = "Busque e selecione uma carta antes de publicar.";
    cardPicker?.focus();
    return;
  }
  const payload = {
    card_id: Number(form.card_id), title: form.title, description: form.description,
    price_cents: form.price ? Math.round(Number(form.price) * 100) : null,
    condition: form.condition, language: "en", mode: form.mode
  };
  try {
    if (STATIC_MODE) {
      const entry = {...payload, id: Date.now(), name: card.name, set_code: card.set_code,
        set_name: card.set_name, image_url: card.image_url, display_name: "Você (demonstração)", city: "Natal", state: "RN"};
      localStorage.setItem(STORAGE_KEY, JSON.stringify([entry, ...savedListings()]));
    } else {
      await getJson("/api/listings", {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken}, body: JSON.stringify(payload)});
    }
    $("#formStatus").textContent = STATIC_MODE ? "Oferta salva neste navegador." : "Oferta publicada no protótipo.";
    await loadListings(); setTimeout(() => modal.close(), 700);
  } catch (error) { $("#formStatus").textContent = error.message; }
});

$("#authButton").onclick = () => {
  $("#authStaticWarning").hidden = !STATIC_MODE;
  $("#authInteractive").hidden = STATIC_MODE;
  authModal.showModal();
};
$("#closeAuth").onclick = () => authModal.close();
document.querySelectorAll("[data-auth-tab]").forEach(button => button.addEventListener("click", () => {
  const login = button.dataset.authTab === "login";
  document.querySelectorAll("[data-auth-tab]").forEach(item => item.classList.toggle("active", item === button));
  $("#loginForm").hidden = !login; $("#registerForm").hidden = login;
  $("#authTitle").textContent = login ? "Entrar" : "Criar conta"; $("#authStatus").textContent = "";
}));

$("#loginForm").addEventListener("submit", async event => {
  event.preventDefault(); $("#authStatus").textContent = "Verificando…";
  try {
    const data = await getJson("/api/auth/login", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});
    setAuth(data); event.target.reset(); $("#authStatus").textContent = "Login realizado."; setTimeout(() => authModal.close(), 500);
  } catch (error) { $("#authStatus").textContent = error.message; }
});

$("#registerForm").addEventListener("submit", async event => {
  event.preventDefault(); $("#authStatus").textContent = "Criando conta…";
  try {
    const data = await getJson("/api/auth/register", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});
    setAuth(data); event.target.reset(); $("#authStatus").textContent = "Conta criada com segurança."; setTimeout(() => authModal.close(), 600);
  } catch (error) { $("#authStatus").textContent = error.message; }
});

$("#logoutButton").onclick = async () => {
  try { await getJson("/api/auth/logout", {method:"POST", headers:{"X-CSRF-Token":csrfToken}}); setAuth(null); }
  catch (error) { alert(error.message); }
};

loadData().catch(error => { $("#status").textContent = error.message; });
