// D20 (41bdb8b49835) — visual da conversa com o Orquestrador, v2: roteiro de navegador (QA, teste de reprodução).
// Contrato: docs/contracts/ui-conversa-visual-v2.md §4 (CA-V1..CA-V12); parecer docs/squad/gates/G1-D20.json.
// CA-V5 (servidor/prompt) está em tests/squad/test_conversa_tz_d20.py; aqui só a parte de UI (a UI envia `tz`).
//
// Os seletores aceitam a estrutura atual (`.who`/`.bub`/`#chat-live`) E a v2 (`.c-meta`/`.c-body`/`.c-msg--streaming`),
// para que o teste falhe hoje pelo MOTIVO do bug (layout/cor/fase/horário), não por seletor inexistente.
//
// Isolamento: servidor do WORKTREE com dados TEMPORÁRIOS (nunca o :7070 nem o log real) e runner SIMULADO
// (tests/squad/conversa_fake_runner.py, palavra-chave FXD20 = texto FX do §4 em trechos a cada 0,45 s):
//   S=<scratch>/qa-d20; python3 -c "import sys,pathlib; sys.path.insert(0,'tests/squad'); import test_conversa_d17 as h; \
//     h.make_data(pathlib.Path('$S/ui-data'))"; mkdir -p $S/ui-data/.squad/conversas
//   SQUAD_ROOT_DATA=$S/ui-data SQUAD_LOG=$S/ui-data/docs/squad/memory/decisions.jsonl SQUAD_TRANSCRIPTS=$S/trans \
//     SQUAD_TESTENV_PROBE=0 SQUAD_TESTENV_SPAWN=0 SQUAD_CHAT_RUNNER=fake SQUAD_CHAT_FAKE=$PWD/tests/squad/conversa_fake_runner.py \
//     SQUAD_CHAT_TIMEOUT_S=20 python3 tools/squad/server.py --port <livre> &
//   docker run --rm --add-host=host.docker.internal:host-gateway -e TZ=America/Sao_Paulo -e PORT=<livre> \
//     -v "$PWD/tests/ui:/shots" -v "$S/ui-data/.squad/conversas:/conv" zenika/alpine-chrome:with-puppeteer \
//     node /shots/d20-conversa-visual.js > $S/d20-ui.json
//   (G3/QA: imagem zenika com NODE_PATH=/usr/src/app/node_modules e --entrypoint node; axe opcional em
//    -v "$S/axe.min.js:/work/axe.min.js:ro" — sem ele o CA-V10 falha por falta da medida de contraste.)
// As rotas /api/conversas* exigem Host local (anti-DNS-rebinding): repasse TCP dentro do container
// (127.0.0.1:PORT → host.docker.internal:PORT). Saída: JSON {results:{CA-Vn:{ok,...}}, errors}; código 1 se algum falhar.
const puppeteer = require('puppeteer');
const net = require('net');
const fs = require('fs');
const PORT = Number(process.env.PORT || 7381);
const BASE = `http://127.0.0.1:${PORT}/`;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = { results: {}, errors: [] };
const R = (k, v) => { out.results[k] = v; console.error(`[${k}] ${v.ok ? 'PASS' : 'FAIL'} ${JSON.stringify(v).slice(0, 700)}`); };
const relay = port => new Promise(res => net.createServer(c => {
  const u = net.connect(port, 'host.docker.internal');
  c.pipe(u).pipe(c); u.on('error', () => c.destroy()); c.on('error', () => u.destroy());
}).listen(port, '127.0.0.1', res));
const diffAt = (a, b) => { let i = 0; while (i < a.length && a[i] === b[i]) i++; return i === a.length && a.length === b.length ? {} : { difereEm: i, live: a.slice(Math.max(0, i - 60), i + 80), final: b.slice(Math.max(0, i - 60), i + 80) }; };
const PHASE_RE = /Pensando|Lendo|Procurando|Consultando|Respondendo|Parando/;

// ---- seletores compatíveis (atual × v2)
const SEL = {
  msgs: '#chat-msgs > li.c-msg',
  live: '#chat-msgs > li.c-msg--streaming, #chat-live',
};

// Medidas de DOM rodadas na página (serializadas para evaluate).
function measure() {
  const pick = (li, a, b) => li.querySelector(`:scope > ${a}`) || li.querySelector(`:scope > ${b}`);
  const lis = [...document.querySelectorAll('#chat-msgs > li.c-msg')];
  return lis.map(li => {
    const orq = li.classList.contains('c-msg--orq') || li.classList.contains('orquestrador');
    const meta = pick(li, '.c-meta', '.who'), body = pick(li, '.c-body', '.bub');
    const cs = getComputedStyle(li), mr = meta?.getBoundingClientRect(), br = body?.getBoundingClientRect();
    return {
      orq, streaming: li.classList.contains('c-msg--streaming') || li.id === 'chat-live', cls: li.className,
      display: cs.display, flexDirection: cs.flexDirection,
      metaAbove: !!(mr && br) && mr.bottom <= br.top + 0.5,
      sideDelta: mr && br ? Math.round((orq ? Math.abs(mr.left - br.left) : Math.abs(mr.right - br.right)) * 10) / 10 : null,
    };
  });
}

(async () => {
  await relay(PORT);
  const b = await puppeteer.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'], executablePath: process.env.PUPPETEER_EXECUTABLE_PATH });
  // clock (ms desde a época): relógio FIXO do navegador (defeito af1bc2450bca — o CA-V4 dependia da hora real: depois
  // de 00:00 em Tóquio a mensagem "de hoje" virava "ontem"). Só `new Date()`/`Date.now()` sem argumento são deslocados;
  // o tempo continua andando a partir do instante fixado (timers/animações intactos).
  const page = async (w, { theme = 'light', tz = 'America/Sao_Paulo', hash = '#/painel', clock = null } = {}) => {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: w > 500 ? 900 : 844, deviceScaleFactor: 1 });
    await p.emulateTimezone(tz);
    p.on('pageerror', e => out.errors.push(String(e).slice(0, 300)));
    if (clock != null) await p.evaluateOnNewDocument(fixed => {
      const RD = Date, off = fixed - RD.now();
      class FD extends RD { constructor(...a) { if (a.length === 0) super(RD.now() + off); else super(...a); } static now() { return RD.now() + off; } }
      window.Date = FD;
    }, clock);
    await p.evaluateOnNewDocument(t => {
      try { localStorage.setItem('sc-theme', t); } catch (e) { /* */ }
      window.__live = []; window.__posts = [];
      const f = window.fetch; window.fetch = (u, o) => { if (o && o.method === 'POST' && /\/mensagens$/.test(String(u))) window.__posts.push(o.body); return f(u, o); };
      document.addEventListener('DOMContentLoaded', () => {
        const el = document.getElementById('sr-live');
        if (el) new MutationObserver(() => { const t = el.textContent.trim(); if (t) window.__live.push(t); }).observe(el, { childList: true, characterData: true, subtree: true });
      });
    }, theme);
    await p.goto(BASE + hash, { waitUntil: 'domcontentloaded' });
    await p.waitForFunction(() => typeof state !== 'undefined' && state, { timeout: 60000 }); await sleep(500);
    return p;
  };
  const shot = (p, n) => p.screenshot({ path: `/shots/d20-${n}.png` });
  const typeSend = async (p, t) => { await p.focus('#chat-text'); await p.$eval('#chat-text', e => { e.value = ''; }); await p.type('#chat-text', t); await p.keyboard.press('Enter'); };
  const waitIdle = (p, ms = 30000) => p.waitForFunction(() => !document.querySelector('#chat-msgs > li.c-msg--streaming, #chat-live') && document.getElementById('chat-stop').hidden, { timeout: ms });
  const liveBodyText = p => p.evaluate(s => { const li = document.querySelector(s); const bd = li && (li.querySelector(':scope > .c-body') || li.querySelector(':scope > .bub')); return bd ? bd.textContent : ''; }, SEL.live);
  const phaseCount = p => p.evaluate(re => {
    const rx = new RegExp(re), chat = document.getElementById('chat'), hits = [];
    for (const el of chat.querySelectorAll('*')) {
      const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('');
      if (!rx.test(own)) continue;
      const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      if (r.width && r.height && cs.visibility !== 'hidden' && !el.closest('[hidden]')) hits.push({ where: el.closest('#chat-status') ? 'status' : el.closest('li.c-msg--streaming, #chat-live') ? 'streaming' : el.className || el.tagName, t: own.trim().slice(0, 40) });
    }
    return hits;
  }, PHASE_RE.source);

  // ======================= Turno 1 (concluído) + turno 2 "Mandei la" ao vivo (reproduz a captura da evidência)
  const p = await page(1440, { hash: '#/painel?conversa=nova' }); await sleep(1000);
  await typeSend(p, 'Primeira pergunta FXD20'); await waitIdle(p);
  const composer0 = await p.evaluate(() => { const r = document.getElementById('chat-send').getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y) }; });
  await p.evaluate(() => { window.__live.length = 0; });
  await typeSend(p, 'Mandei la FXD20');
  await p.waitForFunction(s => { const li = document.querySelector(s); return li && /08:47[\s\S]*você iniciou/.test(li.textContent); }, { timeout: 15000 }, SEL.live);
  // --- durante o streaming
  const v1Live = await p.evaluate(measure);
  const liveHasLiveClass = await p.evaluate(() => document.querySelectorAll('#chat .live').length);
  const v2Live = await p.evaluate(s => {
    const li = document.querySelector(s), bd = li.querySelector(':scope > .c-body') || li.querySelector(':scope > .bub');
    const done = [...document.querySelectorAll('#chat-msgs > li.c-msg')].find(x => x !== li && (x.classList.contains('c-msg--orq') || x.classList.contains('orquestrador')));
    const dbd = done && (done.querySelector(':scope > .c-body') || done.querySelector(':scope > .bub'));
    const lp = bd.querySelector('p'), dp = dbd && dbd.querySelector('p');
    const text = getComputedStyle(document.documentElement).getPropertyValue('--text').trim(), ok = getComputedStyle(document.documentElement).getPropertyValue('--ok').trim();
    const probe = c => { const d = document.createElement('span'); d.style.color = c; document.body.append(d); const v = getComputedStyle(d).color; d.remove(); return v; };
    const caret = li.querySelector('.c-caret');
    return {
      liveColor: lp && getComputedStyle(lp).color, liveWeight: lp && getComputedStyle(lp).fontWeight, liveBodyColor: getComputedStyle(bd).color,
      doneColor: dp && getComputedStyle(dp).color, textColor: probe(text), okColor: probe(ok),
      strong: [...bd.querySelectorAll('strong, b')].map(x => x.textContent),
      ulStyle: bd.querySelector('ul') && getComputedStyle(bd.querySelector('ul')).listStyleType,
      caretParent: caret && caret.parentElement.tagName,
    };
  }, SEL.live);
  const v3Live = { phases: await phaseCount(p), statusVisible: await p.evaluate(() => !document.getElementById('chat-status').hidden) };
  const v8Live = await p.evaluate(() => {
    const ta = document.getElementById('chat-text'), btns = [...document.querySelectorAll('#chat button')].filter(x => !x.hidden && /^\s*Parar\s*$/.test(x.textContent));
    const r = btns[0] && btns[0].getBoundingClientRect();
    return { editable: !ta.readOnly && !ta.disabled, stop: r ? { x: Math.round(r.x), y: Math.round(r.y) } : null };
  });
  await shot(p, '1440-claro-streaming');
  // captura do corpo ao vivo com o texto completo (antes do fim), sem cursor e sem linha de fase
  const snapLive = await p.waitForFunction(s => {
    const li = document.querySelector(s); if (!li) return null;
    const bd = li.querySelector(':scope > .c-body') || li.querySelector(':scope > .bub');
    if (!/o painel\.\s*$/.test(bd.textContent)) return false;
    const c = bd.cloneNode(true); c.querySelectorAll('.c-caret, .c-phase, .muted').forEach(x => x.remove());
    return c.innerHTML;
  }, { timeout: 15000, polling: 50 }, SEL.live).then(h => h.jsonValue()).catch(() => null);
  await waitIdle(p); await sleep(400);
  // --- após o fim
  const v1Final = await p.evaluate(measure);
  const v2Final = await p.evaluate(() => { const li = [...document.querySelectorAll('#chat-msgs > li.c-msg')].at(-1); const bd = li.querySelector(':scope > .c-body') || li.querySelector(':scope > .bub'); return bd.innerHTML; });
  const v3Final = await p.evaluate(() => { const st = document.getElementById('chat-status'); const all = document.getElementById('chat').innerText; return { statusText: st.hidden ? '' : st.textContent.trim(), total: (all.match(/total\s+[\d,.]+\s*s/g) || []).length }; });
  await shot(p, '1440-claro-final');
  const liveAnnounce = await p.evaluate(() => [...window.__live]);
  const tzPosts = await p.evaluate(() => window.__posts.map(b => { try { return JSON.parse(b).tz ?? null; } catch (e) { return null; } }));

  const V1 = { durante: v1Live, final: v1Final, classeLive: liveHasLiveClass };
  const liOk = m => (m.display === 'block' || m.display === 'list-item' || (m.display.includes('flex') && m.flexDirection === 'column')) && m.metaAbove && m.sideDelta !== null && m.sideDelta <= 1;
  R('CA-V1', { ok: v1Live.every(liOk) && v1Final.every(liOk) && liveHasLiveClass === 0 && v1Live.some(m => m.streaming), ...V1 });
  R('CA-V2', { ok: !!v2Live.liveColor && v2Live.liveColor === v2Live.doneColor && v2Live.liveColor === v2Live.textColor && v2Live.liveWeight === '400'
      && v2Live.strong.length === 1 && v2Live.strong[0] === '08:47' && v2Live.ulStyle === 'disc' && v2Live.caretParent === 'LI' && snapLive === v2Final,
    ...v2Live, iguaisLiveFinal: snapLive === v2Final, ...diffAt(snapLive || '', v2Final) });

  // CA-V3: erro simulado
  await typeSend(p, 'FALHAR agora'); await waitIdle(p); await sleep(400);
  const v3Err = await p.evaluate(() => { const st = document.getElementById('chat-status'); const all = document.getElementById('chat').innerText;
    return { statusVisible: !st.hidden, statusText: st.hidden ? '' : st.textContent.trim().slice(0, 120), invalidKey: (all.match(/Invalid API key/g) || []).length }; });
  R('CA-V3', { ok: v3Live.phases.length === 1 && v3Live.phases[0].where === 'streaming' && !v3Live.statusVisible && !/concluída/i.test(v3Final.statusText) && v3Final.total === 1
      && !v3Err.statusVisible && v3Err.invalidKey === 1, durante: v3Live, final: v3Final, erro: v3Err });
  R('CA-V8-parcial', { ok: v8Live.editable && !!v8Live.stop && Math.abs(v8Live.stop.x - composer0.x) <= 2 && Math.abs(v8Live.stop.y - composer0.y) <= 2, durante: v8Live, enviar: composer0 });
  R('CA-V11-aria-live', { ok: liveAnnounce.filter(t => /Recebido|08:47|registro confirma/.test(t)).length === 0 && liveAnnounce.some(t => /Resposta do Orquestrador recebida/.test(t)), liveAnnounce });
  await p.close();

  // ======================= CA-V4: horários no fuso do navegador, sem segundos, "ontem"
  const ymd = (d, tz) => new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  // Relógio fixo (af1bc2450bca): 2026-09-24 12:00Z = 09:00 em São Paulo e 21:00 em Tóquio — "hoje" nos dois fusos.
  const CLOCK = Date.UTC(2026, 8, 24, 12, 0, 0);
  const now = new Date(CLOCK), today = ymd(now, 'America/Sao_Paulo'), yday = ymd(new Date(now.getTime() - 86400000), 'America/Sao_Paulo');
  const [yy, mm, dd] = today.split('-');
  const CID = 'c-d20d20d20d20';
  const recs = [
    { t: 'meta', id: CID, createdAt: `${yday}T11:40:00Z`, runner: 'fake', modelRequested: null, sessionId: '00000000-0000-4000-8000-00000000d020', v: 1 },
    { t: 'msg', seq: 1, turn: 1, role: 'humano', ts: `${yday}T11:47:59Z`, text: 'pergunta de ontem' },
    { t: 'msg', seq: 2, turn: 1, role: 'orquestrador', ts: `${yday}T11:48:10Z`, text: 'resposta de ontem', status: 'ok', runner: 'fake', model: 'claude-fake-1-20260901', firstTextMs: 900, totalMs: 2100 },
    { t: 'msg', seq: 3, turn: 2, role: 'humano', ts: `${today}T11:47:59Z`, text: 'Mandei la' },
    { t: 'msg', seq: 4, turn: 2, role: 'orquestrador', ts: `${today}T11:48:30Z`, text: 'Recebido. O registro confirma:\n\n- **08:47** – ok.', status: 'ok', runner: 'fake', model: 'claude-fake-1-20260901', firstTextMs: 1800, totalMs: 23300 },
  ];
  let v4 = { ok: false, erro: 'sem /conv montado' };
  if (fs.existsSync('/conv')) {
    fs.writeFileSync(`/conv/${CID}.jsonl`, recs.map(r => JSON.stringify(r)).join('\n') + '\n');
    const times = async tz => {
      const q = await page(1440, { tz, hash: `#/painel?conversa=${CID}`, clock: CLOCK }); await sleep(1500);
      const r = await q.evaluate(() => {
        const pick = li => li.querySelector(':scope > .c-meta') || li.querySelector(':scope > .who');
        const msgs = [...document.querySelectorAll('#chat-msgs > li.c-msg')].map(li => { const m = pick(li), t = m && m.querySelector('time');
          return { meta: m ? m.textContent.replace(/\s+/g, ' ').trim() : '', time: t ? t.textContent.trim() : null, title: t ? t.getAttribute('title') || '' : '', dt: t ? t.getAttribute('datetime') : null }; });
        const chatTimes = [...document.querySelectorAll('#chat time')].map(t => t.textContent.trim());
        return { msgs, secondsShown: chatTimes.filter(x => /\d{1,2}:\d{2}:\d{2}/.test(x)), chatTimes };
      });
      if (tz === 'America/Sao_Paulo') await shot(q, 'horarios-1440');
      await q.close(); return r;
    };
    const sp = await times('America/Sao_Paulo'), tk = await times('Asia/Tokyo');
    const hojeHum = sp.msgs[2] || {}, ontemHum = sp.msgs[0] || {};
    v4 = {
      ok: hojeHum.time === '08:47' && hojeHum.title.includes(`${dd}/${mm}/${yy} 08:47:59`) && /^ontem 08:47$/.test(ontemHum.time || '') && (tk.msgs[2] || {}).time === '20:47'
        && sp.secondsShown.length === 0 && tzPosts.length > 0 && tzPosts.every(z => z === 'America/Sao_Paulo'),
      saoPaulo: sp.msgs, toquio: tk.msgs.map(m => m.time), comSegundos: sp.secondsShown, tzEnviadoNoPost: tzPosts,
    };
  }
  R('CA-V4', v4);

  // ======================= CA-V6/V9/V10/V12 (checagens de apoio) em 390 e tema escuro
  const q = await page(390, { theme: 'dark', hash: `#/painel?conversa=${CID}` }); await sleep(1500);
  const v9 = await q.evaluate(() => {
    const bubbles = [...document.querySelectorAll('#chat-msgs > li.c-msg')].filter(li => li.classList.contains('c-msg--hum') || li.classList.contains('humano'))
      .map(li => { const bd = li.querySelector(':scope > .c-body') || li.querySelector(':scope > .bub'); return bd.getBoundingClientRect().width / document.getElementById('chat-msgs').clientWidth; });
    const sep = document.querySelectorAll('#chat [role="separator"]').length;
    return { hscroll: document.documentElement.scrollWidth > innerWidth, maxBubble: Math.max(0, ...bubbles), separadorDeDia: sep };
  });
  R('CA-V9-parcial', { ok: !v9.hscroll && v9.maxBubble <= 0.88 + 0.005 && v9.separadorDeDia >= 1, ...v9 });
  const v10 = await q.evaluate(() => {
    const probe = c => { const d = document.createElement('span'); d.style.color = c; document.body.append(d); const v = getComputedStyle(d).color; d.remove(); return v; };
    const ok = probe(getComputedStyle(document.documentElement).getPropertyValue('--ok').trim());
    const green = [...document.querySelectorAll('#chat-msgs li.c-msg *')].filter(e => e.textContent.trim() && getComputedStyle(e).color === ok).map(e => e.tagName + '.' + e.className);
    return { okColor: ok, textoVerde: green.slice(0, 10) };
  });
  await shot(q, '390-escuro-final');
  R('CA-V10-parcial', { ok: v10.textoVerde.length === 0, ...v10 });
  const v6 = await q.evaluate(() => {
    const li = [...document.querySelectorAll('#chat-msgs > li.c-msg')].at(-1), bd = li.querySelector(':scope > .c-body') || li.querySelector(':scope > .bub');
    return { ulStyle: bd.querySelector('ul') && getComputedStyle(bd.querySelector('ul')).listStyleType, strong: [...bd.querySelectorAll('strong')].map(x => x.textContent) };
  });
  R('CA-V6-parcial', { ok: v6.ulStyle === 'disc' && v6.strong.join() === '08:47', ...v6 });
  const v12 = await q.evaluate(() => { const h = document.querySelector('#hdr .live, .gbar .live'); if (!h) return { existe: false };
    const probe = c => { const d = document.createElement('span'); d.style.color = c; document.body.append(d); const v = getComputedStyle(d).color; d.remove(); return v; };
    const cs = getComputedStyle(h); return { existe: true, display: cs.display, color: cs.color, okOrState: [probe('var(--ok)'), probe('var(--warn)'), probe('var(--danger)')].includes(cs.color) }; });
  R('CA-V12-indicador-live', { ok: v12.existe ? /flex/.test(v12.display) && v12.okOrState : true, ...v12 });
  await q.close();

  // ======================= G3 (QA): CA-V6, V7, V8, V9, V10 e V11 completos (ressalvas do G2-D20)
  const axe = fs.existsSync('/work/axe.min.js') ? fs.readFileSync('/work/axe.min.js', 'utf8') : null;
  const runAxe = async pg => { if (!axe) return null; if (!(await pg.evaluate(() => !!window.axe))) await pg.addScriptTag({ content: axe });
    return pg.evaluate(async () => (await axe.run('#chat', { runOnly: ['wcag2aa'] })).violations.map(v => ({ id: v.id, n: v.nodes.length, ex: v.nodes.slice(0, 3).map(n => n.target.join(' ')) }))); };
  const greenText = pg => pg.evaluate(() => {
    const probe = c => { const d = document.createElement('span'); d.style.color = c; document.body.append(d); const v = getComputedStyle(d).color; d.remove(); return v; };
    const ok = probe(getComputedStyle(document.documentElement).getPropertyValue('--ok').trim());
    return [...document.querySelectorAll('#chat-msgs li.c-msg *')].filter(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) && getComputedStyle(e).color === ok).map(e => e.tagName + '.' + e.className).slice(0, 10);
  });

  // ---- CA-V10: 8 capturas d20-{1440,390}-{claro,escuro}-{streaming,final}.png + contraste (axe wcag2aa) + nenhum texto verde
  const v10f = {};
  for (const [w, theme, nome] of [[1440, 'light', 'claro'], [1440, 'dark', 'escuro'], [390, 'light', 'claro'], [390, 'dark', 'escuro']]) {
    const pg = await page(w, { theme, hash: '#/painel?conversa=nova' }); await sleep(800);
    await typeSend(pg, 'Primeira FXD20'); await waitIdle(pg);
    await typeSend(pg, 'Mandei la FXD20');
    await pg.waitForFunction(s => { const li = document.querySelector(s); return li && /você iniciou/.test(li.textContent); }, { timeout: 15000 }, SEL.live);
    const k = `${w}-${nome}`;
    v10f[k] = { durante: { axe: await runAxe(pg), verde: await greenText(pg) } };
    await shot(pg, `${w}-${nome}-streaming`);
    await waitIdle(pg); await sleep(500);
    v10f[k].final = { axe: await runAxe(pg), verde: await greenText(pg), hscroll: await pg.evaluate(() => document.documentElement.scrollWidth > innerWidth) };
    await shot(pg, `${w}-${nome}-final`);
    await pg.close();
  }
  R('CA-V10', { ok: Object.values(v10f).every(x => ['durante', 'final'].every(f => (x[f].axe === null || x[f].axe.length === 0) && x[f].verde.length === 0)) && !!axe, axeDisponivel: !!axe, ...v10f });

  // ---- CA-V6: Markdown completo e seguro (390, escuro)
  {
    const pg = await page(390, { theme: 'dark', hash: '#/painel?conversa=nova' }); await sleep(800);
    await typeSend(pg, 'MDV6 markdown'); await waitIdle(pg); await sleep(400);
    const r = await pg.evaluate(() => {
      const li = [...document.querySelectorAll('#chat-msgs > li.c-msg')].at(-1), bd = li.querySelector(':scope > .c-body');
      const pre = bd.querySelector('pre'), tbl = bd.querySelector('table'), tw = tbl && tbl.parentElement;
      const ext = [...bd.querySelectorAll('a')].find(a => /^https?:/.test(a.getAttribute('href') || ''));
      const ol = bd.querySelector('ol');
      return {
        p: !!bd.querySelector('p'), ol: !!ol && getComputedStyle(ol).listStyleType, aninhada: !!bd.querySelector('li > ul, li > ol'),
        ulTopo: bd.querySelector(':scope ul') && getComputedStyle(bd.querySelector('ul')).listStyleType,
        ulAninhada: bd.querySelector('li > ul') && getComputedStyle(bd.querySelector('li > ul')).listStyleType,
        code: !!bd.querySelector(':not(pre) > code'), pre: pre && { ox: getComputedStyle(pre).overflowX, rola: pre.scrollWidth > pre.clientWidth, ws: getComputedStyle(pre).whiteSpace },
        quote: !!bd.querySelector('blockquote'), tabela: tbl && { linhas: tbl.querySelectorAll('tr').length, cols: tbl.querySelector('tr').children.length, contOx: getComputedStyle(tw).overflowX },
        interno: [...bd.querySelectorAll('a')].map(a => a.getAttribute('href')).filter(h => h && h.startsWith('#/')),
        externo: ext && { rel: ext.getAttribute('rel'), target: ext.getAttribute('target') },
        negritoLiteral: bd.textContent.includes('**negrito sem fechar'), img: bd.querySelectorAll('img').length, imgLiteral: bd.textContent.includes('<img src=x onerror=alert(1)>'),
        hscroll: document.documentElement.scrollWidth > innerWidth || document.body.scrollWidth > innerWidth,
      };
    });
    await shot(pg, '390-escuro-markdown');
    R('CA-V6', { ok: r.p && r.ol === 'decimal' && r.aninhada && r.ulTopo === 'disc' && r.code && r.pre && /auto|scroll/.test(r.pre.ox) && r.pre.rola && r.quote && r.tabela && r.tabela.linhas === 4 && r.tabela.cols === 3
      && /auto|scroll/.test(r.tabela.contOx) && r.interno.some(h => /^#\/painel(\?|$)/.test(h)) && r.externo && /noopener/.test(r.externo.rel) && /noreferrer/.test(r.externo.rel) && r.negritoLiteral && r.img === 0 && r.imgLiteral && !r.hscroll, ...r });
    await pg.close();
  }

  // ---- CA-V7 (rolagem) + CA-V11 (teclado em "Ir para o fim"): histórico longo semeado + resposta LONGO (~10 s)
  const CID7 = 'c-d20d20d20d21';
  if (fs.existsSync('/conv')) {
    const hist = [{ t: 'meta', id: CID7, createdAt: `${today}T10:00:00Z`, runner: 'fake', modelRequested: null, sessionId: '00000000-0000-4000-8000-00000000d021', v: 1 }];
    for (let i = 1; i <= 15; i++) {
      hist.push({ t: 'msg', seq: 2 * i - 1, turn: i, role: 'humano', ts: `${today}T10:${String(i).padStart(2, '0')}:00Z`, text: `pergunta ${i}` });
      hist.push({ t: 'msg', seq: 2 * i, turn: i, role: 'orquestrador', ts: `${today}T10:${String(i).padStart(2, '0')}:30Z`, text: `Resposta ${i}.\n\n- item a\n- item b\n- item c`, status: 'ok', runner: 'fake', model: 'claude-fake-1-20260901', firstTextMs: 500, totalMs: 1500 });
    }
    fs.writeFileSync(`/conv/${CID7}.jsonl`, hist.map(r => JSON.stringify(r)).join('\n') + '\n');
  }
  {
    const pg = await page(1440, { hash: `#/painel?conversa=${CID7}` }); await sleep(1500);
    const dist = () => pg.evaluate(() => { const l = document.getElementById('chat-msgs'); return Math.round(l.scrollHeight - l.scrollTop - l.clientHeight); });
    const btn = () => pg.evaluate(() => { const b = document.getElementById('chat-bottom'), r = b.getBoundingClientRect(); return { visivel: !b.hidden && r.height > 0, texto: b.textContent.trim(), ctrl: b.getAttribute('aria-controls') }; });
    const r = { historicoRola: await pg.evaluate(() => { const l = document.getElementById('chat-msgs'); return l.scrollHeight > l.clientHeight + 400; }) };
    await pg.evaluate(() => { const l = document.getElementById('chat-msgs'); l.scrollTop = 0; });   // rolado para cima antes de enviar
    await typeSend(pg, 'LONGO rolagem');
    await pg.waitForFunction(s => { const li = document.querySelector(s); return li && /Parágrafo 03/.test(li.textContent); }, { timeout: 15000 }, SEL.live);
    r.aoEnviarVaiAoFim = await dist();
    // parado no fim: acompanha cada trecho
    const seg = []; for (let i = 0; i < 8; i++) { await sleep(250); seg.push(await dist()); }
    r.acompanha = seg;
    // rola 400 px para cima: posição fixa por 3 s de trechos e aparece o botão
    await pg.evaluate(() => { const l = document.getElementById('chat-msgs'); l.scrollTop = l.scrollTop - 400; l.dispatchEvent(new Event('scroll')); });
    await sleep(100);
    const top0 = await pg.evaluate(() => document.getElementById('chat-msgs').scrollTop), len0 = (await liveBodyText(pg)).length;
    const tops = []; for (let i = 0; i < 6; i++) { await sleep(500); tops.push(await pg.evaluate(() => document.getElementById('chat-msgs').scrollTop)); }
    r.rolado = { top0, tops, cresceu: (await liveBodyText(pg)).length > len0, botao: await btn() };
    // CA-V11: só teclado — Shift+Tab a partir do campo chega em "Ir para o fim"; Enter rola ao fim e o foco volta ao campo
    await pg.focus('#chat-text'); await pg.keyboard.down('Shift'); await pg.keyboard.press('Tab'); await pg.keyboard.up('Shift');
    r.focoNoBotao = await pg.evaluate(() => document.activeElement?.id);
    const focVis = await pg.evaluate(() => { const b = document.getElementById('chat-bottom'), cs = getComputedStyle(b); return cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 2; });
    await pg.keyboard.press('Enter'); await sleep(1200);
    r.aposClique = { dist: await dist(), botao: await btn(), foco: await pg.evaluate(() => document.activeElement?.id), focoVisivel: focVis };
    // rolar manualmente até o fim também esconde o botão
    await pg.evaluate(() => { const l = document.getElementById('chat-msgs'); l.scrollTop = l.scrollTop - 400; l.dispatchEvent(new Event('scroll')); }); await sleep(300);
    const antesManual = (await btn()).visivel;
    await pg.evaluate(() => { const l = document.getElementById('chat-msgs'); l.scrollTop = l.scrollHeight; l.dispatchEvent(new Event('scroll')); }); await sleep(300);
    r.manual = { antes: antesManual, depois: (await btn()).visivel };
    await shot(pg, '1440-claro-rolagem');
    await waitIdle(pg, 30000); await sleep(400);
    // parado no meio do histórico, recarregar a lista (fim do turno → chatRender) preserva a posição
    await pg.evaluate(() => { const l = document.getElementById('chat-msgs'); l.scrollTop = 200; l.dispatchEvent(new Event('scroll')); }); await sleep(300);
    await typeSend(pg, 'pergunta curta depois de rolar');
    await sleep(300); r.enviarDeNovo = await dist();
    await waitIdle(pg); await sleep(300); r.aposFim = await dist();
    R('CA-V7', { ok: r.historicoRola && r.aoEnviarVaiAoFim <= 80 && r.acompanha.every(d => d <= 80) && r.rolado.tops.every(t => Math.abs(t - r.rolado.top0) <= 1) && r.rolado.cresceu
      && r.rolado.botao.visivel && /Nova resposta|Ir para o fim/.test(r.rolado.botao.texto) && r.rolado.botao.ctrl === 'chat-msgs'
      && r.aposClique.dist <= 80 && !r.aposClique.botao.visivel && r.aposClique.foco === 'chat-text' && r.manual.antes && !r.manual.depois && r.enviarDeNovo <= 80, ...r });
    R('CA-V11-ir-para-o-fim-teclado', { ok: r.focoNoBotao === 'chat-bottom' && r.aposClique.foco === 'chat-text' && r.aposClique.focoVisivel, foco: r.focoNoBotao, focoVisivel: r.aposClique.focoVisivel });
    await pg.close();
  }

  // ---- CA-V8: composição (altura automática, contador, Enter durante o turno, dica de atalhos)
  {
    const pg = await page(1440, { hash: '#/painel?conversa=nova' }); await sleep(800);
    const set = v => pg.evaluate(v => { const t = document.getElementById('chat-text'); t.value = v; t.dispatchEvent(new Event('input', { bubbles: true })); const r = t.getBoundingClientRect();
      return { h: Math.round(r.height), oy: getComputedStyle(t).overflowY, vh40: Math.round(innerHeight * 0.4), cont: !document.getElementById('chat-count').hidden }; }, v);
    const h1 = await set(''), h12 = await set(Array.from({ length: 12 }, (_, i) => `linha ${i}`).join('\n')), h60 = await set(Array.from({ length: 60 }, (_, i) => `linha ${i}`).join('\n'));
    const c100 = await set('a'.repeat(100)), c7000 = await set('a'.repeat(7000)), c8001 = await set('a'.repeat(8001));
    const over = await pg.evaluate(() => document.getElementById('chat-count').classList.contains('over'));
    await set(''); await typeSend(pg, 'Mandei la FXD20');
    await pg.waitForFunction(s => !!document.querySelector(s), { timeout: 10000 }, SEL.live);
    const nMsgs = await pg.evaluate(() => document.querySelectorAll('#chat-msgs > li.c-msg').length);
    await pg.type('#chat-text', 'rascunho'); await pg.keyboard.press('Enter'); await sleep(400);
    const dur = await pg.evaluate(() => ({ msgs: document.querySelectorAll('#chat-msgs > li.c-msg').length, val: document.getElementById('chat-text').value, hint: document.getElementById('chat-hint').textContent.trim() }));
    await waitIdle(pg); await set(''); const hApos = await set('');
    const hint1440 = await pg.evaluate(() => { const r = document.getElementById('chat-hint').getBoundingClientRect(); return r.width > 50 && r.height > 5; });
    await pg.close();
    const pq = await page(390, { hash: '#/painel?conversa=nova' }); await sleep(800);
    const hint390 = await pq.evaluate(() => { const h = document.getElementById('chat-hint'), r = h.getBoundingClientRect(); return { visivel: r.width > 2 && r.height > 2, describedby: document.getElementById('chat-text').getAttribute('aria-describedby') }; });
    await pq.close();
    const r = { h1, h12, h60, c100: c100.cont, c7000: c7000.cont, c8001: c8001.cont, over, nMsgs, dur, hApos, hint1440, hint390 };
    R('CA-V8', { ok: h1.h >= 44 && h12.h > h1.h && Math.abs(h60.h - h60.vh40) <= 2 && h60.oy === 'auto' && hApos.h === h1.h && !r.c100 && r.c7000 && r.c8001 && over
      && dur.msgs === nMsgs && dur.val.includes('rascunho') && /Aguarde/.test(dur.hint) && hint1440 && !hint390.visivel && /chat-hint/.test(hint390.describedby || ''), ...r });
  }

  // ---- CA-V9 completo: largura de leitura em 1440 e alvos em 390; CA-V11 reduced-motion
  {
    const pg = await page(1440, { hash: `#/painel?conversa=${CID}` }); await sleep(1500);
    const r1440 = await pg.evaluate(() => {
      const li = [...document.querySelectorAll('#chat-msgs > li.c-msg--orq')].at(-1), bd = li.querySelector(':scope > .c-body');
      const s = document.createElement('span'); s.textContent = '0'.repeat(68); s.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap'; bd.append(s); const ch68 = s.getBoundingClientRect().width; s.remove();
      const col = document.getElementById('chat-msgs'), cw = col.clientWidth;
      const hum = [...document.querySelectorAll('#chat-msgs > li.c-msg--hum > .c-body')].map(b => b.getBoundingClientRect().width / cw);
      return { corpo: Math.round(bd.getBoundingClientRect().width), ch68: Math.round(ch68), balaoMax: Math.round(Math.max(...hum) * 1000) / 1000 };
    });
    await pg.close();
    const pq = await page(390, { hash: `#/painel?conversa=${CID7}` }); await sleep(1500);
    await pq.evaluate(() => { const l = document.getElementById('chat-msgs'); l.scrollTop = 0; l.dispatchEvent(new Event('scroll')); }); await sleep(300);
    const r390 = await pq.evaluate(() => {
      const sz = e => { const r = e.getBoundingClientRect(); return { h: Math.round(r.height), w: Math.round(r.width) }; };
      return { irParaOFim: sz(document.getElementById('chat-bottom')), enviar: sz(document.getElementById('chat-send')), hscroll: document.documentElement.scrollWidth > innerWidth,
        links: [...document.querySelectorAll('#chat-msgs .c-foot .linkbtn, #chat-msgs .c-foot a')].filter(e => e.offsetParent).map(sz) };
    });
    await typeSend(pq, 'DORMIR parar'); await pq.waitForFunction(() => !document.getElementById('chat-stop').hidden, { timeout: 8000 });
    r390.parar = await pq.evaluate(() => Math.round(document.getElementById('chat-stop').getBoundingClientRect().height));
    await pq.click('#chat-stop'); await waitIdle(pq); await sleep(300);
    r390.linksRodape = await pq.evaluate(() => [...document.querySelectorAll('#chat-msgs .c-foot .linkbtn')].map(e => Math.round(e.getBoundingClientRect().height)));
    await pq.close();
    R('CA-V9', { ok: r1440.corpo <= r1440.ch68 + 1 && r1440.balaoMax <= 0.85 + 0.005 && r390.irParaOFim.h >= 44 && r390.enviar.h >= 44 && r390.parar >= 44 && !r390.hscroll && r390.linksRodape.every(h => h >= 44), r1440, r390 });
    // reduced motion: cursor e ícone de fase sem animação
    const pm = await page(1440, { hash: '#/painel?conversa=nova' }); await pm.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]); await sleep(500);
    await typeSend(pm, 'Mandei la FXD20');
    await pm.waitForFunction(s => { const li = document.querySelector(s); return li && li.querySelector('.c-caret') && li.querySelector('.c-phase-ic'); }, { timeout: 15000 }, SEL.live);
    const rm = await pm.evaluate(() => ({ caret: getComputedStyle(document.querySelector('#chat-live .c-caret')).animationName, fase: getComputedStyle(document.querySelector('#chat-live .c-phase-ic')).animationName }));
    await pm.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }]); await sleep(200);
    const semRm = await pm.evaluate(() => { const c = document.querySelector('#chat-live .c-caret'); return c ? getComputedStyle(c).animationName : null; });
    // Esc fecha e o foco volta ao botão do cabeçalho
    await waitIdle(pm); await pm.focus('#chat-text'); await pm.keyboard.press('Escape'); await sleep(500);
    const esc = await pm.evaluate(() => ({ fechado: document.getElementById('chat').hidden, foco: document.activeElement?.id }));
    await pm.close();
    R('CA-V11-reduced-motion-esc', { ok: rm.caret === 'none' && rm.fase === 'none' && esc.fechado && esc.foco === 'chat-btn', reduce: rm, semReduce: semRm, esc });
  }
  await b.close();
  // CA-V5 (servidor): tests/squad/test_conversa_tz_d20.py (+ pergunta real no checklist). CA-V12 (D17 CA-1,2,3,10,18,19,21,23):
  // tests/ui/d17-conversa.js. Resultado desta execução: tests/ui/d20-conversa-visual-result.json.
  out.ok = Object.values(out.results).every(r => r.ok);
  console.log(JSON.stringify(out, null, 2));
  process.exit(out.ok ? 0 : 1);
})().catch(e => { console.log(JSON.stringify({ fatal: String(e && e.stack || e), ...out }, null, 2)); process.exit(2); });
