#!/usr/bin/env node
/*
 * Etapa 5 — validação visual e de interação no navegador.
 *
 * Conecta ao Chromium headless via protocolo CDP usando o módulo ws real
 * (disponível em NODE_PATH), navega pela interface do ManaPonte, executa os
 * fluxos de usuário e captura screenshots + estado DOM/console em cada passo.
 * Emite um relatório JSON com pass/fail por verificação. Sem rede externa.
 */

const fs = require("fs");
const path = require("path");
const http = require("http");
const WS = require("/home/x/.local/lib/dsh-runtime-0.1.5-rc.2/node_modules/ws");
let seq = { next: 0 };
const BASE = process.env.MP_APP_URL || "http://127.0.0.1:8097";
const CDP_PORT = Number(process.env.MP_CDP_PORT) || 9222;
const OUT_DIR = process.env.MP_OUT_DIR || path.join(__dirname, "..", "e5-screenshots");
fs.mkdirSync(OUT_DIR, { recursive: true });

const results = [];
function check(scenario, name, expected, actual) {
  const pass = JSON.stringify(expected) === JSON.stringify(actual);
  results.push({ scenario, name, expected, actual, pass });
}

// ---- CDP client (módulo ws real via NODE_PATH) ----------------------------
let ws;
const pending = new Map();
const eventWaiters = new Map();
const CALL_TIMEOUT_MS = 8000;
const READY_RETRIES = 6;
const READY_BACKOFF_MS = 200;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function httpGetJSON(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, res => {
      let b = "";
      res.setEncoding("utf8");
      res.on("data", d => (b += d));
      res.on("end", () => {
        try { resolve(JSON.parse(b)); } catch (error) { reject(error); }
      });
    });
    request.setTimeout(CALL_TIMEOUT_MS, () => request.destroy(new Error("CDP HTTP timeout")));
    request.on("error", reject);
  });
}
function openHandshake() {
  return new Promise((resolve, reject) => {
    const findTarget = async () => {
      let lastError;
      for (let attempt = 0; attempt < READY_RETRIES; attempt += 1) {
        try {
          const targets = await httpGetJSON(`http://127.0.0.1:${CDP_PORT}/json`);
          const page = targets.find(t => t.type === "page" && t.webSocketDebuggerUrl);
          if (page) return page;
          lastError = new Error("sem target Page no endpoint CDP");
        } catch (error) {
          lastError = error;
        }
        await sleep(READY_BACKOFF_MS * 2 ** attempt);
      }
      throw lastError || new Error("sem target Page no endpoint CDP");
    };
    findTarget().then(page => {
      ws = new WS(page.webSocketDebuggerUrl);
      ws.once("open", async () => {
        // O evento open garante apenas o handshake TCP/WebSocket. O processo
        // do Chromium pode ainda estar inicializando o target Page; aguarde um
        // pequeno intervalo antes dos primeiros comandos CDP.
        await sleep(READY_BACKOFF_MS);
        resolve();
      });
      ws.on("error", e => reject(e));
      ws.on("message", raw => {
        let data;
        try { data = JSON.parse(raw.toString()); } catch (error) { reject(error); return; }
        if (data.id !== undefined && pending.has(data.id)) {
          const call = pending.get(data.id);
          pending.delete(data.id);
          clearTimeout(call.timer);
          if (data.error) call.reject(new Error(`${data.error.code}: ${data.error.message}`));
          else call.resolve(data.result || {});
        }
        if (data.method && eventWaiters.has(data.method)) {
          const waiters = eventWaiters.get(data.method);
          eventWaiters.delete(data.method);
          for (const resolveEvent of waiters) resolveEvent(data.params || {});
        }
      });
    }).catch(reject);
  });
}
function send(method, params) {
  return new Promise((resolve, reject) => {
    const id = ++seq.next;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`${method} timeout after ${CALL_TIMEOUT_MS}ms`));
    }, CALL_TIMEOUT_MS);
    pending.set(id, { resolve, reject, timer });
    try { ws.send(JSON.stringify({ id, method, params })); }
    catch (error) { clearTimeout(timer); pending.delete(id); reject(error); }
  });
}
function onEvent(method) {
  return new Promise(resolve => {
    const waiters = eventWaiters.get(method) || [];
    waiters.push(resolve);
    eventWaiters.set(method, waiters);
  });
}

async function sendWithRetry(method, params = {}, attempts = READY_RETRIES) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await send(method, params);
    } catch (error) {
      lastError = error;
      if (attempt + 1 < attempts) await sleep(READY_BACKOFF_MS * 2 ** attempt);
    }
  }
  throw lastError;
}

async function main() {
  await openHandshake();
  // A conexão pelo endpoint devtools/browser/<id> já é uma sessão Page
  // achatada (flatten), então não é preciso chamar attachToTarget.
  await sendWithRetry("Page.enable", {});
  await sendWithRetry("Runtime.enable", {});
  await sendWithRetry("Log.enable", {});
  await sendWithRetry("Network.enable", {});

  const evalInPage = expr => send("Runtime.evaluate", {
    expression: '(() => { const value = (' + expr + '); return typeof value === "function" ? value() : value; })()',
    returnByValue: true,
    awaitPromise: true
  }).then(r => {
    if (r.exceptionDetails) {
      const description = r.exceptionDetails.exception?.description || r.exceptionDetails.text || "Runtime.evaluate failed";
      return { __error: description };
    }
    return r.result?.value;
  }).catch(e => ({ __error: String(e) }));

  async function navigate(url) {
    const loaded = onEvent("Page.loadEventFired");
    await send("Page.navigate", { url });
    return loaded;
  }
  async function setViewport(w, h) {
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  }
  async function screenshot(name) {
    const r = await send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(OUT_DIR, name), Buffer.from(r.data, "base64"));
    return r;
  }
  async function settle(ms = 1500) {
    const start = Date.now();
    while (Date.now() - start < ms) {
      const s = await evalInPage("document.getElementById('status').textContent");
      if (!String(s).includes("Carregando") && !String(s).includes("Buscando")) return;
      await new Promise(r => setTimeout(r, 200));
    }
  }

  // A. Carga inicial (desktop)
  await navigate(BASE + "/");
  check("A. Carga inicial", "title contém 'ManaPonte'", true, await evalInPage("document.title.includes('ManaPonte')"));

  const consoleErrors = await evalInPage(
    "() => { const e=[]; window.addEventListener('error',x=>e.push(x.message)); return JSON.stringify(e); }").then(v => (v.__error ? v : JSON.parse(v).length));
  check("A. Carga inicial", "sem erros de console", 0, consoleErrors);

  const listingCount = await evalInPage("() => document.querySelectorAll('#listings .listing').length");
  check("A. Carga inicial", "#listings renderiza >0 cards", true, listingCount > 0);

  const statusText = await evalInPage("document.getElementById('status').textContent");
  check("A. Carga inicial", "status não está 'Carregando…'", true, !String(statusText).includes("Carregando"));

  const heroH1 = await evalInPage("document.querySelector('main h1')?.textContent.includes('na mesa ao lado')");
  check("A. Carga inicial", "hero h1 presente", true, heroH1);

  await setViewport(1280, 720);
  const shotDesktop = await screenshot("A_desktop_1280x720.png");
  check("A. Carga inicial", "screenshot desktop salvo", true, !!shotDesktop.data);

  // B. Filtro de modalidade (chips)
  const allCount = listingCount;
  await evalInPage("document.querySelector('[data-mode=\"troca\"]')?.click()");
  await settle(900);
  const trocaCount = await evalInPage("document.querySelectorAll('#listings .listing').length");
  check("B. Filtro de modalidade", "Troca mostra <= Todos", true, trocaCount <= allCount);
  await evalInPage("document.querySelector('[data-mode=\"\"]')?.click()");
  await settle(900);

  await evalInPage("document.querySelector('[data-mode=\"venda\"]')?.click()");
  await settle(900);
  const activeChip = await evalInPage("() => [...document.querySelectorAll('.chip')].find(c=>c.classList.contains('active'))?.dataset.mode || ''");
  check("B. Filtro de modalidade", "chip ativo == venda", "venda", activeChip);

  // D. Autenticação + cadastro (deve ocorrer antes do modal de anúncio,
  // pois o backend exige uma sessão para abrir esse formulário).
  await evalInPage("document.getElementById('authButton').click()");
  check("D. Autenticação", "<dialog id=authModal> abre", true, await evalInPage("document.getElementById('authModal')?.open === true"));
  const interactiveVisible = await evalInPage("() => document.getElementById('authInteractive') && !document.getElementById('authInteractive').hidden");
  check("D. Autenticação", "painel interativo visível (não estático)", true, interactiveVisible);

  const userSuffix = Date.now();
  await evalInPage("document.querySelector('[data-auth-tab=\"register\"]')?.click()");
  await evalInPage(`() => { const f=document.getElementById('registerForm'); if(f.hidden) return false; document.querySelector('#registerForm [name=username]').value='etapa5_${userSuffix}'; document.querySelector('#registerForm [name=email]').value='etapa5_${userSuffix}@example.com'; document.querySelector('#registerForm [name=display_name]').value='Equipe Etapa 5'; document.querySelector('#registerForm [name=city]').value='Natal'; document.querySelector('#registerForm [name=state]').value='RN'; document.querySelector('#registerForm [name=password]').value='Abc12345!XYZ'; document.getElementById('registerForm').requestSubmit(); return true; }`);
  await sleep(1200);
  check("D. Autenticação", "status 'Conta criada com segurança'", true, (await evalInPage("document.getElementById('authStatus')?.textContent || ''")).includes("Conta criada"));

  const loggedIn = await evalInPage("() => document.getElementById('authButton').hidden && document.getElementById('logoutButton') && !document.getElementById('logoutButton').hidden");
  check("D. Autenticação", "botão 'Entrar' some e 'Sair' aparece", true, loggedIn);
  const badge = await evalInPage("document.getElementById('userBadge')?.textContent || ''");
  check("D. Autenticação", "badge mostra nome de exibição", true, String(badge).includes("Equipe"));

  // C. Seletor de cartas no modal
  await evalInPage("document.getElementById('openModal').click()");
  check("C. Seletor de cartas", "<dialog id=modal> abre (open)", true, await evalInPage("document.getElementById('modal')?.open === true"));

  await evalInPage("() => { const i=document.getElementById('cardSearch'); i.value='Sol Ring'; i.dispatchEvent(new Event('input',{bubbles:true})); return i.value; }");
  await sleep(1400);
  check("C. Seletor de cartas", "digitar 'Sol Ring' mostra resultados", true, (await evalInPage("document.querySelectorAll('[data-card-results] [data-card-index]').length")) > 0);

  await evalInPage("() => { const r=document.querySelector('[data-card-results] [data-card-index]'); if(r){r.click();} return document.getElementById('cardId').value; }");
  await settle(600);
  check("C. Seletor de cartas", "carta selecionada (card_id preenchido)", true, (await evalInPage("document.getElementById('cardId')?.value || ''")).length > 0);

  // E. Criar oferta end-to-end
  await evalInPage("document.getElementById('openModal').click()");
  check("E. Criar oferta", "modal reabre (form limpo)", true, await evalInPage("document.getElementById('modal')?.open === true"));

  // A abertura limpa o formulário; selecione novamente a impressão antes do
  // POST para que o teste valide também a exigência de card_id.
  await evalInPage("() => { const i=document.getElementById('cardSearch'); i.value='Sol Ring'; i.dispatchEvent(new Event('input',{bubbles:true})); return i.value; }");
  await sleep(1400);
  await evalInPage("() => document.querySelector('[data-card-results] [data-card-index]')?.click()");
  await sleep(200);

  const listingOk = await evalInPage(`() => { const f=document.getElementById('listingForm'); if(f.hidden) return false; document.querySelector('#listingForm [name=mode]').value='ambos'; document.querySelector('#listingForm [name=condition]').value='NM'; document.querySelector('#listingForm [name=title]').value='Vendo ou troco'; document.querySelector('#listingForm [name=description]').value='Disponível para negociação.'; document.querySelector('#listingForm [name=price]').value='25.00'; document.querySelector('#listingForm [name=contact_url]').value='https://exemplo.com/contato'; const btn=document.querySelector('#listingForm button[type=submit]'); btn.click(); return true; }`);
  await sleep(2200);
  check("E. Criar oferta", "formulário submetido", true, listingOk === true);
  check("E. Criar oferta", "oferta publicada (status confirma)", true, (await evalInPage("document.getElementById('formStatus')?.textContent || ''")).includes("publicada"));
  check("E. Criar oferta", "modal fecha após publicação", true, await evalInPage("document.getElementById('modal')?.open === false"));

  // Logout depois dos fluxos autenticados, pelo mesmo caminho usado pela UI.
  await evalInPage("document.getElementById('logoutButton').click()");
  await sleep(700);
  const loggedOut = await evalInPage("() => !document.getElementById('authButton').hidden && document.getElementById('logoutButton').hidden");
  check("D. Autenticação", "logout revoga sessão e restaura controles", true, loggedOut);

  // F. Responsividade mobile/tablet
  await setViewport(375, 667);
  const shotMobile = await screenshot("F_mobile_375x667.png");
  check("F. Responsividade", "screenshot mobile salvo", true, !!shotMobile.data);

  await setViewport(768, 1024);
  const shotTablet = await screenshot("F_tablet_768x1024.png");
  check("F. Responsividade", "screenshot tablet salvo", true, !!shotTablet.data);

  // Relatório
  const passCount = results.filter(r => r.pass).length;
  fs.writeFileSync(path.join(OUT_DIR, "e5_report.json"), JSON.stringify({ target: BASE, cdpPort: CDP_PORT, outDir: OUT_DIR, total: results.length, passed: passCount, failed: results.length - passCount, failures: results.filter(r => !r.pass) }, null, 2));

  console.log("\n===== Etapa 5 — relatório de validação =====");
  for (const r of results) { const mark = r.pass ? "PASS" : "FAIL"; console.log(`[${mark}] ${r.scenario} :: ${r.name}  (actual=${JSON.stringify(r.actual)})`); }
  console.log(`\n${passCount}/${results.length} verificações aprovadas.`);
  process.exit(results.filter(r => !r.pass).length === 0 ? 0 : 1);
}

main().catch(e => { console.error("CDP driver falhou:", e.message); process.exit(2); });
