// D23 (6450aecde7f9) — F2a, CA-13 no navegador: o painel mostra D1–D24 congelados na lista, nas rotas
// #/demandas/<código> e nos links dos alertas, MESMO com o log REORDENADO (linhas dos `task` D7/D8 trocadas).
// Nada é injetado: o `codes` vem do próprio /api/state do servidor do worktree (sem interceptar requisições).
// Checklist: tests/ui/checklist-f2a-d23.md.
//
// Isolamento: servidor do WORKTREE em porta livre (lsof) com SQUAD_ROOT_DATA/SQUAD_LOG numa CÓPIA reordenada do log
// real (nunca o :7070 nem o log real), runner da conversa simulado:
//   S=<scratch>/qa-d23; python3 -c "import sys,pathlib,json; ..."   (cópia + troca D7↔D8; ver checklist)
//   SQUAD_ROOT_DATA=$S/ui-data SQUAD_LOG=$S/ui-data/docs/squad/memory/decisions.jsonl SQUAD_TRANSCRIPTS=$S/tr \
//     SQUAD_TESTENV_PROBE=0 SQUAD_TESTENV_SPAWN=0 SQUAD_CHAT_RUNNER=fake SQUAD_GH=/usr/bin/false \
//     python3 tools/squad/server.py --port <livre> &
//   docker run --rm --add-host=host.docker.internal:host-gateway -e PORT=<livre> -e NODE_PATH=/usr/src/app/node_modules -v "$PWD/tests/ui:/shots" \
//     zenika/alpine-chrome:with-puppeteer node /shots/d23-codigos.js
// Saída: tests/ui/d23-codigos-result.json + capturas tests/ui/d23-*.png. Código ≠ 0 se alguma verificação falhar.
const puppeteer = require('puppeteer');
const net = require('net');
const fs = require('fs');
const PORT = Number(process.env.PORT || 7391);
const BASE = `http://127.0.0.1:${PORT}/`;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = { results: {}, errors: [], console: [], requests: [] };
const R = (k, v) => { out.results[k] = v; console.error(`[${k}] ${v.ok ? 'PASS' : 'FAIL'} ${JSON.stringify(v).slice(0, 900)}`); };
const relay = port => new Promise(res => net.createServer(c => {
  const u = net.connect(port, 'host.docker.internal');
  c.pipe(u).pipe(c); u.on('error', () => c.destroy()); c.on('error', () => u.destroy());
}).listen(port, '127.0.0.1', res));

// tabela do contrato §4.3 (D1…D24)
const FROZEN = ['13e55010e3f5', '48b6ace91207', '62f458c8038b', '1cc732c62a2d', 'd91b7a8b31d9', 'c6f83b5bb5c7',
  '349e5b1bf818', 'e31bdfb73679', 'f2324e0f25de', '174084ec85d0', '642a73cb38e5', '1ac2708028fd',
  'efe387a35d71', '1e3d3c894630', '518f89f27ae8', '841f9a27e64a', 'e1d6eae16073', 'b72a6bd8caf3',
  '402e76f187f9', '41bdb8b49835', '71b7d9bc3313', 'b26da7851764', '6450aecde7f9', 'cf7a120591b0'];
const TABLE = Object.fromEntries(FROZEN.map((id, i) => [id, `D${i + 1}`]));
const norm = s => String(s || '').replace(/\s+/g, ' ').trim();
const short = t => norm(String(t || '').replace(/^Demanda:\s*/, ''));

(async () => {
  await relay(PORT);
  const b = await puppeteer.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'], executablePath: process.env.PUPPETEER_EXECUTABLE_PATH });
  const open = async (hash, w = 1440) => {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: 900, deviceScaleFactor: 1 });
    p.on('pageerror', e => out.errors.push(String(e).slice(0, 300)));
    p.on('console', m => { if (m.type() === 'error') out.console.push(m.text().slice(0, 200)); });
    p.on('request', r => { if (r.method() !== 'GET') out.requests.push(`${r.method()} ${r.url()}`); });
    await p.goto(BASE + hash, { waitUntil: 'domcontentloaded' });
    await p.waitForFunction(() => typeof state !== 'undefined' && state && state.log, { timeout: 90000 });
    await sleep(1200);
    return p;
  };

  // 0) log servido está REORDENADO (D8 antes de D7) e o servidor devolve os códigos congelados
  let p = await open('#/demandas?f=todas');
  const st = await p.evaluate(() => ({ codes: state.codes || null,
    order: state.log.filter(e => e.type === 'task' && e.agent === 'humano').map(e => e.id),
    titles: Object.fromEntries(state.log.filter(e => e.type === 'task' && e.agent === 'humano').map(e => [e.id, e.title])),
    usesCodeOf: typeof codeOf === 'function' }));
  const i7 = st.order.indexOf('349e5b1bf818'), i8 = st.order.indexOf('e31bdfb73679');
  R('log-reordenado', { ok: i8 >= 0 && i7 > i8, i7, i8 });
  const badApi = FROZEN.filter(id => !st.codes || st.codes[id] !== TABLE[id]);
  R('api-state-codes-D1-D24', { ok: !!st.codes && badApi.length === 0, bad: badApi });
  const inv = Object.fromEntries(Object.entries(st.codes || {}).map(([id, c]) => [c, id]));

  // 1) lista "Todas": o selo de código de cada cartão (elemento cujo texto é só "Dn") e o título no mesmo cartão
  await p.waitForFunction(() => [...document.querySelectorAll('body *')].some(e => e.children.length === 0 && e.textContent.trim() === 'D24'), { timeout: 30000 }).catch(() => null);
  await sleep(800);
  const cards = await p.evaluate(() => {
    const m = {};
    for (const e of document.querySelectorAll('body *')) {
      const t = e.textContent.trim();
      if (e.children.length === 0 && /^D\d+$/.test(t) && e.parentElement) {
        (m[t] = m[t] || []).push(e.parentElement.textContent.replace(/\s+/g, ' ').trim().slice(0, 200));
      }
    }
    return m;
  });
  const miss = [];
  let found = 0;
  for (const [id, c] of Object.entries(st.codes || {})) {
    const t = short(st.titles[id]).slice(0, 25).trim();
    if ((cards[c] || []).some(x => x.includes(t))) found++; else miss.push([c, t, (cards[c] || [])[0]]);
  }
  R('lista-todas', { ok: miss.length === 0 && found >= 24, found, total: Object.keys(st.codes || {}).length, miss: miss.slice(0, 8) });
  // posicional seria errado no log reordenado: o cartão "D7" não pode ter o título de e31bdfb73679 (D8 congelado)
  const wrongT = short(st.titles['e31bdfb73679']).slice(0, 25).trim();
  R('lista-sem-posicional', { ok: !(cards.D7 || []).some(x => x.includes(wrongT)) && (cards.D8 || []).some(x => x.includes(wrongT)), d7: (cards.D7 || [])[0], d8: (cards.D8 || [])[0] });
  await p.screenshot({ path: '/shots/d23-lista-reordenado-1440.png' });
  await p.close();

  // 2) rotas #/demandas/<código> abrem a demanda do código congelado
  const routes = {};
  for (const c of ['D7', 'D8', 'D9', 'D10', 'D24']) {
    p = await open(`#/demandas/${c}`);
    const h1 = norm(await p.evaluate(() => { const h = document.querySelector('main h1, h1'); return h ? h.innerText : ''; }));
    const want = short(st.titles[inv[c]]).slice(0, 30);
    routes[c] = { id: inv[c], expectedId: FROZEN[Number(c.slice(1)) - 1], h1: h1.slice(0, 90), ok: inv[c] === FROZEN[Number(c.slice(1)) - 1] && h1.includes(want) };
    if (c === 'D7' || c === 'D8') await p.screenshot({ path: `/shots/d23-rota-${c}-1440.png` });
    await p.close();
  }
  R('rotas', { ok: Object.values(routes).every(r => r.ok), routes });

  // 3) painel: links de alertas/cartões #/demandas/<código> com o título da demanda do código congelado
  p = await open('#/painel');
  const links = await p.evaluate(() => [...document.querySelectorAll('a[href^="#/demandas/D"]')]
    .map(a => ({ href: a.getAttribute('href'), text: a.innerText })));
  const badL = [];
  for (const l of links) {
    const c = (l.href.match(/#\/demandas\/(D\d+)/) || [])[1];
    const t = norm(l.text);
    if (c && t.startsWith(c) && t.length > c.length + 3) {
      const want = short(st.titles[inv[c]]).slice(0, 20);
      if (!t.includes(want)) badL.push([c, t.slice(0, 60), want]);
    }
  }
  R('painel-alertas', { ok: badL.length === 0, links: links.length, bad: badL.slice(0, 5) });
  await p.screenshot({ path: '/shots/d23-painel-reordenado-1440.png' });
  await p.close();

  R('sem-erros-e-sem-post', { ok: out.errors.length === 0 && out.requests.length === 0, errors: out.errors.slice(0, 5), requests: out.requests.slice(0, 5) });
  await b.close();
  const ok = Object.values(out.results).every(r => r.ok);
  fs.writeFileSync('/shots/d23-codigos-result.json', JSON.stringify({ ok, ...out }, null, 2));
  process.exit(ok ? 0 : 1);
})().catch(e => { console.error(e); process.exit(2); });
