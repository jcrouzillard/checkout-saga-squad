// D13 (efe387a35d71) — navegação do Squad Control: tarefas T1-T10, paridade PA-1..PA-23 e CA-1..CA-16.
// Executado em Docker (servidores do worktree no host):
//   docker run --rm --add-host=host.docker.internal:host-gateway -e NODE_PATH=/home/pptruser/node_modules \
//     -v "$PWD/tests/ui:/shots" -v "$DATA:/work/data" -w /home/pptruser ghcr.io/puppeteer/puppeteer:latest node /shots/d13-navegacao.js
// REAL = servidor com os dados reais, SOMENTE LEITURA (todo POST é abortado pelo script).
// FIX  = servidor com SQUAD_ROOT_DATA = cópia temporária ($DATA, montada em /work/data); o script acrescenta
//        fixtures ao log dessa cópia e confere nele os eventos gravados pela UI (nunca no log real).
// Autossuficiente: se a cópia não tiver as fixtures base (D14–D17), o script as cria; FIX_PID = pid vivo no host para o run
//   do Backend na D14 (ex.: -e FIX_PID=<pid do servidor FIX>). ONLY=<regex> roda só os cenários escolhidos.
const puppeteer = require('puppeteer');
const fs = require('fs');
const REAL = process.env.REAL || 'http://host.docker.internal:7112/';
const FIX = process.env.FIX || 'http://host.docker.internal:7113/';
const LOG = '/work/data/docs/squad/memory/decisions.jsonl';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const iso = (ms = Date.now()) => new Date(ms).toISOString().replace(/\.\d+Z$/, '+00:00');
const append = evs => { const have = new Set(readLog().map(e => e.id)); evs = evs.filter(e => !have.has(e.id)); if (evs.length) fs.appendFileSync(LOG, evs.map(e => JSON.stringify(e)).join('\n') + '\n'); };
const readLog = () => fs.readFileSync(LOG, 'utf8').trim().split('\n').map(l => JSON.parse(l));
const codeOf = id => { const t = readLog().filter(e => e.type === 'task' && e.agent === 'humano'); const i = t.findIndex(e => e.id === id); return i >= 0 ? `D${i + 1}` : null; };
const out = { errors: [], results: {} };
const R = (k, v) => { out.results[k] = v; console.error(`[${k}] ${JSON.stringify(v).slice(0, 400)}`); };

let browser;
async function newPage(base, w, opts = {}) {
  const ctx = await (browser.createBrowserContext ? browser.createBrowserContext() : browser.createIncognitoBrowserContext());
  const p = await ctx.newPage();
  p._ctx = ctx; p._w = w; p._posts = []; p._reqs = new Set(); p._clicks = [];
  await p.setViewport({ width: w, height: w <= 400 ? 844 : 1000 });
  await p.setRequestInterception(true);
  p.on('request', r => {
    const u = r.url();
    if (u.startsWith(base)) p._reqs.add(`${r.method()} ${u.replace(base, '/').replace(/\?.*$/, '')}`);
    if (r.method() === 'POST') {
      p._posts.push({ url: u.replace(base, '/'), body: r.postData() });
      if (opts.readOnly) return r.abort();
    }
    r.continue();
  });
  p.on('console', m => { if (m.type() === 'error' && !/favicon|localhost:(3000|16686|8090|8081)|ERR_CONNECTION|Failed to load resource/.test(m.text() + (m.location()?.url || ''))) out.errors.push(`${w}px console: ${m.text()}`); });
  p.on('pageerror', e => out.errors.push(`${w}px pageerror: ${e.message}`));
  return p;
}
// Primeira carga (ou hash vazio) = goto; depois, troca só o hash (como um link), o que também exercita o hashchange.
const go = async (p, base, hash = '') => {
  if (!hash || !p.url().startsWith(base)) { await p.goto(base + hash, { waitUntil: 'networkidle2' }); await sleep(1200); return; }
  await p.evaluate(h => { location.hash = h; }, hash); await sleep(900);
};
const waitHash = (p, h, t = 6000) => p.waitForFunction(h => location.hash === h, { timeout: t }, h).then(() => true).catch(() => false);
// Clique "real" (mouse) num elemento por seletor e (opcional) texto; conta o clique no caminho.
async function clk(p, sel, text, label, tries = 4) {
  // O polling (3 s) redesenha o #main: se o nó for trocado entre achar e clicar, procura de novo (não conta clique extra).
  for (let i = 1; ; i++) { try { return await clk1(p, sel, text, label); } catch (e) { if (i >= tries || !/detached|not clickable|not an Element/.test(String(e))) throw e; await sleep(300); } }
}
async function clk1(p, sel, text, label) {
  const h = await p.evaluateHandle((sel, text) => {
    const re = text ? new RegExp(text) : null;
    return [...document.querySelectorAll(sel)].find(e => (!re || re.test(e.textContent)) && e.getClientRects().length) || null;
  }, sel, text || '');
  const el = h.asElement();
  if (!el) throw new Error(`não encontrado: ${sel} ${text || ''}`);
  await el.evaluate(e => e.scrollIntoView({ block: 'center' }));
  await el.click();
  p._clicks.push(label || `${sel}${text ? ` "${text}"` : ''}`);
  await sleep(700);
}
const loc = p => p.evaluate(() => {
  const a = document.activeElement, de = document.documentElement;
  return { hash: location.hash, title: document.title, h1: document.querySelector('#main h1')?.textContent.trim(), h1count: document.querySelectorAll('#main h1').length,
    active: a ? `${a.tagName.toLowerCase()}${a.id ? '#' + a.id : ''}${a.getAttribute('href') ? `[href=${a.getAttribute('href')}]` : ''} "${(a.textContent || a.value || '').trim().slice(0, 40)}"` : null,
    activeIsH1: a?.tagName === 'H1', menu: [...document.querySelectorAll('#menu a[aria-current="page"]')].map(x => x.dataset.nav),
    crumbs: [...document.querySelectorAll('#main nav.crumbs li')].map(li => li.textContent.trim() + (li.querySelector('a') ? '(link)' : '')),
    srLive: document.querySelector('#sr-live')?.textContent, sw: de.scrollWidth, cw: de.clientWidth,
    usage: !document.querySelector('#ai-usage').hidden, drawer: !document.querySelector('#drawer').hidden };
});
const lastHuman = () => readLog().filter(e => e.type === 'human').at(-1);

async function scenario(name, fn) {
  if (process.env.ONLY && !new RegExp(process.env.ONLY).test(name)) return;
  const t0 = Date.now();
  try { await fn(); } catch (e) { R(name, { error: String(e && e.stack || e).slice(0, 600) }); }
  console.error(`-- ${name} ${Math.round((Date.now() - t0) / 1000)} s`);
}

// ---------------------------------------------------------------------------------------------
(async () => {
  browser = await puppeteer.launch({ args: ['--no-sandbox'] });

  // ===== Fixtures base (script autossuficiente): D14/D15/D16 ativas, D17 backlog, Backend trabalhando na D14 =====
  // Só na cópia temporária (/work/data). FIX_PID = pid vivo NO HOST (o servidor só testa kill(pid, 0)); sem ele, não há run.
  if (!readLog().some(e => e.id === 'fx14aaaaaaaa')) {
    const ago = m => iso(Date.now() - m * 60000), ev = [];
    for (const [code, did, title, t0] of [['D14', 'fx14aaaaaaaa', 'QA fixture A — demanda ativa do meio', 60], ['D15', 'fx15bbbbbbbb', 'QA fixture B — segunda ativa', 50], ['D16', 'fx16cccccccc', 'QA fixture C — ultima ativa', 40]]) {
      ev.push({ id: did, ts: ago(t0), agent: 'humano', type: 'task', to: 'orquestrador', title: `Demanda: ${title}`, detail: `Fixture do QA (${code}).`, priority: 'normal', kind: 'operacao' },
        { id: did + '-v', ts: ago(t0 - 1), agent: 'arquiteto', type: 'validation', demand: did, status: 'ok', title: 'Validação ok', questions: [] },
        { id: did + '-s', ts: ago(t0 - 2), agent: 'humano', type: 'start', to: 'orquestrador', demand: did, title: `Iniciar: ${title}`, priority: 'normal', route: 'padrao', target: 'auto' },
        { id: did + '-t', ts: ago(t0 - 3), agent: 'orquestrador', type: 'task', to: 'backend', demand: did, title: `${code}: implementar fixture` },
        { id: did + '-h', ts: ago(t0 - 5), agent: 'backend', type: 'handoff', to: 'auditor', demand: did, title: 'Implementação pronta', model: 'gpt-5-codex', modelProvider: 'OpenAI' });
    }
    ev.push({ id: 'fx17dddddddd', ts: ago(30), agent: 'humano', type: 'task', to: 'orquestrador', title: 'Demanda: QA fixture D — item de backlog', detail: 'Fixture de backlog.', priority: 'baixa', kind: 'produto', backlog: true });
    append(ev);
    if (process.env.FIX_PID) {
      const dir = '/work/data/.squad/runs'; fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(`${dir}/20260924120000-backend-qa0001.json`, JSON.stringify({ id: '20260924120000-backend-qa0001', agent: 'backend', runner: 'codex', demand: 'fx14aaaaaaaa', description: 'Backend · implementar fixture da D14',
        started: ago(20), status: 'trabalhando', pid: +process.env.FIX_PID, model: 'gpt-5-codex', modelProvider: 'OpenAI' }));
      fs.writeFileSync(`${dir}/20260924120000-backend-qa0001.log`, 'editando services/order-service/src/main/java/...\nrodando mvn -q test\n');
    }
    await sleep(1500);
  }

  // ===== CA-1..5, 11, 13-16: varredura de rotas (dados reais, somente leitura) + capturas =====
  const ROUTES = [
    ['', 'painel', 'Painel'], ['#/painel', 'painel', 'Painel'], ['#/demandas', 'demandas', 'Demandas'], ['#/demandas?f=todas', 'demandas', 'Demandas · Todas'],
    ['#/demandas?f=backlog', 'demandas', 'Demandas · Backlog'], ['#/demandas?f=fila', 'demandas', 'Demandas · Na fila'],
    ['#/demandas/nova', 'demandas', 'Nova demanda'], ['#/demandas/D13', 'demandas', 'D13'], ['#/demandas/efe387a35d71/gates', 'demandas', 'D13'],
    ['#/demandas/D11', 'demandas', 'D11'], ['#/demandas/D999', 'demandas', 'Demanda não encontrada'], ['#/squad', 'squad', 'Squad'],
    ['#/auditoria/eventos', 'auditoria', 'Auditoria · Eventos'], ['#/auditoria/eventos?demanda=D13&tipo=gate', 'auditoria', 'Auditoria · Eventos'],
    ['#/auditoria/gates?demanda=D11', 'auditoria', 'Auditoria · Gates'], ['#/auditoria/handoffs', 'auditoria', 'Auditoria · Handoffs'],
    ['#/auditoria/politicas', 'auditoria', 'Auditoria · Políticas'], ['#/produto/grafana', 'produto', 'Produto · Grafana'], ['#/produto/jaeger', 'produto', 'Produto · Jaeger'],
    ['#/painel?agente=backend', 'painel', 'Painel'],
    // aliases e rota desconhecida
    ['#execucoes', 'demandas', null], ['#/decisoes', 'auditoria', 'Auditoria · Eventos'], ['#/evidencias', 'auditoria', 'Auditoria · Gates'],
    ['#/politicas', 'auditoria', 'Auditoria · Políticas'], ['#/agentes', 'squad', 'Squad'], ['#/observabilidade', 'produto', 'Produto · Grafana'],
    ['#/xyz', 'painel', 'Painel'], ['#/painel#squad-base', 'painel', 'Painel'],
  ];
  for (const w of [1440, 390]) await scenario(`rotas-${w}`, async () => {
    const p = await newPage(REAL, w, { readOnly: true });
    await go(p, REAL, '#/painel');
    const struct = await p.evaluate(() => {
      const nav = document.querySelectorAll('nav[aria-label="Principal"]');
      const items = [...document.querySelectorAll('nav[aria-label="Principal"] a')].map(a => a.textContent.replace(/\d+/g, '').trim());
      const focusables = [...document.querySelectorAll('a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])')].filter(e => !e.disabled);
      const ext = [...document.querySelectorAll('a[target=_blank]')];
      return { navCount: nav.length, items, tabs: document.querySelectorAll('.tabs').length, firstFocusable: focusables[0]?.textContent.trim(),
        scripts: [...document.querySelectorAll('script[src]')].map(s => s.src), links: [...document.querySelectorAll('link[href]')].map(l => l.href),
        sideWidth: Math.round(document.querySelector('.side').getBoundingClientRect().width), menuH: [...document.querySelectorAll('#menu a')].map(a => Math.round(a.getBoundingClientRect().height)) };
    });
    const res = [];
    for (const [h, view, title] of ROUTES) {
      await go(p, REAL, h); await sleep(300);
      const l = await loc(p);
      const ext = await p.evaluate(() => [...document.querySelectorAll('a[target=_blank]')].filter(a => a.getClientRects().length).map(a => ({ t: a.textContent.trim().slice(0, 40),
        arrow: getComputedStyle(a, '::after').content.includes('↗') || a.textContent.includes('↗'), sr: /abre em nova aba/.test(a.textContent) })));
      const internalBad = await p.evaluate(() => [...document.querySelectorAll('#main a[href], #menu a[href]')].filter(a => !a.target && !a.getAttribute('href').startsWith('#/') && !a.getAttribute('href').startsWith('http')).map(a => a.getAttribute('href')).slice(0, 5));
      res.push({ h, hash: l.hash, menu: l.menu, menuOk: l.menu.length === 1 && l.menu[0] === view, title: l.title, titleOk: !title || l.title.replace(/^\(\d+\) /, '').startsWith(title + ' · Squad Control'),
        h1: l.h1, h1count: l.h1count, crumbs: l.crumbs, usage: l.usage, usageOk: l.usage === (view !== 'produto'), noHScroll: l.sw <= l.cw, drawer: l.drawer,
        extNoArrow: ext.filter(x => !x.arrow).map(x => x.t), extNoSr: ext.filter(x => !x.sr).map(x => x.t), internalBad,
        notice: await p.evaluate(() => document.querySelector('#main .notice')?.textContent || '') });
      if (w === 1440 || ['#/painel', '#/demandas', '#/demandas/D13', '#/demandas/D11', '#/auditoria/eventos', '#/produto/grafana'].includes(h)) {
        const shot = { '#/painel': 'painel', '#/demandas': 'demandas', '#/demandas/D13': 'demanda-ativa', '#/demandas/D11': 'demanda-entregue', '#/auditoria/eventos': 'auditoria', '#/produto/grafana': 'produto' }[h];
        if (shot) await p.screenshot({ path: `/shots/d13-${shot}-${w}.png`, fullPage: shot !== 'produto' && shot !== 'auditoria' });
      }
    }
    // Voltar do navegador entre telas
    await go(p, REAL, '#/painel'); await clk(p, '#menu a[data-nav="demandas"]'); await clk(p, '#main a.ttl'); await clk(p, '#menu a[data-nav="auditoria"]');   // D14: a D13 real já foi entregue e saiu da lista padrão; vale a 1ª demanda listada
    const back = []; for (let i = 0; i < 3; i++) { await p.goBack(); await sleep(700); back.push((await loc(p)).hash); }
    R(`CA-rotas-${w}`, { struct, routes: res, back, posts: p._posts, reqs: [...p._reqs] });
    await p._ctx.close();
  });

  // ===== T3 (dados reais): qual PR entregou uma demanda já entregue e quais gates a aprovaram =====
  for (const w of [1440, 390]) await scenario(`T3-${w}`, async () => {
    const p = await newPage(REAL, w, { readOnly: true });
    await go(p, REAL, '#/painel');
    await clk(p, '#main section[aria-labelledby="h-entregues"] a.ttl', 'D11', 'Painel › Entregues recentemente › D11');
    const info = await p.evaluate(() => ({ hash: location.hash, delivered: document.querySelector('#main .pass')?.textContent.trim().slice(0, 160),
      prTag: [...document.querySelectorAll('#main .page-head a.ext')].map(a => a.textContent.trim()),
      gates: [...document.querySelectorAll('#sec-gates .card b')].map(b => b.textContent.trim()), stepper: document.querySelector('.stepper-legend')?.textContent }));
    R(`T3-${w}`, { clicks: p._clicks, n: p._clicks.length, ...info, ok: /D11$/.test(info.hash) && /PR #\d+/.test(info.delivered || '') && info.gates.some(g => /G3 · APPROVE/.test(g)) });
    await p._ctx.close();
  });

  // ===== T2 via toast (1440): gate RETURN obrigatório na D14, que NÃO é a última ativa =====
  const D14 = 'fx14aaaaaaaa', D15 = 'fx15bbbbbbbb', D16 = 'fx16cccccccc';
  const gate = (demand, g, reco, conf, extra = {}, dt = 0) => ({ id: `qa${Math.random().toString(16).slice(2, 12)}`, ts: iso(Date.now() + dt), agent: 'auditor', type: 'gate', gate: g, demand,
    recommendation: reco, confidence: conf, risk: extra.risk || 'moderado', human_required: extra.human_required, to: 'orquestrador', title: `${g}: ${reco}`, detail: extra.detail || 'Parecer de fixture do QA',
    evidences: [{ name: 'Evidência de fixture', status: reco === 'APPROVE' ? 'pass' : 'fail' }], model: 'claude-opus-5-5' });
  await scenario('T2-toast-1440', async () => {
    const p = await newPage(FIX, 1440);
    await go(p, FIX, '#/painel'); await sleep(1500);
    append([gate(D14, 'G2', 'RETURN', 0.62, { human_required: true, detail: 'D14 devolvida: exige humano' }), gate(D16, 'G1', 'APPROVE', 0.91, {}, 1000)]);
    await p.waitForFunction(() => [...document.querySelectorAll('.toast')].some(t => /D14/.test(t.textContent)), { timeout: 10000 });
    const toasts = await p.evaluate(() => [...document.querySelectorAll('.toast')].map(t => t.textContent.replace(/\s+/g, ' ').trim()));
    const painelBadge = await p.evaluate(() => ({ c: document.querySelector('#c-painel').textContent, alert: document.querySelector('#c-painel').classList.contains('alert'),
      needs: [...document.querySelectorAll('#main section[aria-labelledby="h-precisa"] li')].map(li => li.textContent.replace(/\s+/g, ' ').trim().slice(0, 90)) }));
    await clk(p, '.toast button[data-goto]', 'Abrir D14', 'toast "Abrir D14"');
    await waitHash(p, '#/demandas/D14/gates'); await sleep(500);
    const at = await loc(p);
    const box = await p.evaluate(() => ({ h2: document.querySelector('#main .next-box h2')?.textContent, gateBtns: [...document.querySelectorAll('#main .next-box [data-human]')].map(b => `${b.textContent.trim()}|${b.dataset.gate}|${b.dataset.demand}`) }));
    await p.keyboard.type('QA T2 toast: aceito a devolução da D14');
    await clk(p, '#main .next-box [data-human="APPROVE"]', null, 'Aceitar devolução (D14 G2)');
    await sleep(1500);
    const h = lastHuman(); const msg = await p.evaluate(() => document.querySelector('#main .next-box .ok-msg, #main .ok-msg')?.textContent);
    R('T2-toast-1440', { toasts, painelBadge, clicks: p._clicks, n: p._clicks.length, landed: at, box, post: p._posts.at(-1), human: h, msg,
      ok: h && h.gate === 'G2' && h.demand === D14 && h.recommendation === 'APPROVE' && h.detail.includes('QA T2') && at.hash === '#/demandas/D14/gates' && /note-fx14aaaaaaaa-G2/.test(at.active) && p._clicks.length <= 3 });
    await p._ctx.close();
  });

  // ===== T2 via sino (390): RETURN com confiança < 70% na D15 (não é a última ativa; a última é a D16) =====
  await scenario('T2-sino-390', async () => {
    const p = await newPage(FIX, 390);
    await go(p, FIX, '#/painel'); await sleep(1500);
    append([gate(D15, 'G2', 'RETURN', 0.58, { risk: 'moderado', detail: 'D15 devolvida: confiança 58%' }), gate(D16, 'G2', 'APPROVE', 0.9, {}, 1000)]);
    await p.waitForFunction(() => /\d/.test(document.querySelector('#bell-badge').textContent) && !document.querySelector('#bell-badge').hidden, { timeout: 10000 });
    await sleep(3500);
    await p.evaluate(() => document.querySelectorAll('.toast').forEach(t => t.remove()));  // usa o sino, não o toast
    await clk(p, '#bell', null, 'sino');
    const items = await p.evaluate(() => [...document.querySelectorAll('#notif-panel a.notif')].slice(0, 4).map(a => `${a.getAttribute('href')} :: ${a.textContent.replace(/\s+/g, ' ').trim().slice(0, 80)}`));
    await clk(p, '#notif-panel a.notif', 'D15 · Auditor devolveu G2', 'item do sino "D15 · Auditor devolveu G2"');
    await waitHash(p, '#/demandas/D15/gates'); await sleep(500);
    const at = await loc(p);
    await p.keyboard.type('QA T2 sino: seguir mesmo assim');
    await clk(p, '#main .next-box [data-human="OVERRIDE"]', null, 'Seguir mesmo assim (D15 G2)');
    await sleep(1500);
    const h = lastHuman();
    await p.screenshot({ path: '/shots/d13-t2-decisao-390.png' });
    R('T2-sino-390', { items, clicks: p._clicks, n: p._clicks.length, landed: at, post: p._posts.at(-1), human: h,
      ok: h && h.gate === 'G2' && h.demand === D15 && h.recommendation === 'OVERRIDE' && at.hash === '#/demandas/D15/gates' && p._clicks.length <= 3 && at.sw <= at.cw });
    await p._ctx.close();
  });

  // ===== T10 + T2 pela página (Painel › Precisa de você), só teclado (1440) =====
  await scenario('T10-teclado-1440', async () => {
    append([gate(D14, 'G2', 'RETURN', 0.6, { human_required: true, detail: 'D14 ciclo 2: exige humano' }), gate(D16, 'G3', 'APPROVE', 0.93, {}, 1000)]);
    const p = await newPage(FIX, 1440);
    await go(p, FIX, '#/painel'); await sleep(1500);
    const steps = [{ key: 'carga', active: (await loc(p)).active }];
    // Na carga o foco já está no h1 (conteúdo). O "Pular para o conteúdo" é o 1º focável do documento: volta até ele com Shift+Tab.
    let back = 0; for (; back < 20; back++) { await p.keyboard.down('Shift'); await p.keyboard.press('Tab'); await p.keyboard.up('Shift'); if (await p.evaluate(() => document.activeElement?.id === 'skip')) { back++; break; } }
    const skipVisible = await p.evaluate(() => { const r = document.querySelector('#skip').getBoundingClientRect(); return r.top >= 0 && r.bottom > 0; });
    const first = await loc(p); steps.push({ key: `Shift+Tab x${back}`, active: first.active, skipVisible });
    await p.keyboard.press('Enter'); await sleep(300); const afterSkip = await loc(p); steps.push({ key: 'Enter (skip)', active: afterSkip.active, activeIsH1: afterSkip.activeIsH1 });
    let tabs = 0, found = false;
    for (; tabs < 80; tabs++) { await p.keyboard.press('Tab'); if (await p.evaluate(() => document.activeElement?.getAttribute('href') === '#/demandas/D14/gates')) { found = true; tabs++; break; } }
    steps.push({ key: `Tab x${tabs}`, found });
    await p.keyboard.press('Enter'); await waitHash(p, '#/demandas/D14/gates'); await sleep(600);
    const landed = await loc(p);
    await p.keyboard.type('QA T10 teclado: devolver ao Backend');
    let t2 = 0; for (; t2 < 6; t2++) { await p.keyboard.press('Tab'); if (await p.evaluate(() => document.activeElement?.dataset?.human === 'APPROVE')) { t2++; break; } }
    const btn = await p.evaluate(() => `${document.activeElement.textContent.trim()}|${document.activeElement.dataset.gate}|${document.activeElement.dataset.demand}`);
    await p.keyboard.press('Enter'); await sleep(1600);
    const h = lastHuman(); const afterDecision = await loc(p);
    // troca de rota por teclado no menu: foco no h1 + anúncio
    const menuNav = [];
    for (const nav of ['demandas', 'squad', 'auditoria', 'painel']) {
      await p.focus(`#menu a[data-nav="${nav}"]`); await p.keyboard.press('Enter'); await sleep(900);
      const l = await loc(p); menuNav.push({ nav, hash: l.hash, activeIsH1: l.activeIsH1, h1: l.h1, srLive: l.srLive });
    }
    // Esc fecha a gaveta e o sino
    await p.focus('#main .squad a.agent'); await p.keyboard.press('Enter'); await sleep(800);
    const drawerOpen = await loc(p);
    await p.keyboard.press('Escape'); await sleep(800); const drawerClosed = await loc(p);
    await p.focus('#bell'); await p.keyboard.press('Enter'); await sleep(400);
    const bellOpen = await p.evaluate(() => !document.querySelector('#notif-panel').hidden);
    await p.keyboard.press('Escape'); await sleep(400);
    const bellClosed = await p.evaluate(() => ({ hidden: document.querySelector('#notif-panel').hidden, focusBell: document.activeElement?.id === 'bell' }));
    R('T10-teclado-1440', { steps, landed, t2, btn, human: h, afterDecisionSr: afterDecision.srLive, menuNav,
      drawer: { open: drawerOpen.drawer, hashOpen: drawerOpen.hash, focus: drawerOpen.active, closed: !drawerClosed.drawer, hashClosed: drawerClosed.hash }, bellOpen, bellClosed,
      ok: /Pular para o conteúdo/.test(first.active) && afterSkip.activeIsH1 && found && /note-fx14aaaaaaaa-G2/.test(landed.active) && h?.gate === 'G2' && h?.demand === D14 && h?.detail.includes('QA T10') && menuNav.every(m => m.activeIsH1 && /aberta/.test(m.srLive || '')) });
    await p._ctx.close();
  });

  // ===== T9: Nova demanda meio preenchida por >= 3 ciclos de polling (1440 e 390) + CA-11 na página da demanda =====
  for (const w of [1440, 390]) await scenario(`T9-${w}`, async () => {
    const p = await newPage(FIX, w);
    await go(p, FIX, '#/demandas/nova');
    await p.focus('#dem-title'); await p.keyboard.type('Meia demanda do QA');
    await clk(p, '#dem-kind-operacao', null, 'tipo operação');
    await p.focus('#dem-detail'); await p.keyboard.type('Descrição pela metade, ainda sendo escr');
    const before = await p.evaluate(() => ({ sel: document.activeElement.selectionStart, id: document.activeElement.id }));
    append([{ id: `qa${Date.now()}`, ts: iso(), agent: 'qa', type: 'progress', title: 'QA: evento durante o T9 (força mudança no /api/state)', demand: D16 }]);
    // D14 (§8.2): o polling agora é GET /api/live a cada 1,5 s; /api/state só quando a versão muda ou a cada 15 s.
    const reqs0 = [...p._reqs].length; let polls = 0; p.on('request', r => { if (r.url().includes('/api/live')) polls++; });
    await sleep(10500);
    await p.keyboard.type('evendo');
    const after = await p.evaluate(() => ({ hash: location.hash, title: document.querySelector('#dem-title').value, detail: document.querySelector('#dem-detail').value, kind: document.querySelector('#dem-kind-operacao').checked,
      active: document.activeElement.id, sel: document.activeElement.selectionStart, usageVisible: !document.querySelector('#ai-usage').hidden, scrollY }));
    // CA-11: details aberto + rolagem na página da demanda sobrevivem ao polling
    await go(p, FIX, '#/demandas/D14');
    await p.evaluate(() => { const d = document.querySelector('#main details[id^="reg-"]'); d.open = true; window.scrollTo(0, 600); });
    const y0 = await p.evaluate(() => scrollY); await sleep(7000);
    const ca11 = await p.evaluate(y0 => ({ open: document.querySelector('#main details[id^="reg-"]').open, y: scrollY, y0, hash: location.hash }), y0);
    R(`T9-${w}`, { polls, before, after, ca11, ok: polls >= 3 && after.title === 'Meia demanda do QA' && after.detail === 'Descrição pela metade, ainda sendo escrevendo' && after.kind && after.active === 'dem-detail' && after.hash === '#/demandas/nova' && ca11.open && Math.abs(ca11.y - y0) < 3 });
    await p._ctx.close();
  });

  // ===== T5: URL da seção Gates em outra aba + F5; filtros e gaveta na URL =====
  await scenario('T5-1440', async () => {
    const p = await newPage(FIX, 1440);
    const url = '#/demandas/D14/gates';
    await go(p, FIX, url);
    const sec = () => p.evaluate(() => ({ hash: location.hash, h1: document.querySelector('#main h1')?.textContent, toc: document.querySelector('.toc a[aria-current]')?.textContent,
      gatesTop: Math.round(document.querySelector('#sec-gates').getBoundingClientRect().top), nextTop: Math.round(document.querySelector('#main .next-box')?.getBoundingClientRect().top ?? -1), scrollY, active: document.activeElement?.id || document.activeElement?.tagName }));
    const a = await sec();
    await p.reload({ waitUntil: 'networkidle2' }); await sleep(1500); const b = await sec();
    const p2 = await p._ctx.newPage(); await p2.setViewport({ width: 1440, height: 1000 }); await p2.goto(FIX + url, { waitUntil: 'networkidle2' }); await sleep(1500);
    const c = await p2.evaluate(() => ({ hash: location.hash, h1: document.querySelector('#main h1')?.textContent, toc: document.querySelector('.toc a[aria-current]')?.textContent, scrollY }));
    await p2.close();
    // D16 (sem decisão pendente): a seção Gates deve ficar no topo
    await go(p, FIX, '#/demandas/D16/gates'); const d16 = await sec();
    await go(p, FIX, '#/demandas/D14/execucao?agente=backend'); await p.reload({ waitUntil: 'networkidle2' }); await sleep(1500);
    const drawer = await loc(p);
    await go(p, FIX, '#/demandas?f=backlog'); await p.reload({ waitUntil: 'networkidle2' }); await sleep(1200);
    const filt = await p.evaluate(() => ({ hash: location.hash, cur: document.querySelector('nav.seg a[aria-current]')?.textContent.trim() }));
    await go(p, FIX, '#/auditoria/eventos?demanda=D14&tipo=gate'); await p.reload({ waitUntil: 'networkidle2' }); await sleep(1200);
    const aud = await p.evaluate(() => ({ hash: location.hash, sel: [...document.querySelectorAll('.filters select')].map(s => s.value), rows: document.querySelectorAll('#main tbody tr').length }));
    R('T5-1440', { first: a, reload: b, otherTab: c, d16, drawer: { hash: drawer.hash, open: drawer.drawer }, filt, aud,
      ok: [a, b, c].every(x => x.hash === url && x.toc === 'Gates') && drawer.drawer && filt.cur?.startsWith('Backlog') && aud.sel.join() === 'D14,,gate' });
    await p._ctx.close();
  });

  // ===== T7: Jaeger pelo menu, link externo ↗ e Voltar (1440 e 390) =====
  for (const w of [1440, 390]) await scenario(`T7-${w}`, async () => {
    const p = await newPage(FIX, w);
    await go(p, FIX, '#/demandas/D14'); await clk(p, '#menu a[data-nav="painel"]', null, 'menu Painel (ponto de partida)'); p._clicks = [];
    await clk(p, '#menu a[data-nav="produto"]', null, 'menu Produto');
    await clk(p, '#main nav.seg a', 'Jaeger', 'segmento Jaeger');
    const j = await p.evaluate(() => ({ hash: location.hash, iframe: document.querySelector('#main iframe')?.src, ext: [...document.querySelectorAll('#main a[target=_blank]')].map(a => ({ t: a.textContent.trim(), arrow: getComputedStyle(a, '::after').content })) }));
    const newTarget = new Promise(r => browser.once('targetcreated', t => r(t.url())));
    await clk(p, '#main a[target=_blank]', 'Abrir Jaeger', 'Abrir Jaeger em nova aba ↗');
    const opened = await Promise.race([newTarget, sleep(4000).then(() => null)]);
    const stay = (await loc(p)).hash;
    await p.goBack(); await sleep(900); const back1 = await loc(p);
    await p.goBack(); await sleep(900); const back2 = await loc(p);
    R(`T7-${w}`, { clicks: p._clicks, n: p._clicks.length, jaeger: j, opened, stay, back1: { hash: back1.hash, menu: back1.menu, activeIsH1: back1.activeIsH1 }, back2: { hash: back2.hash, menu: back2.menu },
      ok: j.hash === '#/produto/jaeger' && /16686/.test(j.iframe || '') && stay === '#/produto/jaeger' && back1.hash === '#/produto/grafana' && back2.hash === '#/painel' && p._clicks.length <= 3 });
    await p._ctx.close();
  });

  // ===== T1: registrar demanda "operação" e responder às perguntas sem usar o menu (1440 e 390) =====
  for (const w of [1440, 390]) await scenario(`T1-${w}`, async () => {
    const p = await newPage(FIX, w);
    await go(p, FIX, '#/painel');
    await clk(p, '#main .page-head a.btn.primary', 'Nova demanda', 'Painel "+ Nova demanda"');
    // PA-1: validações do formulário
    await clk(p, '#main [data-register]', null, 'Registrar (vazio)'); const e1 = await p.evaluate(() => document.querySelector('#main .fail')?.textContent);
    await p.focus('#dem-title'); await p.keyboard.type(`QA T1 ${w}px — demanda operação`);
    await clk(p, '#main [data-register]', null, 'Registrar (sem tipo)'); const e2 = await p.evaluate(() => document.querySelector('#main .fail')?.textContent);
    await p.focus('#dem-detail'); await p.keyboard.type('Critério: aparece na página da demanda.');
    await clk(p, '#dem-kind-operacao', null, 'tipo operação');
    p._clicks.push('--- após registrar ---');
    await clk(p, '#main [data-register]', null, 'Registrar demanda');
    await p.waitForFunction(() => /^#\/demandas\/D\d+$/.test(location.hash), { timeout: 8000 });
    const reg = await loc(p); const post = p._posts.at(-1);
    const id = readLog().filter(e => e.type === 'task' && e.agent === 'humano').at(-1).id;
    const kClicks = p._clicks.indexOf('--- após registrar ---');
    append([{ id: `qav${Date.now()}`, ts: iso(), agent: 'arquiteto', type: 'validation', demand: id, status: 'perguntas', title: 'Validação: 2 perguntas',
      questions: [{ id: 'q1', text: 'Qual o critério de aceite?', dimension: 'aceite' }, { id: 'q2', text: 'Há restrição de escopo?', dimension: 'escopo' }] }]);
    await p.waitForFunction(() => /Responder 2 perguntas/.test(document.querySelector('#main .next-box')?.textContent || ''), { timeout: 10000 });
    const nextBox = await p.evaluate(() => document.querySelector('#main .next-box h2').textContent);
    const c0 = p._clicks.length;
    await clk(p, '#main .next-box a', 'Validação', 'Próxima ação › link Validação');
    const land = await loc(p);
    await p.keyboard.type('Aparece na página da demanda.');
    await clk(p, '#main textarea[data-ans][data-q="q2"]', null, '2ª resposta');
    await p.keyboard.type('Só Squad Control.');
    await clk(p, '#main [data-clarify]', null, 'Enviar respostas');
    await sleep(1500);
    const clar = readLog().filter(e => e.type === 'clarification' && e.demand === id).at(-1);
    const after = await p.evaluate(() => ({ next: document.querySelector('#main .next-box h2')?.textContent, msg: document.querySelector('#main .ok-msg')?.textContent, sr: document.querySelector('#sr-live').textContent, hash: location.hash }));
    if (w === 390) await p.screenshot({ path: '/shots/d13-t1-validacao-390.png', fullPage: false });
    R(`T1-${w}`, { errors: [e1, e2], clicksBefore: p._clicks.slice(0, kClicks), reg: { hash: reg.hash, h1: reg.h1, menu: reg.menu }, post, id, nextBox, landed: { hash: land.hash, active: land.active },
      clicksAfterRegister: p._clicks.slice(c0), nAfter: p._clicks.length - c0, clar: clar && clar.answers, after, usedMenu: p._clicks.some(c => /menu/.test(c)),
      ok: !!clar && clar.answers.length === 2 && p._clicks.length - c0 <= 3 && /Iniciar/.test(after.next || '') && !p._clicks.some(c => /menu/.test(c)) });
    out.t1ids = (out.t1ids || []).concat(id);
    await p._ctx.close();
  });

  // ===== T4: o que o Backend faz na demanda ativa → gaveta → abrir a demanda da sessão (1440 e 390) =====
  for (const w of [1440, 390]) await scenario(`T4-${w}`, async () => {
    const p = await newPage(FIX, w);
    await go(p, FIX, '#/painel');
    const now = await p.evaluate(() => [...document.querySelectorAll('#main section[aria-labelledby="h-andamento"] li')].map(li => li.textContent.replace(/\s+/g, ' ').trim().slice(0, 140)).filter(t => /D14/.test(t)));
    await clk(p, '#main .squad a.agent', 'Backend', 'Painel › faixa de agentes › Backend');
    const dr = await p.evaluate(() => ({ hash: location.hash, open: !document.querySelector('#drawer').hidden, text: document.querySelector('#drawer').innerText.slice(0, 300), focus: document.activeElement?.id }));
    await clk(p, '#drawer a', 'Abrir D14', 'gaveta › "Abrir D14 ›"');
    const l = await loc(p);
    if (w === 1440) { await go(p, FIX, '#/demandas/D14?agente=backend'); await p.screenshot({ path: '/shots/d13-gaveta-1440.png' }); }
    R(`T4-${w}`, { now, clicks: p._clicks, n: p._clicks.length, drawer: dr, landed: { hash: l.hash, drawer: l.drawer, menu: l.menu, h1: l.h1 },
      ok: dr.open && /Executando agora|trabalhando/i.test(dr.text)   /* D14: rótulos de estado em maiúsculas (CSS) */ && l.hash === '#/demandas/D14' && !l.drawer && p._clicks.length <= 3 });
    await p._ctx.close();
  });

  // ===== T6: mover item do backlog para a fila e confirmar a posição (1440) + PA-4 editar =====
  await scenario('T6-1440', async () => {
    const p = await newPage(FIX, 1440);
    await go(p, FIX, '#/painel');
    await clk(p, '#menu a[data-nav="demandas"]', null, 'menu Demandas');
    await clk(p, '#main nav.seg a', 'Backlog', 'filtro Backlog');
    const bl = await p.evaluate(() => [...document.querySelectorAll('#main .bl-item b')].map(b => b.textContent.trim()));
    // PA-4: editar (título) e salvar
    const c4 = p._clicks.length;
    await clk(p, '#main [data-bl-edit="fx17dddddddd"]', null, 'Editar (PA-4)');
    await p.evaluate(() => { const i = document.querySelector('#ble-t-fx17dddddddd'); i.value = ''; i.focus(); }); await p.keyboard.type('QA fixture D — item de backlog (editado)');
    await clk(p, '#main [data-bl-save="fx17dddddddd"]', null, 'Salvar (PA-4)');
    const edit = readLog().filter(e => e.type === 'edit' && e.demand === 'fx17dddddddd').at(-1);
    const pa4 = p._clicks.slice(c4);
    p._clicks = p._clicks.slice(0, c4);
    await clk(p, '#main [data-start="fx17dddddddd"]', null, 'Mover para a fila');
    await sleep(1200);
    const msg = await p.evaluate(() => document.querySelector('#main .ok-msg')?.textContent);
    await clk(p, '#main nav.seg a', 'Na fila', 'filtro Na fila');
    const fila = await p.evaluate(() => [...document.querySelectorAll('#main ul.rows li')].map(li => li.textContent.replace(/\s+/g, ' ').trim().slice(0, 120)));
    const start = readLog().filter(e => e.type === 'start' && e.demand === 'fx17dddddddd').at(-1);
    R('T6-1440', { backlog: bl, pa4: { clicks: pa4, edit: edit && edit.changes }, clicks: p._clicks, n: p._clicks.length, msg, fila, start: start && { fromBacklog: start.fromBacklog, priority: start.priority },
      ok: !!start && start.fromBacklog && fila.some(t => /D17/.test(t) && /º na fila/.test(t)) && p._clicks.length <= 4 });
    await p.screenshot({ path: '/shots/d13-fila-1440.png' });
    await p._ctx.close();
  });

  // ===== T8: regra dos gates (Políticas) =====
  for (const w of [1440, 390]) await scenario(`T8-${w}`, async () => {
    const p = await newPage(FIX, w);
    await go(p, FIX, '#/painel');
    await clk(p, '#menu a[data-nav="auditoria"]', null, 'menu Auditoria');
    await clk(p, '#main nav.seg a', 'Políticas', 'aba Políticas');
    await sleep(800);
    const r = await p.evaluate(() => ({ hash: location.hash, h3: [...document.querySelectorAll('#main h3')].map(h => h.textContent), hasGates: /G1|G2|G3/.test(document.querySelector('#main pre')?.textContent || '') }));
    R(`T8-${w}`, { clicks: p._clicks, n: p._clicks.length, ...r, ok: r.hash === '#/auditoria/politicas' && r.hasGates && p._clicks.length <= 2 });
    await p._ctx.close();
  });

  // ===== Paridade: itens que as tarefas não cobrem =====
  await scenario('PA-extra-1440', async () => {
    const LATE = 'fx18late0000', REJ = 'fx19rej00000';
    const t = m => iso(Date.now() - m * 60000);
    append([
      { id: LATE, ts: t(6), agent: 'humano', type: 'task', to: 'orquestrador', title: 'Demanda: QA fixture E — validação atrasada', detail: '', priority: 'normal', kind: 'operacao' },
      { id: REJ, ts: t(5), agent: 'humano', type: 'task', to: 'orquestrador', title: 'Demanda: QA fixture F — devolvida pelo revisor', detail: '', priority: 'normal', kind: 'operacao' },
      { id: REJ + 'v', ts: t(5), agent: 'arquiteto', type: 'validation', demand: REJ, status: 'ok', questions: [] },
      { id: REJ + 's', ts: t(4), agent: 'humano', type: 'start', demand: REJ, title: 'Iniciar: F', priority: 'normal', route: 'padrao', target: 'auto' },
      { id: REJ + 'h', ts: t(4), agent: 'frontend', type: 'handoff', demand: REJ, title: 'feito' },
      { id: REJ + 'g', ts: t(3), agent: 'auditor', type: 'gate', gate: 'G3', demand: REJ, recommendation: 'APPROVE', confidence: 0.9, risk: 'baixo' },
      { id: REJ + 'r', ts: t(3), agent: 'orquestrador', type: 'review', demand: REJ, pr: 901, url: 'https://github.com/x/y/pull/901', title: 'PR aberto' },
      { id: REJ + 'x', ts: t(2), agent: 'orquestrador', type: 'review-rejected', demand: REJ, pr: 901, url: 'https://github.com/x/y/pull/901', title: 'Revisor devolveu', detail: 'Ajustar o rótulo.' },
    ]);
    const cLate = codeOf(LATE), cRej = codeOf(REJ);
    const p = await newPage(FIX, 1440);
    await go(p, FIX, '#/painel'); await sleep(1500);
    const res = {};
    const needs = await p.evaluate(() => [...document.querySelectorAll('#main section[aria-labelledby="h-precisa"] li')].map(li => li.textContent.replace(/\s+/g, ' ').trim().slice(0, 110)));
    res.precisa = needs;
    // PA-3 override com nota (validação atrasada): Painel › "Ver validação" › marcar override › nota › Iniciar
    p._clicks = [];
    const part = async (k, fn) => { try { await fn(); } catch (e) { res[k] = { error: String(e).slice(0, 200), clicks: p._clicks.slice() }; } };
    await part('PA-3-override', async () => {
    const pre = readLog().filter(e => e.type === 'start' && e.demand === LATE).at(-1);
    if (pre) { res['PA-3-override'] = { note: 'já executado na 1ª rodada (mesmo fluxo)', clicks: ['Painel › Ver validação', 'override', 'Iniciar sem nota', 'Iniciar (override)'], start: { override: pre.override, detail: pre.detail } }; return; }
    await clk(p, `#main section[aria-labelledby="h-precisa"] a[href="#/demandas/${cLate}"]`, 'Ver validação', `Painel › Ver validação (${cLate})`);
    await clk(p, `#ovc-${LATE}`, null, 'override');
    await clk(p, `#start-${LATE}`, null, 'Iniciar sem nota'); const noNote = await p.evaluate(() => document.querySelector('#main .fail')?.textContent);
    await p.focus(`#ovn-${LATE}`); await p.keyboard.type('QA: validação atrasada, seguir');
    await clk(p, `#start-${LATE}`, null, 'Iniciar (override)'); await sleep(1000);
    const st = readLog().filter(e => e.type === 'start' && e.demand === LATE).at(-1);
    res['PA-3-override'] = { clicks: p._clicks, noNote, start: st && { override: st.override, detail: st.detail } }; });
    // PA-7: pausar, retomar, repriorizar, cancelar (em andamento) na D16
    await go(p, FIX, '#/painel'); p._clicks = [];
    await clk(p, '#main section[aria-labelledby="h-andamento"] a.ttl', 'D16', 'Painel › Em andamento › D16');
    await clk(p, '#main [data-ctl="pause"]', null, 'Pausar'); await sleep(800);
    await clk(p, '#main [data-ctl="resume"]', null, 'Retomar'); await sleep(800);
    await p.select('#main [data-ctlpr="fx16cccccccc"]', 'alta'); p._clicks.push('Prioridade=alta (select)'); await sleep(1200);
    { const b = await p.$('#main [data-ctl="cancel"]'); await b.click(); p._clicks.push('Cancelar demanda'); const txt = await b.evaluate(e => e.textContent); await b.click(); p._clicks.push(`Confirmar cancelamento (${txt})`); } await sleep(1500);
    res['PA-7'] = { clicks: p._clicks, controls: readLog().filter(e => e.type === 'control' && e.demand === 'fx16cccccccc').map(e => e.action + (e.priority ? ':' + e.priority : '')), status: await p.evaluate(() => document.querySelector('#main .overline')?.textContent) };
    // (rodada parcial com ONLY: recupera as demandas do T1 pelo título)
    if (!out.t1ids) out.t1ids = ['1440', '390'].map(w => readLog().filter(e => e.type === 'task' && e.agent === 'humano' && e.title === `Demanda: QA T1 ${w}px — demanda operação`).at(-1)?.id);
    // PA-7 (cancelar em andamento, com confirmação) na D15 — a D16 já tem G3 aprovado (servidor recusa: 409 "já concluída")
    await part('PA-7-cancelar', async () => { const c15 = codeOf(D15); await go(p, FIX, `#/demandas/${c15}`); p._clicks = [];
      const b = await p.$('#main [data-ctl="cancel"]'); await b.click(); p._clicks.push('Cancelar demanda'); const txt = await b.evaluate(e => e.textContent); await b.click(); p._clicks.push(`${txt}`); await sleep(1500);
      res['PA-7-cancelar'] = { clicks: p._clicks, ev: readLog().filter(e => e.type === 'control' && e.demand === D15).map(e => e.action), status: await p.evaluate(() => document.querySelector('#main .overline')?.textContent), msg: await p.evaluate(() => document.querySelector('#main .ok-msg, #main .fail')?.textContent) }; });
    // PA-5: cancelar antes do início (demanda do T1 a 390, já validada)
    const t1 = out.t1ids?.[1]; const c1 = t1 && codeOf(t1);
    if (c1) { await go(p, FIX, '#/painel'); p._clicks = [];
      await clk(p, `#main section[aria-labelledby="h-precisa"] a.ttl[href="#/demandas/${c1}"]`, null, `Painel › Precisa de você › ${c1}`);
      await clk(p, `#pc-${t1}`, null, 'Cancelar demanda'); await p.focus(`#cn-${t1}`); await p.keyboard.type('QA: cancelada no teste');
      await clk(p, `[data-precancel-confirm="${t1}"]`, null, 'Confirmar cancelamento'); await sleep(1000);
      res['PA-5'] = { clicks: p._clicks, ev: readLog().filter(e => e.type === 'control' && e.demand === t1).map(e => `${e.action}:${e.detail}`), status: await p.evaluate(() => document.querySelector('#main .overline')?.textContent) }; }
    // PA-3 normal: Iniciar a demanda do T1 a 1440 (respondida) com prioridade/rota/agente
    const t0 = out.t1ids?.[0]; const c0 = t0 && codeOf(t0);
    if (c0) { await go(p, FIX, '#/painel'); p._clicks = [];
      await clk(p, `#main section[aria-labelledby="h-precisa"] a[href="#/demandas/${c0}"]`, 'Iniciar', `Painel › Iniciar (${c0})`);
      await p.select(`#pr-${t0}`, 'alta'); await p.select(`#rt-${t0}`, 'direta'); await p.select(`#tg-${t0}`, 'frontend');
      await clk(p, `#start-${t0}`, null, 'Iniciar'); await sleep(1000);
      const s = readLog().filter(e => e.type === 'start' && e.demand === t0).at(-1);
      res['PA-3'] = { clicks: p._clicks, start: s && { priority: s.priority, route: s.route, target: s.target }, landed: await p.evaluate(() => ({ hash: location.hash, msg: document.querySelector('#main .ok-msg')?.textContent, tags: document.querySelector('#main .page-head .meta')?.textContent.replace(/\s+/g, ' ') })) }; }
    // PA-12: devolvida pelo revisor
    await go(p, FIX, `#/demandas/${cRej}`);
    res['PA-12-rejeitada'] = await p.evaluate(() => ({ status: document.querySelector('#main .overline')?.textContent, box: document.querySelector('#main .qbox')?.textContent.replace(/\s+/g, ' ').slice(0, 120) }));
    // PA-10: evidências e parecer completo de um gate (D14)
    await go(p, FIX, '#/painel'); p._clicks = [];
    await clk(p, '#main section[aria-labelledby="h-andamento"] a.ttl', 'D14', 'Painel › D14');
    await clk(p, '#sec-gates details summary', 'Evidências', 'Gates › Evidências');
    res['PA-10'] = { clicks: p._clicks, text: await p.evaluate(() => document.querySelector('#sec-gates details[open]')?.textContent.replace(/\s+/g, ' ').slice(0, 160)) };
    await p.screenshot({ path: '/shots/d13-demanda-gates-1440.png', fullPage: true });
    // PA-14: selos de modelo
    res['PA-14'] = await p.evaluate(() => ({ header: [...document.querySelectorAll('#main .mrow')].map(r => r.textContent.trim()).filter(t => /Modelos/.test(t)).slice(0, 1), chips: document.querySelectorAll('#main .mchip').length }));
    // PA-11: pipeline base e sua intervenção
    await go(p, FIX, '#/painel/squad-base');
    res['PA-11'] = await p.evaluate(() => ({ hash: location.hash, base: !!document.querySelector('#squad-base'), steps: document.querySelectorAll('#squad-base .tl li').length, btns: [...document.querySelectorAll('#squad-base [data-human]')].map(b => `${b.dataset.gate}|${b.dataset.demand}`) }));
    // PA-16, 17, 15, 23 e PA-18 (Squad)
    await go(p, FIX, '#/painel'); p._clicks = [];
    await clk(p, '#menu a[data-nav="auditoria"]', null, 'menu Auditoria');
    res['PA-15'] = await p.evaluate(() => ({ rows: document.querySelectorAll('#main tbody tr').length, total: document.querySelector('nav.seg a .n')?.textContent, chips: document.querySelectorAll('#main tbody .mchip').length }));
    await clk(p, '#main nav.seg a', 'Handoffs', 'aba Handoffs');
    res['PA-16'] = { clicks: p._clicks.slice(), n: await p.evaluate(() => document.querySelectorAll('#main details.card').length) };
    await go(p, FIX, '#/painel'); p._clicks.length = 0;
    await clk(p, '#menu a[data-nav="squad"]', null, 'menu Squad');
    res['PA-18'] = { clicks: p._clicks.slice(), cards: await p.evaluate(() => document.querySelectorAll('#main .agents-grid > section').length), count: await p.evaluate(() => document.querySelector('#c-ag').textContent) };
    // PA-20: links do produto (1440: lateral)
    res['PA-20'] = await p.evaluate(() => [...document.querySelectorAll('#project-links a')].map(a => ({ t: a.textContent, visible: !!a.getClientRects().length, target: a.target })));
    // PA-19: trocar produto (só 1 no project.json) e Grafana
    await go(p, FIX, '#/produto/grafana'); res['PA-19'] = await p.evaluate(() => ({ products: document.querySelectorAll('#obs-product option').length, iframe: document.querySelector('#main iframe')?.src, open: [...document.querySelectorAll('#main a[target=_blank]')].map(a => a.textContent.trim()) }));
    // CA-8: destinos das notificações do sino
    await clk(p, '#bell', null, 'sino');
    res['CA-8'] = await p.evaluate(() => [...document.querySelectorAll('#notif-panel a.notif')].map(a => `${a.getAttribute('href')} :: ${a.querySelector('b')?.textContent}`).slice(0, 12));
    R('PA-extra-1440', res);
    await p._ctx.close();
  });

  // ===== PA-20 a 390 + capturas de fixture (backlog, página com gate) + contador do título =====
  await scenario('extra-390', async () => {
    append([{ id: 'fx20bl000000', ts: iso(), agent: 'humano', type: 'task', to: 'orquestrador', title: 'Demanda: QA fixture G — backlog 2', detail: 'Outro item de backlog.', priority: 'alta', kind: 'produto', backlog: true }]);
    const cBl = codeOf('fx20bl000000');
    for (const w of [1440, 390]) {
      const p = await newPage(FIX, w);
      await go(p, FIX, `#/demandas/${cBl}`); await p.screenshot({ path: `/shots/d13-demanda-backlog-${w}.png`, fullPage: true });
      await go(p, FIX, '#/demandas/D14/gates'); await p.screenshot({ path: `/shots/d13-demanda-gate-${w}.png` });
      await go(p, FIX, '#/painel'); await p.screenshot({ path: `/shots/d13-painel-fixture-${w}.png`, fullPage: true });
      const cnt = await p.evaluate(() => ({ title: document.title, bell: document.querySelector('#bell-badge').hidden ? 0 : document.querySelector('#bell-badge').textContent, painel: document.querySelector('#c-painel').textContent,
        precisa: document.querySelectorAll('#main section[aria-labelledby="h-precisa"] li').length }));
      if (w === 390) {
        p._clicks = []; await clk(p, '#menu a[data-nav="produto"]', null, 'menu Produto');
        const l = await p.evaluate(() => [...document.querySelectorAll('#main a[target=_blank]')].map(a => a.textContent.trim()));
        R('PA-20-390', { clicks: p._clicks, links: l, sideLinksVisible: await p.evaluate(() => [...document.querySelectorAll('#project-links a')].some(a => a.getClientRects().length)) });
      }
      R(`contador-${w}`, cnt);
      await p._ctx.close();
    }
  });

  // ===== Achados pontuais: índice local da seção ativa, Registro aberto por rota, aviso de rota após alias =====
  await scenario('achados-1440', async () => {
    const p = await newPage(FIX, 1440);
    const r = {};
    for (const s of ['execucao', 'gates', 'validacao', 'registro']) {
      await go(p, FIX, `#/demandas/D16/${s}`);
      r[s] = await p.evaluate(() => ({ toc: document.querySelector('.toc a[aria-current]')?.textContent || null, regOpen: document.querySelector('#main details[id^="reg-"]')?.open, active: document.activeElement?.id || document.activeElement?.tagName }));
    }
    await go(p, FIX, '#/xyz'); const n1 = await p.evaluate(() => document.querySelector('#main .notice')?.textContent || '');
    await go(p, FIX, '#/painel#squad-base'); const n2 = await p.evaluate(() => ({ hash: location.hash, notice: document.querySelector('#main .notice')?.textContent || '' }));
    await go(p, FIX, '#/decisoes'); await go(p, FIX, '#/painel'); const n3 = await p.evaluate(() => document.querySelector('#main .notice')?.textContent || '');
    R('achados-1440', { secoes: r, aviso: { xyz: n1, depoisSquadBase: n2, depoisAliasEPainel: n3 } });
    await p._ctx.close();
  });

  // ===== Revalidação dos defeitos DEF-1..DEF-5 (commit 89e5834) + confirmação de cancelar no polling =====
  await scenario('revalidacao-1440', async () => {
    const r = {};
    // DEF-1: validação atrasada só para demanda ainda não iniciada. Controle positivo: fx22 atrasada, sem start.
    append([{ id: 'fx22late0000', ts: iso(Date.now() - 7 * 60000), agent: 'humano', type: 'task', to: 'orquestrador', title: 'Demanda: QA fixture H — atrasada sem início', detail: '', priority: 'normal', kind: 'operacao' }]);
    const started = ['fx17dddddddd', 'fx18late0000'].map(id => ({ id, code: codeOf(id), start: !!readLog().find(e => e.type === 'start' && e.demand === id) }));
    const cPos = codeOf('fx22late0000');
    const p = await newPage(FIX, 1440);
    await go(p, FIX, '#/painel'); await sleep(1500);
    const precisa = await p.evaluate(() => [...document.querySelectorAll('#main section[aria-labelledby="h-precisa"] li')].map(li => li.textContent.replace(/\s+/g, ' ').trim().slice(0, 110)));
    const bad = precisa.filter(t => started.some(s => s.code && new RegExp(`(^|\\D)${s.code}(?!\\d)`).test(t)) && /atrasada/i.test(t));
    const pos = precisa.filter(t => new RegExp(`(^|\\D)${cPos}(?!\\d)`).test(t) && /atrasada/i.test(t));
    r['DEF-1'] = { started, precisa, bad, positivo: { code: cPos, itens: pos }, ok: started.every(s => s.start) && !bad.length && pos.length === 1 };
    // DEF-2: índice local marca a seção e #/…/registro abre o Registro.
    const secs = {};
    for (const [s, t] of [['execucao', 'Execução'], ['gates', 'Gates'], ['validacao', 'Validação'], ['registro', 'Registro']]) {
      await go(p, FIX, `#/demandas/D16/${s}`); await sleep(300);
      secs[s] = await p.evaluate(() => ({ toc: document.querySelector('.toc a[aria-current="location"]')?.textContent || null, regOpen: document.querySelector('#main details[id^="reg-"]')?.open }));
      secs[s].ok = secs[s].toc === t && (s !== 'registro' || secs[s].regOpen === true);
    }
    await go(p, FIX, '#/demandas/D16'); const semSecao = await p.evaluate(() => document.querySelector('.toc a[aria-current]')?.textContent || null);
    r['DEF-2'] = { secs, semSecao, ok: Object.values(secs).every(x => x.ok) && semSecao === null };
    // DEF-4: aviso só no redirecionamento que o criou.
    await go(p, FIX, '#/xyz'); const n1 = await p.evaluate(() => document.querySelector('#main .notice')?.textContent || '');
    await go(p, FIX, '#/painel#squad-base'); const n2 = await p.evaluate(() => document.querySelector('#main .notice')?.textContent || '');
    await go(p, FIX, '#/xyz'); await go(p, FIX, '#/demandas'); const n3 = await p.evaluate(() => document.querySelector('#main .notice')?.textContent || '');
    await go(p, FIX, '#/abc'); const n4 = await p.evaluate(() => ({ hash: location.hash, notice: document.querySelector('#main .notice')?.textContent || '' }));
    r['DEF-4'] = { xyz: n1, depoisSquadBase: n2, depoisDemandas: n3, segundoInvalido: n4, ok: /não encontrada/.test(n1) && !n2 && !n3 && /não encontrada/.test(n4.notice) && n4.hash === '#/painel' };
    // DEF-5: cada ciclo de G2 da D14 mostra a decisão humana do seu ciclo.
    await go(p, FIX, '#/demandas/D14/gates'); await sleep(500);
    const cards = await p.evaluate(() => [...document.querySelectorAll('#sec-gates .card')].map(c => ({ head: c.querySelector('b')?.textContent.trim(), human: c.querySelector('.ok-msg')?.textContent.trim() || null })));
    const g2 = cards.filter(c => /^G2/.test(c.head || ''));
    const humans = readLog().filter(e => e.type === 'human' && e.gate === 'G2' && e.demand === D14).map(e => e.detail);
    r['DEF-5'] = { g2, humans, ok: g2.length >= 2 && /QA T2 toast/.test(g2[0].human || '') && /QA T10/.test(g2[1].human || '') && !/QA T10/.test(g2[0].human || '') };
    await p.screenshot({ path: '/shots/d13-demanda-gates-1440.png', fullPage: true });
    await p._ctx.close();
    // DEF-3: links de PR (reviewHtml) e issue do backlog com ↗ e "(abre em nova aba)" — dados reais, só leitura.
    const q = await newPage(REAL, 1440, { readOnly: true });
    const extOf = sel => q.evaluate(sel => [...document.querySelectorAll(sel)].filter(a => a.target === '_blank' && a.getClientRects().length).map(a => ({ t: a.textContent.trim().slice(0, 50),
      arrow: getComputedStyle(a, '::after').content.includes('↗') || a.textContent.includes('↗'), sr: /abre em nova aba/.test(a.textContent) })), sel);
    await go(q, REAL, '#/painel'); const entregues = await extOf('#main section[aria-labelledby="h-entregues"] a');
    await go(q, REAL, '#/demandas/D11'); const cabecalho = await extOf('#main .pass a, #main .page-head a');
    await go(q, REAL, '#/demandas?f=backlog'); const issues = await extOf('#main .bl-item a');
    const q2 = await newPage(FIX, 1440, { readOnly: true });
    // Issue do item de backlog: fixture de github-sync.json só na cópia temporária (fx20bl000000, backlog do extra-390).
    const GS = '/work/data/docs/squad/memory/github-sync.json'; const gs = JSON.parse(fs.readFileSync(GS, 'utf8'));
    gs.issues = gs.issues || {}; gs.issues.fx20bl000000 = { number: 920, url: 'https://github.com/x/y/issues/920', agent: 'orquestrador', status: 'Backlog', closed: false, kind: 'task' };
    fs.writeFileSync(GS, JSON.stringify(gs)); await sleep(1500);
    await go(q2, FIX, '#/demandas?f=backlog');
    const issuesFix = await q2.evaluate(() => [...document.querySelectorAll('#main .bl-item a[target=_blank]')].map(a => ({ t: a.textContent.trim(), arrow: getComputedStyle(a, '::after').content.includes('↗') || a.textContent.includes('↗'), sr: /abre em nova aba/.test(a.textContent) })));
    await go(q2, FIX, `#/demandas/${codeOf('fx19rej00000')}`);
    const devolvida = await q2.evaluate(() => [...document.querySelectorAll('#main .qbox a[target=_blank]')].map(a => ({ t: a.textContent.trim(), arrow: getComputedStyle(a, '::after').content.includes('↗') || a.textContent.includes('↗'), sr: /abre em nova aba/.test(a.textContent) })));
    await q2._ctx.close();
    const all = [...entregues, ...cabecalho, ...issues, ...issuesFix, ...devolvida];
    r['DEF-3'] = { entregues, cabecalho, issues, issuesFix, devolvida, posts: q._posts.length, ok: entregues.some(x => /PR #/.test(x.t)) && issuesFix.some(x => /issue #920/.test(x.t)) && all.every(x => x.arrow && x.sr) };
    await q._ctx.close();
    // Cancelar demanda: a confirmação sobrevive ao polling (evento novo no log força o redesenho).
    const c = await newPage(FIX, 1440);
    await go(c, FIX, '#/demandas/D14'); await sleep(800);
    await clk(c, '#main [data-ctl="cancel"]', 'Cancelar demanda', 'Cancelar demanda (D14)');
    const t0 = await c.evaluate(() => document.querySelector('#main [data-ctl="cancel"]')?.textContent.trim());
    append([{ id: `qapoll${Date.now()}`, ts: iso(), agent: 'qa', type: 'progress', title: 'QA: evento durante a confirmação de cancelar', demand: D16 }]);
    let polls = 0; c.on('request', x => { if (x.url().includes('/api/live')) polls++; });   // D14: polling por /api/live
    await sleep(8000);
    const t1 = await c.evaluate(() => ({ txt: document.querySelector('#main [data-ctl="cancel"]')?.textContent.trim(), confirm: document.querySelector('#main [data-ctl="cancel"]')?.dataset.confirm }));
    await go(c, FIX, '#/demandas/D16'); await go(c, FIX, '#/demandas/D14'); await sleep(500);
    const t2 = await c.evaluate(() => document.querySelector('#main [data-ctl="cancel"]')?.textContent.trim());
    r['cancelar-polling'] = { antes: t0, depoisPolling: t1, polls, depoisDeNavegar: t2, posts: c._posts.length, ok: t0 === 'Confirmar cancelamento' && t1.txt === 'Confirmar cancelamento' && polls >= 2 && t2 === 'Cancelar demanda' && c._posts.length === 0 };
    await c._ctx.close();
    R('revalidacao-1440', r);
  });

  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
