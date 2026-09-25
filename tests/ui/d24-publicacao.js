// D24 (QA, cf7a120591b0) — publicação do Squad Control no navegador: CA-8 (diálogo), CA-11 (avisos e contagem),
// CA-12 (botão/selo), CA-13 (recarga sem rascunho × rascunho preservado), CA-14 (conversa interrompida + Reenviar) e,
// com REAL_PORT, o CA-1/CA-13 de ponta a ponta contra um SUPERVISOR REAL num sandbox (repositório temporário).
// Base: roteiro do Frontend (scratchpad/d24-front/d24-ui.js). Checklist: tests/ui/checklist-publicacao-d24.md.
// Parte A (mocks): servidor do WORKTREE numa porta livre com dados copiados; os estados do publicador são simulados por
// um invólucro de fetch (sessionStorage "__mock"). A mensagem interrompida (CID) é REAL: SIGTERM num server.py com
// SQUAD_SUPERVISED=1 no meio de um turno FXD20 (ver roteiro no checklist).
// Parte B (REAL_PORT + REAL_TITLE): página aberta no supervisor do sandbox; o roteiro grava $OUT/d24-real-ready e o
// driver faz o merge que muda o <title>; espera a recarga sozinha na mesma rota e o aviso "atualizado".
//   docker run --rm --user root -e NODE_PATH=/usr/src/app/node_modules --add-host=host.docker.internal:host-gateway \
//     -e PORT=<p> -e CID=<cid> [-e REAL_PORT=<q> -e REAL_TITLE=<t>] -e OUT=/out -v "<saida>:/out" \
//     -v "$PWD/tests/ui:/shots:ro" zenika/alpine-chrome:with-puppeteer node /shots/d24-publicacao.js
// Nunca a 7070 nem o log real.
const puppeteer = require('puppeteer');
const net = require('net');
const fs = require('fs');
const PORT = Number(process.env.PORT || 7494);
const BASE = `http://127.0.0.1:${PORT}/`;
const CID = process.env.CID;
const OUT = process.env.OUT || '/out';
const REAL_PORT = Number(process.env.REAL_PORT || 0), REAL_TITLE = process.env.REAL_TITLE || '';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = { results: {}, errors: [] };
const R = (k, ok, v) => { out.results[k] = { ok, ...v }; console.error(`[${ok ? 'ok' : 'FALHA'}] ${k} ${JSON.stringify(v).slice(0, 400)}`); };
const iso = s => new Date(Date.now() + s * 1000).toISOString().replace(/\.\d+Z$/, 'Z');
const C1 = 'a'.repeat(40), C2 = 'b'.repeat(40), C3 = 'c'.repeat(40), C4 = 'd'.repeat(40);

const MOCK_JS = `(() => {
  const of = window.fetch.bind(window);
  const M = () => { try { return JSON.parse(sessionStorage.getItem("__mock") || "{}"); } catch (e) { return {}; } };
  const J = (o, st = 200) => new Response(JSON.stringify(o), { status: st, headers: { "Content-Type": "application/json" } });
  const patch = (i, p) => { if (!i || !p) return; if (p.env) i.environment = { ...i.environment, name: p.env, label: p.env === "produtivo" ? "Produtivo" : "Teste" };
    if (p.commit) i.build = { ...i.build, commitFull: p.commit, commit: p.commit.slice(0, 7), display: "v1.0.0 · 1.1.0-SNAPSHOT · " + p.commit.slice(0, 7), dirty: false };
    i.freshness = { ...i.freshness, state: "atual", ...(p.fresh || {}) }; };
  window.fetch = async (u, opt = {}) => {
    const m = M(), path = String(u).replace(/^https?:\\/\\/[^/]+/, "");
    if (m.down && path.startsWith("/api/")) throw new TypeError("Failed to fetch");
    if (path.startsWith("/api/squad-control/publish")) {
      const posts = JSON.parse(sessionStorage.getItem("__posts") || "[]"); posts.push(JSON.parse(opt.body || "{}")); sessionStorage.setItem("__posts", JSON.stringify(posts));
      const rs = (m.postSeq || [])[posts.length - 1] || { status: 202, body: { requestId: "r" } }; return J(rs.body, rs.status); }
    if (path.startsWith("/api/squad-control/publication") && m.info) return J(m.info);
    const r = await of(u, opt);
    if (path.startsWith("/api/live") && "pub" in m && r.ok) { const j = await r.json(); j.publication = m.pub; return J(j); }
    if (path.startsWith("/api/instance") && m.inst && r.ok) { const j = await r.json(); patch(j, m.inst); return J(j); }
    if (path.startsWith("/api/state") && m.inst && r.ok) { const j = await r.json(); patch(j.instance, m.inst); return J(j); }
    return r;
  };
})();`;

function relay(port, host = 'host.docker.internal') {
  return new Promise(res => net.createServer(c => { const u = net.connect(port, host); c.pipe(u).pipe(c); u.on('error', () => c.destroy()); c.on('error', () => u.destroy()); }).listen(port, '127.0.0.1', res));
}
const setMock = (p, m) => p.evaluate(m => sessionStorage.setItem('__mock', JSON.stringify(m)), m);
const text = (p, sel) => p.$eval(sel, e => e.innerText).catch(() => null);
const barText = p => p.evaluate(() => { const b = document.getElementById('pub-bar'); return b && !b.hidden ? b.innerText : ''; });
async function openPanel(p) {
  await p.evaluate(() => { if (INST.open) instClose(false); });
  const sel = await p.evaluate(() => { const s = document.getElementById('inst-side'), c = document.getElementById('inst-c'); return s && s.getClientRects().length ? '#inst-side' : '#inst-c'; });
  await p.click(sel); await sleep(700);
}
const PUB0 = { state: 'no-ar', target: null, deadline: null, trigger: null, lastResult: null, mode: 'principal' };
const INFO0 = { supervised: true, state: 'no-ar', server: { display: 'v1.0.0 · 1.1.0-SNAPSHOT · aaaaaaa' }, target: null, deadline: null, trigger: null, busy: null, lastResult: null, failedCommit: null, canPublish: true, reason: null };

(async () => {
  await relay(PORT);
  const b = await puppeteer.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'], executablePath: process.env.PUPPETEER_EXECUTABLE_PATH });
  const p = await b.newPage();
  p.on('pageerror', e => out.errors.push(String(e)));
  p.on('console', m => { if (m.type() === 'error' && !/Failed to fetch|ERR_|404/.test(m.text())) out.errors.push('console: ' + m.text()); });
  await p.setViewport({ width: 1440, height: 900 });
  await p.evaluateOnNewDocument(MOCK_JS);
  await p.goto(BASE + '#/painel', { waitUntil: 'domcontentloaded' });
  await setMock(p, { inst: { env: 'produtivo', commit: C1 }, pub: PUB0, info: INFO0,
    postSeq: [{ status: 409, body: { code: 'resposta_em_andamento', busy: { conversa: 'c-x', turn: 1 } } }, { status: 409, body: { code: 'resposta_em_andamento', busy: { conversa: 'c-x', turn: 1 } } }, { status: 202, body: { requestId: 'r1' } },
      { status: 409, body: { code: 'resposta_em_andamento' } }, { status: 202, body: { requestId: 'r2' } }] });
  await p.reload({ waitUntil: 'domcontentloaded' }); await sleep(3500);
  await p.evaluate(() => { window.__marker = 1; });

  // --- CA-12: botão no detalhe do selo (produtivo, supervisor ok)
  await openPanel(p);
  let v = await p.evaluate(() => { const bt = document.querySelector('#inst-panel [data-pub-btn]'); return { btn: bt && bt.innerText, dis: bt && bt.disabled, st: document.getElementById('pub-state')?.innerText, title: bt?.title }; });
  R('CA12-botao-produtivo', v.btn === 'Publicar Squad Control' && v.dis === false && /no ar/.test(v.st || '') && /5 s/.test(v.title || ''), v);
  await p.screenshot({ path: `${OUT}/d24-botao-1440.png` });
  // --- §7.2: 409 resposta_em_andamento → diálogo; Esc fecha só o diálogo
  await p.click('#inst-panel [data-pub-btn]'); await sleep(600);
  v = await p.evaluate(() => { const d = document.getElementById('pub-dlg'); return { open: !!d?.open, h: d?.querySelector('h2')?.innerText, btns: [...(d?.querySelectorAll('button') || [])].map(x => x.innerText), focus: document.activeElement?.innerText, modal: d?.matches(':modal') }; });
  R('CA8-dialogo-confirmacao', v.open && v.modal && v.btns.join('|') === 'Publicar agora|Publicar quando a resposta terminar|Cancelar' && v.focus === 'Publicar quando a resposta terminar', v);
  await p.screenshot({ path: `${OUT}/d24-dialogo-1440.png` });
  await p.keyboard.press('Escape'); await sleep(400);
  v = await p.evaluate(() => ({ open: document.getElementById('pub-dlg').open, panel: INST.open, chat: !document.getElementById('chat').hidden, posts: JSON.parse(sessionStorage.getItem('__posts') || '[]') }));
  R('esc-fecha-so-dialogo', !v.open && v.panel && !v.chat && v.posts.length === 1 && v.posts[0].when === 'now' && !v.posts[0].confirm, v);
  await p.click('#inst-panel [data-pub-btn]'); await sleep(600);
  await p.click('#pub-dlg [data-pub-dlg="now"]'); await sleep(900);
  v = await p.evaluate(() => ({ posts: JSON.parse(sessionStorage.getItem('__posts') || '[]'), msg: document.querySelector('#inst-panel .pub-msg')?.innerText }));
  R('CA8-publicar-agora-confirm', JSON.stringify(v.posts[2]) === '{"when":"now","confirm":true}' && /Publicação pedida/.test(v.msg || ''), v);
  await p.click('#inst-panel [data-pub-btn]'); await sleep(600);
  await p.click('#pub-dlg [data-pub-dlg="safe"]'); await sleep(900);
  v = await p.evaluate(() => ({ posts: JSON.parse(sessionStorage.getItem('__posts') || '[]'), msg: document.querySelector('#inst-panel .pub-msg')?.innerText }));
  R('CA8-quando-terminar', JSON.stringify(v.posts[4]) === '{"when":"safe"}' && /quando a resposta/.test(v.msg || ''), v);

  // --- CA-12: sem supervisor → desabilitado com motivo; desatualizado vira "Desatualizado."
  await setMock(p, { inst: { env: 'produtivo', commit: C1, fresh: { state: 'desatualizado', changedPaths: 2 } }, pub: null, info: { ...INFO0, supervised: false, state: null, canPublish: false, reason: 'sem_supervisor' } });
  await p.evaluate(() => instFetch()); await sleep(2500); await openPanel(p);
  v = await p.evaluate(() => { const bt = document.querySelector('#inst-panel [data-pub-btn]'); return { dis: bt?.disabled, why: document.getElementById('pub-why')?.innerText, selo: document.getElementById('inst-side')?.innerText }; });
  R('CA12-sem-supervisor', v.dis === true && /Sem publicador: rode make squad/.test(v.why || '') && /Reinicie \(make squad\)/.test(v.selo || ''), v);
  await p.screenshot({ path: `${OUT}/d24-sem-supervisor-1440.png` });
  // --- teste: sem botão
  await setMock(p, { inst: { env: 'teste', commit: C1 }, pub: null, info: { ...INFO0, supervised: false, canPublish: false, reason: 'sem_supervisor' } });
  await p.evaluate(() => instFetch()); await sleep(1200); await openPanel(p);
  v = await p.evaluate(() => ({ btn: !!document.querySelector('#inst-panel [data-pub-btn]'), sec: document.querySelector('#inst-panel .pub-sec')?.innerText }));
  R('CA12-so-produtivo', !v.btn && /Disponível só no produtivo/.test(v.sec || ''), v);
  await p.evaluate(() => instClose(false));

  // --- CA-11: contagem regressiva (automático) e "publicando" no selo
  await setMock(p, { inst: { env: 'produtivo', commit: C1, fresh: { state: 'desatualizado', changedPaths: 1 } }, pub: { ...PUB0, state: 'aguardando-ponto-seguro', target: { commit: C2, display: null }, deadline: iso(20), trigger: 'auto' }, info: { ...INFO0, state: 'aguardando-ponto-seguro', canPublish: false, reason: 'publicacao_em_andamento' } });
  await p.evaluate(() => instFetch()); await sleep(2200);
  const t1 = await barText(p); await sleep(2100); const t2 = await barText(p);
  const n1 = +(t1.match(/em (\d+) s/) || [])[1], n2 = +(t2.match(/em (\d+) s/) || [])[1];
  const selo = await text(p, '#inst-side');
  R('CA11-contagem', /Squad Control será atualizado para bbbbbbb em \d+ s\. A resposta em andamento será interrompida\./.test(t1) && n1 > n2 && n1 <= 20 && /Desatualizado, publicando…/.test(selo || ''), { t1, t2, selo });
  await p.screenshot({ path: `${OUT}/d24-contagem-1440.png` });
  await p.setViewport({ width: 390, height: 844 }); await sleep(600);
  await p.screenshot({ path: `${OUT}/d24-contagem-390.png` });
  await p.evaluate(() => { try { localStorage.setItem('sc-theme', 'dark'); } catch (e) {} applyTheme(); }); await sleep(400);
  await p.screenshot({ path: `${OUT}/d24-contagem-390-escuro.png` });
  await p.setViewport({ width: 1440, height: 900 }); await sleep(400);
  await p.screenshot({ path: `${OUT}/d24-contagem-1440-escuro.png` });
  await p.evaluate(() => { try { localStorage.setItem('sc-theme', 'light'); } catch (e) {} applyTheme(); });
  // botão "quando terminar" esperando
  await setMock(p, { inst: { env: 'produtivo', commit: C1 }, pub: { ...PUB0, state: 'aguardando-ponto-seguro', target: { commit: C2 }, deadline: iso(600), trigger: 'botao' }, info: INFO0 });
  await sleep(2200); v = await barText(p);
  R('CA11-aguardando-safe', /aguardando a resposta da conversa terminar/.test(v) && !/será atualizado/.test(v), { v });
  // verificando
  await setMock(p, { inst: { env: 'produtivo', commit: C1 }, pub: { ...PUB0, state: 'verificando', target: { commit: C2 }, trigger: 'auto' }, info: INFO0 });
  await sleep(2200); v = await barText(p);
  R('CA11-verificando', /Publicando bbbbbbb…/.test(v), { v });

  // --- queda: "Reiniciando…" no lugar do erro genérico (também após 15 s)
  await setMock(p, { inst: { env: 'produtivo', commit: C1 }, pub: { ...PUB0, state: 'verificando', target: { commit: C2 }, trigger: 'auto' }, info: INFO0, down: true });
  await sleep(3000); const d1 = await barText(p);
  await sleep(15000);
  v = await p.evaluate(() => ({ srv: document.getElementById('srv-down').hidden, live: document.getElementById('live-ind')?.innerText }));
  const d2 = await barText(p);
  R('queda-reiniciando', /Reiniciando o Squad Control…/.test(d1) && /Reiniciando/.test(d2) && v.srv === true, { d1, d2, ...v });
  await p.screenshot({ path: `${OUT}/d24-reiniciando-1440.png` });

  // --- CA-13 + CA-11: volta com commit novo, sem rascunho → recarrega na mesma rota e mostra "atualizado"
  await p.evaluate(() => { location.hash = '#/demandas'; }); await sleep(300);
  await setMock(p, { inst: { env: 'produtivo', commit: C2 }, pub: { ...PUB0, lastResult: { type: 'squad-updated', commit: C2, display: 'v1.0.0 · 1.1.0-SNAPSHOT · bbbbbbb', at: iso(0), eventId: 'ev-up-1' } }, info: INFO0 });
  await sleep(6000);
  v = await p.evaluate(() => ({ marker: window.__marker, hash: location.hash, bar: document.getElementById('pub-bar')?.innerText, open: PUB.openCommit }));
  R('CA13-recarga-automatica', v.marker === undefined && v.hash === '#/demandas' && /Squad Control atualizado para v1\.0\.0 · 1\.1\.0-SNAPSHOT · bbbbbbb/.test(v.bar || ''), v);
  await p.screenshot({ path: `${OUT}/d24-atualizado-1440.png` });
  await sleep(11000); v = await barText(p);
  R('CA11-aviso-10s', !/atualizado para/.test(v), { v });

  // --- CA-13 com rascunho: não recarrega, faixa "Recarregar", rascunho sobrevive
  await p.evaluate(() => { window.__marker = 2; const ta = document.getElementById('chat-text'); ta.value = 'rascunho importante D24'; });
  await setMock(p, { inst: { env: 'produtivo', commit: C2 }, pub: PUB0, info: INFO0, down: true }); await sleep(2500);
  await setMock(p, { inst: { env: 'produtivo', commit: C3 }, pub: { ...PUB0, lastResult: { type: 'squad-updated', commit: C3, display: 'v1.0.0 · ccccccc', at: iso(0), eventId: 'ev-up-2' } }, info: INFO0 });
  await sleep(5000);
  v = await p.evaluate(() => ({ marker: window.__marker, bar: document.getElementById('pub-bar')?.innerText, btn: !!document.querySelector('[data-pub-act="reload"]') }));
  R('CA13-rascunho-sem-recarga', v.marker === 2 && v.btn && /Nova versão do Squad Control no ar/.test(v.bar || ''), v);
  await p.screenshot({ path: `${OUT}/d24-recarregar-1440.png` });
  await p.click('[data-pub-act="reload"]'); await sleep(4000);
  v = await p.evaluate(() => ({ marker: window.__marker, draft: document.getElementById('chat-text').value }));
  R('CA13-rascunho-preservado', v.marker === undefined && v.draft === 'rascunho importante D24', v);
  await p.evaluate(() => { document.getElementById('chat-text').value = ''; window.__marker = 3; });

  // --- CA-2/CA-11: falha com rollback (faixa persistente, fechável) e selo revertido
  await setMock(p, { inst: { env: 'produtivo', commit: C3, fresh: { state: 'revertido', failedCommit: 'ddddddd' } },
    pub: { ...PUB0, state: 'revertido', mode: 'anterior', lastResult: { type: 'squad-update-failed', commit: C4, display: null, at: iso(0), eventId: 'ev-f1' } },
    info: { ...INFO0, state: 'revertido', lastResult: { type: 'squad-update-failed', commit: C4, at: iso(0), eventId: 'ev-f1', phase: 'health', rolledBack: true, detail: '/api/state 500' } } });
  await p.evaluate(() => instFetch()); await sleep(3000);
  v = { bar: await barText(p), selo: await text(p, '#inst-side'), aria: await p.$eval('#inst-side', e => e.getAttribute('aria-label')) };
  R('CA2-faixa-rollback', /Publicação de ddddddd falhou \(saúde após reinício\); mantida a versão anterior v1\.0\.0 · 1\.1\.0-SNAPSHOT · ccccccc\./.test(v.bar) && /Veja o log/.test(v.bar), v);
  R('CA12-selo-revertido', /\[!\] revertido \(falhou ddddddd\)/.test(v.selo || '') && /revertido/.test(v.aria || ''), v);
  await p.screenshot({ path: `${OUT}/d24-rollback-1440.png` });
  await p.setViewport({ width: 390, height: 844 }); await sleep(600);
  await p.screenshot({ path: `${OUT}/d24-rollback-390.png` });
  await p.setViewport({ width: 1440, height: 900 }); await sleep(300);
  await p.click('[data-pub-act="close-fail"]'); await sleep(2000);
  v = await barText(p);
  R('faixa-falha-fechavel', !/falhou/.test(v), { v });
  // falha sem rollback (pré-voo)
  await setMock(p, { inst: { env: 'produtivo', commit: C3 }, pub: { ...PUB0, lastResult: { type: 'squad-update-failed', commit: C4, display: null, at: iso(0), eventId: 'ev-f2' } },
    info: { ...INFO0, lastResult: { type: 'squad-update-failed', commit: C4, at: iso(0), eventId: 'ev-f2', phase: 'preflight', rolledBack: false, detail: 'SyntaxError em tools/squad/server.py, linha 12\nTraceback…' } } });
  await p.evaluate(() => instFetch()); await sleep(3000); v = await barText(p);
  R('CA2-faixa-preflight', /Publicação de ddddddd não foi feita \(verificação prévia\): SyntaxError em tools\/squad\/server\.py, linha 12\. A versão no ar continua v1\.0\.0 · 1\.1\.0-SNAPSHOT · ccccccc\./.test(v), { v });
  await p.screenshot({ path: `${OUT}/d24-preflight-1440.png` });

  // --- CA-14: conversa interrompida pela publicação (registro REAL do SIGTERM) + Reenviar
  await setMock(p, {});
  await p.goto(BASE + `#/painel?conversa=${CID}`, { waitUntil: 'domcontentloaded' }); await sleep(3500);
  v = await p.evaluate(() => { const li = [...document.querySelectorAll('#chat-msgs .c-msg--orq')].pop(); return { body: li?.querySelector('.c-body')?.innerText, foot: li?.querySelector('.c-foot')?.innerText, btn: li?.querySelector('[data-chat-retry]')?.innerText }; });
  R('CA14-interrompida', /Resposta interrompida pela publicação do Squad Control\. O texto já recebido ficou salvo\./.test(v.body || '') && /Recebido\. O registro confirma/.test(v.body || '') && /Interrompida pela publicação/.test(v.foot || '') && v.btn === 'Reenviar', v);
  await p.screenshot({ path: `${OUT}/d24-conversa-interrompida-1440.png` });
  await p.setViewport({ width: 390, height: 844 }); await sleep(600);
  await p.screenshot({ path: `${OUT}/d24-conversa-interrompida-390.png` });
  await p.setViewport({ width: 1440, height: 900 }); await sleep(300);
  await p.click('#chat-msgs [data-chat-retry]'); await sleep(2500);
  v = await p.evaluate(() => ({ humans: [...document.querySelectorAll('#chat-msgs .c-msg--hum')].map(x => x.querySelector('.c-body')?.innerText) }));
  R('CA14-reenviar', v.humans.length === 2 && v.humans[0] === v.humans[1], v);

  // --- Parte B: supervisor REAL (sandbox) — merge muda o <title>; a aba recarrega sozinha, sem terminal (CA-1, CA-13)
  if (REAL_PORT) {
    await relay(REAL_PORT);
    const q = await b.newPage();
    q.on('pageerror', e => out.errors.push('real: ' + String(e)));
    await q.setViewport({ width: 1440, height: 900 });
    await q.goto(`http://127.0.0.1:${REAL_PORT}/#/demandas`, { waitUntil: 'domcontentloaded' }); await sleep(3500);
    await q.evaluate(() => { window.__marker = 'real'; });
    const t0 = Date.now(); fs.writeFileSync(`${OUT}/d24-real-ready`, String(t0));
    let rv = null, bar = '';
    while (Date.now() - t0 < 120000) {
      await sleep(1000);
      try {
        rv = await q.evaluate(() => ({ marker: window.__marker === undefined ? 'recarregada' : window.__marker, open: (typeof PUB !== 'undefined' && PUB.openCommit) || '', hash: location.hash,
          bar: document.getElementById('pub-bar') && !document.getElementById('pub-bar').hidden ? document.getElementById('pub-bar').innerText : '' }));
        if (/atualizado para/.test(rv.bar || '')) bar = rv.bar;
        if (rv.marker === 'recarregada' && bar && rv.open && bar.includes(rv.open.slice(0, 7))) break;
      } catch (e) { /* navegação em curso */ }
    }
    const secs = Math.round((Date.now() - t0) / 100) / 10;
    // o <title> muda no HTML, mas o app reescreve document.title; a prova é o commit com que a página (re)abriu
    const html = await q.evaluate(() => fetch('/').then(r => r.text())).catch(() => '');
    R('CA1-real-recarga-sozinha', !!rv && rv.marker === 'recarregada' && !!rv.open && bar.includes(rv.open.slice(0, 7)) && rv.hash === '#/demandas' && /Squad Control atualizado para/.test(bar) && html.includes(REAL_TITLE) && secs <= 60, { ...rv, bar, secs, htmlTemTitulo: html.includes(REAL_TITLE) });
    await q.screenshot({ path: `${OUT}/d24-real-atualizado-1440.png` });
    await q.close();
  }
  await sleep(6000);
  await b.close();
  fs.writeFileSync(`${OUT}/d24-publicacao-result.json`, JSON.stringify(out, null, 2));
  const bad = Object.entries(out.results).filter(([, r]) => !r.ok).map(([k]) => k);
  console.log(JSON.stringify({ falhas: bad, erros: out.errors }, null, 1));
  process.exit(bad.length || out.errors.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
