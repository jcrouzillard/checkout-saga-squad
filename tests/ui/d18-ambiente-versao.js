// D18 (b72a6bd8caf3) — selo de ambiente e versão do Squad Control: CA15–CA19 (+ ressalvas QA-3 e "indeterminado" do G2).
// Checklist: tests/ui/checklist-ambiente-versao-d18.md. Servidor do WORKTREE numa porta livre, com cópia dos dados
// (nunca o :7070 nem o log real). Variações de estado (produtivo, desatualizado, indeterminado, dados do produtivo,
// servidor antigo 404) são produzidas interceptando /api/state e /api/instance no navegador — o servidor não muda.
//   S=<scratch>/qa-d18; mkdir -p $S/data/docs/squad $S/trans; cp -R docs/squad/memory docs/squad/gates $S/data/docs/squad/
//   SQUAD_ROOT_DATA=$S/data SQUAD_LOG=$S/data/docs/squad/memory/decisions.jsonl SQUAD_TRANSCRIPTS=$S/trans \
//     SQUAD_TESTENV_SPAWN=0 SQUAD_TESTENV_PROBE=0 SQUAD_GH=/usr/bin/false python3 tools/squad/server.py --port 7288 &
//   docker run --rm --add-host=host.docker.internal:host-gateway -e PORT=7288 -v "$PWD/tests/ui:/shots" \
//     -v "<scratch>/axe.min.js:/work/axe.min.js:ro" -w /home/pptruser ghcr.io/puppeteer/puppeteer:latest node /shots/d18-ambiente-versao.js
//   (em Mac arm64, mais rápido: --user root -e NODE_PATH=/usr/src/app/node_modules zenika/alpine-chrome:with-puppeteer —
//    a imagem do puppeteer é amd64 e roda emulada)
// Saída: tests/ui/d18-ambiente-versao-result.json e capturas tests/ui/d18-*.png.
const puppeteer = require('puppeteer');
const net = require('net');
const http = require('http');
const fs = require('fs');
const PORT = Number(process.env.PORT || 7288);
const BASE = `http://127.0.0.1:${PORT}/`;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = { results: {}, errors: [], axe: null };
const R = (k, v) => { out.results[k] = v; console.error(`[${v && v.ok === false ? 'FALHA' : 'ok'}] ${k} ${JSON.stringify(v).slice(0, 600)}`); };
const AXE = fs.existsSync('/work/axe.min.js') ? fs.readFileSync('/work/axe.min.js', 'utf8') : null;

function relay(port, host = 'host.docker.internal') {
  return new Promise(res => net.createServer(c => { const u = net.connect(port, host); c.pipe(u).pipe(c); u.on('error', () => c.destroy()); c.on('error', () => u.destroy()); })
    .listen(port, '127.0.0.1', res));
}
const getJson = path => new Promise((res, rej) => http.get({ host: '127.0.0.1', port: PORT, path, headers: { Host: `127.0.0.1:${PORT}` } }, r => {
  const b = []; r.on('data', d => b.push(d)); r.on('end', () => { try { res(JSON.parse(Buffer.concat(b).toString())); } catch (e) { rej(e); } });
}).on('error', rej));

// Variações do objeto `instance` (contrato §4) a partir do real.
const VARIANTS = {
  real: null,
  produtivo: i => { i.environment = { ...i.environment, name: 'produtivo', label: 'Produtivo', reason: 'cópia principal (develop), porta 7070', port: 7070, worktree: 'plankton', dataIsMain: true }; },
  dadosprod: i => { i.environment = { ...i.environment, dataIsMain: true }; },
  stale: i => { i.freshness = { ...i.freshness, state: 'desatualizado', headNow: 'abc1234', changedPaths: 2 }; },
  indet: i => { i.freshness = { ...i.freshness, state: 'indeterminado', headNow: null, changedPaths: null }; },
  dirty: i => { i.build = { ...i.build, dirty: true, display: i.build.display + ' +alterações' }; },
  old: 'old',
};

(async () => {
  await relay(PORT);
  const realState = await getJson('/api/state');
  const b = await puppeteer.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const newPage = async (w, h, { variant = 'real', theme = 'dark', route = '#/painel' } = {}) => {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: h, deviceScaleFactor: 1 });
    p._errs = []; p._console = []; p._instCalls = 0;
    p.on('pageerror', e => p._errs.push(String(e).slice(0, 300)));
    p.on('console', m => { if (m.type() === 'error') p._console.push(m.text().slice(0, 200)); });
    await p.evaluateOnNewDocument(t => { try { localStorage.setItem('sc-theme', t); } catch (e) { /* */ } }, theme);
    const mod = VARIANTS[variant];
    await p.setRequestInterception(true);
    p.on('request', async req => {
        const u = new URL(req.url());
        if (u.pathname === '/api/instance') p._instCalls++;
        if (!mod) return req.continue();
        if (u.pathname === '/api/instance') {
          if (mod === 'old') return req.respond({ status: 404, contentType: 'application/json', body: '{"error":"not found"}' });
          const i = await getJson('/api/instance'); mod(i);
          return req.respond({ status: 200, contentType: 'application/json; charset=utf-8', headers: { 'Cache-Control': 'no-store' }, body: JSON.stringify(i) });
        }
        if (u.pathname === '/api/state') {
          const s = JSON.parse(JSON.stringify(realState));
          if (mod === 'old') delete s.instance; else mod(s.instance);
          return req.respond({ status: 200, contentType: 'application/json; charset=utf-8', body: JSON.stringify(s) });
        }
        req.continue();
    });
    await p.goto(BASE + route, { waitUntil: 'networkidle2', timeout: 60000 });
    await p.waitForFunction(() => { const s = document.querySelector('#inst-side, #inst-c'); return s && s.dataset.env && s.dataset.env !== 'carregando'; }, { timeout: 15000, polling: 200 }).catch(() => null);
    await sleep(600);
    return p;
  };
  const shot = (p, name, full = false) => p.screenshot({ path: `/shots/d18-${name}.png`, fullPage: full });
  const info = p => p.evaluate(() => {
    const vis = el => { if (!el) return null; const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height), shown: cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0,
        inView: r.top >= -1 && r.left >= -1 && r.bottom <= innerHeight + 1 && r.right <= innerWidth + 1 }; };
    const side = document.querySelector('#inst-side'), c = document.querySelector('#inst-c');
    const act = [side, c].find(e => e && e.getClientRects().length && getComputedStyle(e).display !== 'none');
    return { W: innerWidth, H: innerHeight, scrollY: Math.round(scrollY), docH: document.scrollingElement.scrollHeight, scrollW: document.scrollingElement.scrollWidth,
      title: document.title, side: vis(side), c: vis(c), cm: vis(c?.querySelector('.inst-cm')), bell: vis(document.querySelector('#bell')),
      env: act?.dataset.env, text: act?.innerText.replace(/\s+/g, ' ').trim(), aria: act?.getAttribute('aria-label'), titleAttr: act?.title, expanded: act?.getAttribute('aria-expanded'),
      sideText: side?.innerText.replace(/\s+/g, ' ').trim() };
  });
  // página longa: a primeira rota cuja altura passa de 1,5 × a janela
  const longRoute = async (p, h) => { for (const r of ['#/auditoria', '#/squad', '#/execucoes', '#/painel', '#/demandas']) {
    await p.evaluate(x => { location.hash = x; }, r); await sleep(1200);
    if (await p.evaluate(hh => document.scrollingElement.scrollHeight > hh * 1.5, h)) return r; } return null; };
  const scrollEnd = async p => { await p.evaluate(() => window.scrollTo(0, document.scrollingElement.scrollHeight)); await sleep(500); };
  const overlap = (a, b) => a && b && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  const axe = async (p, label) => {
    if (!AXE) return { skipped: 'axe.min.js indisponível no container' };
    await p.evaluate(AXE);
    const r = await p.evaluate(async () => {
      const inc = ['#inst-side', '#inst-c', '#inst-panel:not([hidden])'].filter(s => document.querySelector(s) && document.querySelector(s).getClientRects().length);
      const res = await window.axe.run({ include: inc.map(s => [s]) }, { resultTypes: ['violations'] });
      return res.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.map(n => n.target.join(' ') + ' — ' + (n.any[0]?.message || '')).slice(0, 4) }));
    });
    return { label, violations: r };
  };
  const CAMPOS = ['Tag de release', 'Versão do pom', 'Commit', 'Branch', 'Worktree', 'Porta', 'Origem dos dados', 'Subiu em', 'HEAD atual', 'Motivo'];
  const real = realState.instance;
  const expAria = `Ambiente: ${real.environment.label}. Versão ${real.build.display}`;
  out.axe = [];

  // ===== CA15: 1440×900 e 1280×720, página longa rolada até o fim, nos dois temas
  for (const [w, h] of [[1440, 900], [1280, 720]]) for (const theme of ['dark', 'light']) {
    const p = await newPage(w, h, { theme, route: '#/demandas' });
    const rota = await longRoute(p, h);
    const top = await info(p);
    await scrollEnd(p);
    const end = await info(p);
    await shot(p, `${w}-fim-${theme === 'dark' ? 'escuro' : 'claro'}`);
    R(`CA15-${w}x${h}-${theme}`, { ok: end.docH > h * 1.5 && top.side.shown && top.side.inView && end.side.shown && end.side.inView && end.scrollY > 0 && /TESTE|Teste/i.test(end.sideText) && end.sideText.includes(real.build.display.split(' · ')[2]),
      rota, docH: end.docH, scrollY: end.scrollY, sideTop: top.side, sideEnd: end.side, sideText: end.sideText, compactoOculto: !end.c.shown });
    out.axe.push(await axe(p, `${w}-${theme}-fechado`));
    await p.close();
  }

  // ===== 800 e 700 (compacto no cabeçalho; commit oculto 600–780)
  for (const w of [800, 700]) {
    const p = await newPage(w, 900);
    const i = await info(p);
    await shot(p, `${w}-cabecalho`);
    const inHdr = await p.evaluate(() => !!document.querySelector('#hdr #inst-c'));
    R(`largura-${w}`, { ok: i.c.shown && i.c.inView && inHdr && !i.side.shown && (w === 800 ? !!i.cm?.shown : !i.cm?.shown) && i.aria.includes(real.build.commit) && i.scrollW <= i.W && i.bell.inView,
      c: i.c, commitVisivel: !!i.cm?.shown, text: i.text, aria: i.aria, scrollW: i.scrollW, bell: i.bell });
    await p.close();
  }

  // ===== CA16: 390 — sem rolagem horizontal, sino visível, selo fixo não cobre toasts nem o último botão
  for (const theme of ['dark', 'light']) {
    const p = await newPage(390, 844, { theme, route: '#/demandas' });
    const rota = await longRoute(p, 844);
    const i0 = await info(p);
    await p.evaluate(() => { for (let k = 0; k < 3; k++) toast({ id: 'qa' + k, level: 'bloqueio', title: `QA toast ${k}`, body: 'teste de sobreposição', href: '#/painel' }); });
    await sleep(400);
    const toasts = await p.evaluate(() => [...document.querySelectorAll('#toasts .toast')].map(t => { const r = t.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }));
    await shot(p, `390-toasts-${theme === 'dark' ? 'escuro' : 'claro'}`);
    await p.evaluate(() => document.querySelectorAll('#toasts .toast').forEach(t => t.remove()));
    await scrollEnd(p);
    const i1 = await info(p);
    // o controle mais baixo VISÍVEL na janela com cada página rolada até o fim não pode ficar sob o selo fixo
    const lastCtl = () => p.evaluate(() => { const bs = [...document.querySelectorAll('#main button, #main a, #main summary, #main input, #main select, #main [tabindex="0"], .frame button')]
      .filter(e => e.getClientRects().length && !e.closest('.inst, #hdr, #toasts'));
      const inWin = bs.filter(e => { const r = e.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight && r.width > 0; });
      const e = inWin.sort((a, b) => a.getBoundingClientRect().bottom - b.getBoundingClientRect().bottom).pop(); if (!e) return null; const r = e.getBoundingClientRect();
      return { route: location.hash, label: (e.innerText || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 40), x: r.left, y: r.top, w: r.width, h: r.height, H: innerHeight }; });
    const lasts = [];
    for (const r of ['#/demandas', '#/painel', '#/execucoes', '#/squad', '#/auditoria']) {
      await p.evaluate(h => { location.hash = h; }, r); await sleep(1200); await scrollEnd(p);
      const l = await lastCtl(); if (l) { l.sobOSelo = !!overlap(l, (await info(p)).c); lasts.push(l); } }
    const last = lasts.length ? lasts : null;
    // outras rotas: sem rolagem horizontal
    const hs = {};
    for (const r of ['#/painel', '#/squad', '#/auditoria', '#/execucoes']) { await p.evaluate(h => { location.hash = h; }, r); await sleep(900); const x = await info(p); hs[r] = x.scrollW <= x.W; }
    await shot(p, `390-fim-${theme === 'dark' ? 'escuro' : 'claro'}`);
    const cov = toasts.filter(t => overlap(t, i1.c));
    R(`CA16-390-${theme}`, { ok: i0.scrollW <= 390 && i0.bell.inView && i1.bell.shown && i0.c.shown && i0.c.inView && i1.c.inView && cov.length === 0 && toasts.length > 0 && !!last && last.every(l => !l.sobOSelo) && Object.values(hs).every(Boolean),
      rota, scrollW: i0.scrollW, bell: i0.bell, selo: i1.c, text: i0.text, toasts, toastsCobertos: cov.length, ultimoBotao: last, semRolagemH: hs, noCabecalho: await p.evaluate(() => !!document.querySelector('#hdr #inst-c')) });
    out.axe.push(await axe(p, `390-${theme}-fechado`));
    await p.close();
  }

  // ===== CA17: teclado (Enter/Esc) e foco devolvido, campos do detalhe e aria-label — 1440 e 390
  for (const [w, h, sel] of [[1440, 900, '#inst-side'], [390, 844, '#inst-c']]) for (const theme of ['dark', 'light']) {
    const p = await newPage(w, h, { theme });
    await p.focus(sel);
    await p.keyboard.press('Enter'); await sleep(400);
    const opened = await p.evaluate(s => ({ hidden: document.querySelector('#inst-panel').hidden, exp: document.querySelector(s).getAttribute('aria-expanded'), role: document.querySelector('#inst-panel').getAttribute('role'),
      focusIn: document.querySelector('#inst-panel').contains(document.activeElement), dts: [...document.querySelectorAll('#inst-panel dt')].map(d => d.textContent),
      btns: [...document.querySelectorAll('#inst-panel button')].map(b => b.textContent), inView: (() => { const r = document.querySelector('#inst-panel').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight + 1 && r.left >= 0 && r.right <= innerWidth + 1; })() }), sel);
    await shot(p, `${w}-detalhe-${theme === 'dark' ? 'escuro' : 'claro'}`);
    out.axe.push(await axe(p, `${w}-${theme}-detalhe-aberto`));
    await p.keyboard.press('Escape'); await sleep(300);
    const closed = await p.evaluate(s => ({ hidden: document.querySelector('#inst-panel').hidden, exp: document.querySelector(s).getAttribute('aria-expanded'), focusBack: document.activeElement === document.querySelector(s) }), sel);
    // clique fora fecha
    await p.keyboard.press('Enter'); await sleep(300);
    const pr = await p.evaluate(() => { const r = document.querySelector('#inst-panel').getBoundingClientRect(); return { l: r.left, r: r.right, t: r.top, b: r.bottom }; });
    await p.mouse.click(pr.r + 6 < w ? Math.round(pr.r + 6) : Math.max(2, Math.round(pr.l - 6)), Math.round((pr.t + pr.b) / 2)); await sleep(300);
    const outside = await p.evaluate(() => document.querySelector('#inst-panel').hidden);
    // botão Fechar devolve o foco
    await p.focus(sel); await p.keyboard.press('Enter'); await sleep(300);
    await p.evaluate(() => document.querySelector('[data-inst-close]').focus()); await p.keyboard.press('Enter'); await sleep(300);
    const fechar = await p.evaluate(s => ({ hidden: document.querySelector('#inst-panel').hidden, focusBack: document.activeElement === document.querySelector(s) }), sel);
    const i = await info(p);
    const faltam = CAMPOS.filter(c => !opened.dts.includes(c));
    R(`CA17-${w}-${theme}`, { ok: !opened.hidden && opened.exp === 'true' && opened.role === 'dialog' && opened.focusIn && faltam.length === 0 && opened.btns.includes('Copiar') && opened.inView && closed.hidden && closed.exp === 'false' && closed.focusBack && outside && fechar.hidden && fechar.focusBack && i.aria.startsWith(expAria) && i.titleAttr.includes(real.build.display),
      opened, closed, cliqueFora: outside, fechar, faltam, aria: i.aria, esperado: expAria, titleAttr: i.titleAttr });
    await p.close();
  }

  // ===== Estados: produtivo, dados do produtivo, desatualizado, indeterminado, dirty (1440 e 390) + título da aba
  for (const v of ['produtivo', 'dadosprod', 'stale', 'indet', 'dirty']) for (const [w, h] of [[1440, 900], [390, 844]]) {
    const p = await newPage(w, h, { variant: v, theme: v === 'stale' ? 'light' : 'dark' });
    const i = await info(p);
    await shot(p, `estado-${v}-${w}`);
    const pan = await p.evaluate(sel => { document.querySelector(sel).click(); return new Promise(r => setTimeout(() => r(document.querySelector('#inst-panel').innerText), 300)); }, w > 900 ? '#inst-side' : '#inst-c');
    const res = { env: i.env, text: i.text, aria: i.aria, title: i.title, painel: pan.replace(/\s+/g, ' ').slice(0, 400), errs: p._errs };
    if (v === 'produtivo') res.ok = i.env === 'produtivo' && /PRODUTIVO|Produtivo/.test(i.text) && !/^\[/.test(i.title) && i.aria.startsWith('Ambiente: Produtivo.');
    if (v === 'dadosprod') res.ok = (w < 900 || i.sideText.includes('dados do produtivo')) && /dados do produtivo/i.test(i.aria + pan) && i.title.startsWith('[TESTE] ');
    if (v === 'stale') res.ok = (w < 900 ? i.text.includes('⚠') : i.sideText.includes('Desatualizado: o código mudou desde a subida. Reinicie (make squad).')) && i.aria.includes('Desatualizado, reinicie') && /reinicie/i.test(pan);
    if (v === 'indet') { res.ok = (w < 900 || i.sideText.includes('Não foi possível verificar a versão')) && /Não foi possível verificar a versão/.test(pan);
      res.ariaDizIndeterminado = /Não foi possível verificar a versão/.test(i.aria); }
    if (v === 'dirty') res.ok = i.aria.includes('+alterações') && /alterações locais/i.test(pan) && (w < 900 || i.sideText.includes('alterações locais não commitadas'));
    res.ok = res.ok && p._errs.length === 0;
    R(`estado-${v}-${w}`, res);
    await p.close();
  }

  // ===== CA19: servidor antigo — /api/instance 404 e /api/state sem instance
  for (const [w, h] of [[1440, 900], [390, 844]]) for (const theme of ['dark', 'light']) {
    const p = await newPage(w, h, { variant: 'old', theme });
    await sleep(800);
    const i = await info(p);
    await shot(p, `antigo-404-${w}-${theme === 'dark' ? 'escuro' : 'claro'}`);
    const cons = p._console.filter(m => !/Failed to load resource/.test(m));
    R(`CA19-${w}-${theme}`, { ok: i.env === 'desconhecido' && /reinicie/i.test(i.aria) && (w < 900 || /reinicie/i.test(i.sideText)) && i.title.startsWith('[?] ') && p._errs.length === 0 && cons.length === 0 && p._instCalls >= 1,
      env: i.env, text: i.text, sideText: i.sideText, aria: i.aria, title: i.title, pageErrors: p._errs, consoleErros: p._console, chamadasInstance: p._instCalls });
    out.axe.push(await axe(p, `antigo-${w}-${theme}`));
    await p.close();
  }

  // ===== Título da aba: [TESTE] no real e mantido ao navegar; sem rede extra no ciclo de 1,5 s
  {
    const p = await newPage(1440, 900, { variant: 'real' });
    const titles = [];
    for (const r of ['#/painel', '#/demandas', '#/squad', '#/auditoria']) { await p.evaluate(h => { location.hash = h; }, r); await sleep(900); titles.push(await p.evaluate(() => document.title)); }
    const c0 = p._instCalls; await sleep(6000); const c1 = p._instCalls;
    R('titulo-TESTE', { ok: titles.every(t => t.startsWith('[TESTE] ') && !t.startsWith('[TESTE] [TESTE]')), titles, chamadasInstanceEm6s: c1 - c0 });
    R('carga-sem-instance-no-ciclo', { ok: c1 - c0 === 0, chamadasInstanceEm6s: c1 - c0 });
    await p.close();
  }

  await Promise.race([b.close(), sleep(5000)]);
  out.axeViolacoes = out.axe.filter(a => a.violations && a.violations.length);
  out.falhas = Object.entries(out.results).filter(([, v]) => v.ok === false).map(([k]) => k);
  fs.writeFileSync('/shots/d18-ambiente-versao-result.json', JSON.stringify(out, null, 2));
  console.error(`FALHAS: ${out.falhas.join(', ') || 'nenhuma'}; axe com violações: ${out.axeViolacoes.map(a => a.label).join(', ') || 'nenhuma'}`);
  process.exit(out.falhas.length || out.axeViolacoes.length ? 1 : 0);   // não espera o fechamento lento do Chromium
})().catch(e => { console.error(e); process.exit(1); });
