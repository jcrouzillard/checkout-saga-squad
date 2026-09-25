// D17 (e1d6eae16073) — conversa com o Orquestrador: fluxo da UI ponta a ponta (QA). Checklist: tests/ui/checklist-conversa-d17.md.
// Servidor do WORKTREE com dados TEMPORÁRIOS (nunca o :7070 nem o log real) e runner SIMULADO
// (tests/squad/conversa_fake_runner.py); os dados vêm do harness de tests/squad/test_conversa_d17.py (make_data com
// demandas semeadas: B1 puro a1…, B2 c1…, obsoleta d1…). Dois servidores: um com o runner simulado e um sem runner
// (estado "indisponível"):
//   S=<scratch>; python3 -c "import sys,pathlib; sys.path.insert(0,'tests/squad'); import test_conversa_d17 as h; \
//     h.make_data(pathlib.Path('$S/ui-data')); h.make_data(pathlib.Path('$S/ui-data-503'), with_seed=False)"
//   SQUAD_ROOT_DATA=$S/ui-data SQUAD_LOG=$S/ui-data/docs/squad/memory/decisions.jsonl SQUAD_TRANSCRIPTS=$S/trans \
//     SQUAD_TESTENV_PROBE=0 SQUAD_TESTENV_SPAWN=0 SQUAD_CHAT_RUNNER=fake SQUAD_CHAT_FAKE=$PWD/tests/squad/conversa_fake_runner.py \
//     SQUAD_CHAT_TIMEOUT_S=6 python3 tools/squad/server.py --port 7371 &
//   (idem com SQUAD_ROOT_DATA=$S/ui-data-503 e SQUAD_CHAT_FAKE=/nao/existe na porta 7372)
//   docker run --rm --add-host=host.docker.internal:host-gateway -e NODE_PATH=/home/pptruser/node_modules \
//     -e PORT=7371 -e PORT2=7372 -v "$PWD/tests/ui:/shots" -v "$S/axe.min.js:/work/axe.min.js:ro" \
//     -w /home/pptruser ghcr.io/puppeteer/puppeteer:latest node /shots/d17-conversa.js > $S/d17-ui.json
// As rotas /api/conversas* exigem Host local (anti-DNS-rebinding): repasse TCP DENTRO do container
// (127.0.0.1:PORT → host.docker.internal:PORT). O repasse guarda os sockets para derrubar o SSE no meio do turno.
const puppeteer = require('puppeteer');
const net = require('net');
const fs = require('fs');
const PORT = Number(process.env.PORT || 7371), PORT2 = Number(process.env.PORT2 || 7372);
const BASE = `http://127.0.0.1:${PORT}/`, BASE2 = `http://127.0.0.1:${PORT2}/`;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = { results: {}, errors: [] };
const R = (k, v) => { out.results[k] = v; console.error(`[${k}] ${JSON.stringify(v).slice(0, 600)}`); };
const sockets = new Set();
const relay = port => new Promise(res => net.createServer(c => {
  const u = net.connect(port, 'host.docker.internal'); sockets.add(c); sockets.add(u);
  c.pipe(u).pipe(c); const done = () => { sockets.delete(c); sockets.delete(u); };
  u.on('error', () => c.destroy()); c.on('error', () => u.destroy()); c.on('close', done);
}).listen(port, '127.0.0.1', res));
const dropAll = () => { for (const s of [...sockets]) s.destroy(); };

(async () => {
  await relay(PORT); await relay(PORT2);
  const axe = fs.existsSync('/work/axe.min.js') ? fs.readFileSync('/work/axe.min.js', 'utf8') : null;
  const b = await puppeteer.launch({ args: ['--no-sandbox'] });
  const page = async (w, theme = 'light', base = BASE, hash = '#/painel') => {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: w > 500 ? 900 : 844, deviceScaleFactor: 1 });
    p.on('pageerror', e => out.errors.push(String(e).slice(0, 300)));
    p.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|EventSource|net::ERR/.test(m.text())) out.errors.push(m.text().slice(0, 300)); });
    await p.evaluateOnNewDocument(t => {
      try { localStorage.setItem('sc-theme', t); } catch (e) { /* */ }
      window.__live = []; window.__alert = [];
      document.addEventListener('DOMContentLoaded', () => {
        const watch = (id, arr) => { const el = document.getElementById(id); if (el) new MutationObserver(() => { const t = el.textContent.trim(); if (t) arr.push(t); }).observe(el, { childList: true, characterData: true, subtree: true }); };
        watch('sr-live', window.__live); watch('sr-alert', window.__alert);
      });
    }, theme);
    await p.goto(base + hash, { waitUntil: 'domcontentloaded' });
    await p.waitForFunction(() => typeof state !== 'undefined' && state, { timeout: 60000 }); await sleep(500);
    return p;
  };
  const st = p => p.evaluate(() => ({
    hash: location.hash, open: !document.getElementById('chat').hidden, focus: document.activeElement?.id || document.activeElement?.tagName,
    status: document.getElementById('chat-status').hidden ? '' : document.getElementById('chat-status').textContent.trim().slice(0, 200),
    msgs: document.querySelectorAll('#chat-msgs > li.c-msg').length, hscroll: document.documentElement.scrollWidth > window.innerWidth,
    textDisabled: document.getElementById('chat-text').disabled, sendDisabled: document.getElementById('chat-send').disabled,
    stopVisible: !document.getElementById('chat-stop').hidden,
  }));
  const typeSend = async (p, t) => { await p.focus('#chat-text'); await p.$eval('#chat-text', e => { e.value = ''; }); await p.type('#chat-text', t); await p.keyboard.press('Enter'); };
  const waitIdle = (p, ms = 20000) => p.waitForFunction(() => document.getElementById('chat-stop').hidden && !document.getElementById('chat-send').disabled, { timeout: ms });
  const liveText = p => p.evaluate(() => document.querySelector('#chat-live .bub')?.textContent || '');
  const lastBubble = p => p.evaluate(() => [...document.querySelectorAll('#chat-msgs > li.c-msg')].map(li => li.textContent).at(-1) || '');
  const shot = (p, n) => p.screenshot({ path: `/shots/d17-${n}.png` });
  const api = (p, m, u, body) => p.evaluate(async (m, u, body) => { const r = await fetch(u, { method: m, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }); return { s: r.status, j: await r.json().catch(() => null) }; }, m, u, body);

  // ===== CA-1: o botão do cabeçalho abre o painel em várias telas (1440 e 390)
  for (const w of [1440, 390]) {
    const p = await page(w);
    const res = {};
    for (const h of ['#/painel', '#/demandas/D16', '#/squad']) {
      await p.evaluate(h => { location.hash = h; }, h); await sleep(700);
      if ((await st(p)).open) { await p.keyboard.press('Escape'); await sleep(300); }
      await p.click('#chat-btn'); await sleep(900);
      const s = await st(p);
      res[h] = { open: s.open, focus: s.focus, conversa: /conversa=(c-[0-9a-f]{12}|nova)/.test(s.hash), hscroll: s.hscroll };
      if (h === '#/painel') await shot(p, `aberto-${w}`);
      await p.keyboard.press('Escape'); await sleep(400);
      res[h].escFocus = (await st(p)).focus; res[h].closed = !(await st(p)).open;
    }
    const btn = await p.$eval('#chat-btn', e => ({ label: e.getAttribute('aria-label'), text: e.textContent.trim(), h: Math.round(e.getBoundingClientRect().height), w: Math.round(e.getBoundingClientRect().width) }));
    const menu = await p.evaluate(() => [...document.querySelectorAll('#menu a')].length);
    R(`CA1-${w}`, { ok: Object.values(res).every(r => r.open && r.focus === 'chat-text' && r.conversa && r.closed && r.escFocus === 'chat-btn' && !r.hscroll), res, btn, menu });
    await p.close();
  }

  // ===== CA-2 + estados: vazio, enviando/pensando ≤300ms, consultando, respondendo, concluída; aria-live
  let p = await page(1440);
  await p.goto(BASE + '#/painel?conversa=nova', { waitUntil: 'domcontentloaded' }); await sleep(1200);
  const vazio = await p.evaluate(() => ({ sug: document.querySelectorAll('[data-chat-sug]').length, aviso: document.getElementById('chat-sub')?.textContent.trim() || document.getElementById('chat-hint')?.textContent.trim() }));
  await shot(p, 'vazio-1440');
  await p.evaluate(() => { window.__live.length = 0; window.__alert.length = 0; });
  await p.focus('#chat-text'); await p.type('#chat-text', 'Qual o estado da D16? LER');
  const t0 = Date.now(); await p.keyboard.press('Enter');
  const humanNow = await p.evaluate(() => [...document.querySelectorAll('#chat-msgs > li.c-msg')].some(li => /Qual o estado da D16/.test(li.textContent)));
  await p.waitForFunction(() => /Pensando|Enviando/.test(document.getElementById('chat-status').textContent + (document.getElementById('chat-live')?.textContent || '')), { timeout: 2000 });
  const pensandoMs = Date.now() - t0;
  const lendo = await p.waitForFunction(() => /Lendo|Consultando/.test(document.getElementById('chat-status').textContent + (document.getElementById('chat-live')?.textContent || '')), { timeout: 5000 }).then(() => true).catch(() => false);
  const lendoTxt = await p.evaluate(() => (document.getElementById('chat-status').textContent + ' ' + (document.getElementById('chat-live')?.textContent || '')).replace(/\s+/g, ' ').trim().slice(0, 160));
  await p.waitForFunction(() => /Respondendo/.test(document.getElementById('chat-status').textContent + (document.getElementById('chat-live')?.textContent || '')), { timeout: 5000 }).catch(() => {});
  const durante = await st(p);
  await shot(p, 'respondendo-1440');
  await waitIdle(p);
  const fim = await st(p);
  const bubble = await lastBubble(p);
  const lives = await p.evaluate(() => ({ live: [...window.__live], alert: [...window.__alert] }));
  R('CA2-estados', { ok: humanNow && pensandoMs <= 300 && lendo && durante.textDisabled !== undefined && fim.msgs === 2 && /Resposta simulada/.test(bubble) && !/\*\*/.test(bubble),
    vazio, humanNow, pensandoMs, lendo, lendoTxt, durante, fim, bubble: bubble.slice(0, 200), model: /claude-fake-1-20260901/.test(bubble) });
  R('CA23-aria-live', { ok: lives.live.filter(t => /Resposta simulada|Trecho/.test(t)).length === 0 && lives.live.some(t => /Resposta do Orquestrador recebida/.test(t)), ...lives,
    roleLog: await p.$eval('#chat-msgs', e => e.getAttribute('role')), dialog: await p.$eval('#chat', e => [e.getAttribute('role'), e.getAttribute('aria-modal'), e.getAttribute('aria-labelledby')]) });
  const linkD = await p.evaluate(() => [...document.querySelectorAll('#chat-msgs a')].map(a => a.getAttribute('href')).filter(h => /D17/.test(h || '')));
  R('CA21-balao', { ok: /claude-fake-1-20260901/.test(bubble), linkDemanda: linkD });

  // ===== CA-3: 3 turnos, F5, fechar e reabrir com ?conversa=
  await typeSend(p, 'segunda pergunta'); await waitIdle(p);
  await typeSend(p, 'terceira pergunta'); await waitIdle(p);
  const antes = await st(p);
  const order = async q => q.evaluate(() => [...document.querySelectorAll('#chat-msgs > li.c-msg')].map(li => li.classList.contains('human') || /humano/.test(li.className) ? 'H' : 'O').join(''));
  const ord1 = await order(p);
  await p.reload({ waitUntil: 'domcontentloaded' }); await sleep(1500);
  const depois = await st(p); const ord2 = await order(p);
  const cid = (depois.hash.match(/conversa=(c-[0-9a-f]{12})/) || [])[1];
  await p.close();
  const ctx = await b.createBrowserContext();
  const p2 = await ctx.newPage(); await p2.setViewport({ width: 1440, height: 900 });
  await p2.goto(BASE + `#/demandas/D16?conversa=${cid}`, { waitUntil: 'domcontentloaded' }); await sleep(2000);
  const reaberto = await st(p2);
  await p2.close(); await ctx.close();
  R('CA3-historico', { ok: antes.msgs === 6 && depois.msgs === 6 && depois.open && reaberto.msgs === 6 && reaberto.open && ord1 === ord2, antes: antes.msgs, depois: depois.msgs, reaberto: reaberto.msgs, ord1, ord2, cid });

  // ===== reconexão: (a) SSE derrubado no meio do turno → polling; (b) F5 no meio do turno
  p = await page(1440, 'light', BASE, `#/painel?conversa=${cid}`); await sleep(800);
  await typeSend(p, 'LENTO primeira reconexão');
  await p.waitForFunction(() => (document.querySelector('#chat-live .bub')?.textContent || '').length > 40, { timeout: 8000 });
  const antesDrop = (await liveText(p)).length;
  dropAll();
  await waitIdle(p, 25000);
  const recA = await lastBubble(p);
  const srvA = await api(p, 'GET', `/api/conversas/${cid}`);
  const lastA = srvA.j.messages.filter(m => m.t === 'msg').at(-1);
  const dupA = (recA.match(/Trecho longo/g) || []).length;
  R('reconexao-sse-caiu', { ok: lastA.status === 'ok' && dupA === 3 && recA.includes(lastA.text.slice(-30).trim()), antesDrop, dupA, status: lastA.status });
  await typeSend(p, 'LENTO segunda reconexão');
  await p.waitForFunction(() => (document.querySelector('#chat-live .bub')?.textContent || '').length > 40, { timeout: 8000 });
  await p.reload({ waitUntil: 'domcontentloaded' }); await sleep(600);
  const meio = await st(p);
  await waitIdle(p, 25000);
  const recB = await lastBubble(p);
  const dupB = (recB.match(/Trecho longo/g) || []).length;
  R('reconexao-f5-no-meio', { ok: dupB === 3 && meio.open, meioStop: meio.stopVisible, dupB });

  // ===== estados de erro, cancelada, tempo esgotado, ocupado
  await typeSend(p, 'FALHAR agora'); await waitIdle(p);
  const erro = await st(p);
  const retry = await p.$('[data-chat-retry], [data-chat-retry-text]');
  const alertErr = await p.evaluate(() => [...window.__alert]);
  R('estado-erro', { ok: /Erro|indispon/i.test(erro.status) && !!retry, status: erro.status, retry: !!retry, alert: alertErr.slice(-2) });
  if (retry) { await retry.click(); await sleep(400); await waitIdle(p); R('tentar-de-novo', { status: (await st(p)).status, msgs: (await st(p)).msgs }); }
  await typeSend(p, 'DORMIR e depois pare');
  await p.waitForFunction(() => !document.getElementById('chat-stop').hidden, { timeout: 5000 });
  await p.waitForFunction(() => /parcial/.test(document.querySelector('#chat-live .bub')?.textContent || ''), { timeout: 8000 }).catch(() => {});
  const dur = await st(p);
  // teclado: Tab até "Parar" e Enter
  await p.focus('#chat-stop'); await p.keyboard.press('Enter');
  await waitIdle(p);
  const canc = await st(p);
  const flag = await p.evaluate(() => [...document.querySelectorAll('.c-msg .flag')].map(e => e.textContent.trim()).at(-1));
  // §9 diz "desabilitada durante o turno", mas também "foco permanece na caixa de texto": a UI desabilita Enviar e
  // mantém a caixa editável (rascunho). Registrado como observação no checklist, não como condição de `ok`.
  R('estado-cancelada', { ok: /cancelada/i.test(canc.status + ' ' + flag) && dur.sendDisabled && dur.stopVisible, status: canc.status, flag, textDisabledDuring: dur.textDisabled, sendDisabledDuring: dur.sendDisabled });
  await typeSend(p, 'DORMIR até esgotar'); await waitIdle(p, 20000);
  const esg = await st(p);
  const flag2 = await p.evaluate(() => [...document.querySelectorAll('.c-msg .flag')].map(e => e.textContent.trim()).at(-1));
  R('estado-tempo-esgotado', { ok: /tempo esgotado/i.test(esg.status + ' ' + flag2), status: esg.status, flag: flag2 });
  // ocupado: outra aba envia enquanto esta responde
  await typeSend(p, 'DORMIR ocupar o servidor');
  await p.waitForFunction(() => !document.getElementById('chat-stop').hidden, { timeout: 5000 });
  const pb = await page(1440, 'light', BASE, '#/painel?conversa=nova'); await sleep(800);
  await typeSend(pb, 'teste ocupado'); await sleep(1200);
  const oc = await st(pb);
  const ocLink = await pb.$eval('#chat-status a', a => a.getAttribute('href')).catch(() => null);
  R('estado-ocupado', { ok: /Ocupado/.test(oc.status) && !!ocLink && ocLink.includes(cid), status: oc.status, link: ocLink, rascunho: await pb.$eval('#chat-text', e => e.value) });
  await pb.close(); await p.focus('#chat-stop'); await p.keyboard.press('Enter'); await waitIdle(p, 25000);
  // lista de conversas
  await p.click('#chat-list-btn'); await sleep(600);
  const lista = await p.$$eval('#chat-list a', as => as.map(a => a.textContent.replace(/\s+/g, ' ').trim()).slice(0, 5));
  await shot(p, 'lista-1440');
  await p.keyboard.press('Escape'); await sleep(200);
  R('lista-conversas', { ok: lista.length >= 2, lista });
  await p.close();

  // ===== indisponível (servidor sem runner)
  p = await page(1440, 'light', BASE2, '#/painel?conversa=nova'); await sleep(900);
  const ind0 = await st(p);
  await typeSend(p, 'está aí?'); await sleep(1500);
  const ind = await st(p);
  await shot(p, 'indisponivel-1440');
  R('estado-indisponivel', { ok: /indispon/i.test(ind.status + ind0.status) && /claude|--version|fake/.test(ind.status + ind0.status), antes: ind0.status, depois: ind.status, msgs: ind.msgs });
  await p.close();

  // ===== destravar: cartão confirmar (B1 OVERRIDE), descartar (B2 APPROVE), obsoleta; teclado; dupla confirmação
  for (const [w, theme] of [[1440, 'light'], [390, 'dark']]) {
    p = await page(w, theme, BASE, '#/painel?conversa=nova'); await sleep(900);
    const live = await api(p, 'GET', '/api/live');
    const al = d => live.j.alerts.find(a => a.demand === d && a.gate)?.id;
    const res = {};
    if (w === 1440) {
      await typeSend(p, 'PROPOR:' + JSON.stringify({ alerta: al('a1'.repeat(6)), acao: 'OVERRIDE', nota: 'seguir: ressalva documental' })); await waitIdle(p);
      const card = await p.$eval('.c-prop:last-of-type', e => ({ text: e.textContent.replace(/\s+/g, ' ').slice(0, 400), danger: e.classList.contains('danger'), role: e.getAttribute('role') })).catch(() => null);
      const bloco = await p.evaluate(() => [...document.querySelectorAll('#chat-msgs > li.orquestrador .bub')].some(e => /```|destravar\s*\{|"acao"/.test(e.textContent)));
      await shot(p, `proposta-${w}${theme === 'dark' ? '-escuro' : ''}`);
      await p.$eval('[data-chat-note]', e => { e.focus(); e.value = ''; });
      await p.type('[data-chat-note]', 'nota editada no painel');
      await p.evaluate(() => [...document.querySelectorAll('[data-chat-note]')].at(-1).dispatchEvent(new Event('input', { bubbles: true })));
      await p.focus('[data-chat-confirm]'); await p.keyboard.press('Enter'); await sleep(1500);
      const done = await p.evaluate(() => [...document.querySelectorAll('.c-prop')].at(-1).textContent.replace(/\s+/g, ' ').slice(-200));
      const logged = await api(p, 'GET', '/api/state');
      const ev = (logged.j.log || []).filter(e => e.via === 'conversa').at(-1) || null;
      const again = await api(p, 'POST', `/api/conversas/${(await st(p)).hash.match(/c-[0-9a-f]{12}/)[0]}/propostas/${(await p.$eval('.c-prop h4', h => h.id.replace('cp-h-', '')))}/confirmar`, {});
      res.confirmar = { ok: !!card && card.danger && /Seguir mesmo assim \(assumo o risco\)/.test(card.text) && !bloco && /Confirmada/.test(done) && again.s === 409,
        card, bloco, done, ev: ev && { detail: ev.detail, rec: ev.recommendation, via: ev.via }, segunda: again.s };
      await shot(p, `proposta-confirmada-${w}`);
    }
    await typeSend(p, 'PROPOR:' + JSON.stringify({ alerta: al('c1'.repeat(6)), acao: 'APPROVE', nota: 'aceito' })); await waitIdle(p);
    const beforeDisc = await api(p, 'GET', '/api/state');
    await p.evaluate(() => [...document.querySelectorAll('[data-chat-discard]')].at(-1).click()); await sleep(1200);
    const disc = await p.evaluate(() => [...document.querySelectorAll('.c-prop')].at(-1).textContent.replace(/\s+/g, ' ').slice(-160));
    const afterDisc = await api(p, 'GET', '/api/state');
    res.descartar = { ok: /Descartada/.test(disc) && (beforeDisc.j.log || []).length === (afterDisc.j.log || []).length, disc };
    if (w === 1440) {
      await typeSend(p, 'PROPOR:' + JSON.stringify({ alerta: al('d1'.repeat(6)), acao: 'OVERRIDE' })); await waitIdle(p);
      await api(p, 'POST', '/api/human', { action: 'OVERRIDE', gate: 'G2', demand: 'd1'.repeat(6), note: 'decidido pelo painel' });
      await p.evaluate(() => [...document.querySelectorAll('[data-chat-confirm]')].at(-1).click()); await sleep(1500);
      const obs = await p.evaluate(() => [...document.querySelectorAll('.c-prop')].at(-1).textContent.replace(/\s+/g, ' ').slice(-220));
      res.obsoleta = { ok: /Obsoleta|estado mudou/.test(obs), obs };
      await shot(p, `proposta-obsoleta-${w}`);
      await typeSend(p, 'PROPOR:' + JSON.stringify({ alerta: al('c3'.repeat(6)), acao: 'RETURN' })); await waitIdle(p);
      const inval = await p.evaluate(() => [...document.querySelectorAll('.c-prop')].at(-1).textContent.replace(/\s+/g, ' ').slice(0, 200));
      res.invalida = { ok: /não acionável|não pode ser feito/.test(inval) && !(/Seguir|Confirmar/.test(inval)), inval };
    } else {
      await shot(p, `proposta-390-escuro`);
      const small = await p.evaluate(() => [...document.querySelectorAll('#chat button, #chat a.btn, #chat textarea, #chat-btn')].filter(e => e.offsetParent && e.getBoundingClientRect().height < 44).map(e => e.id || e.textContent.trim().slice(0, 24)));
      res.alvos390 = { ok: small.length === 0, small, hscroll: (await st(p)).hscroll };
    }
    if (axe) {
      await p.addScriptTag({ content: axe });
      const ax = await p.evaluate(async () => { const r = await axe.run('#chat', { runOnly: ['wcag2a', 'wcag2aa'] }); return r.violations.map(v => ({ id: v.id, n: v.nodes.length, ex: v.nodes.slice(0, 2).map(n => n.target.join(' ')) })); });
      res.axe = { ok: ax.length === 0, ax };
    }
    R(`destravar-${w}-${theme}`, { ok: Object.values(res).every(x => x.ok), ...res });
    await p.close();
  }

  // ===== teclado completo + tema escuro 1440 + Shift+Enter
  p = await page(1440, 'dark'); await sleep(500);
  await p.focus('#chat-btn'); await p.keyboard.press('Enter'); await sleep(900);
  const k1 = await st(p);
  await p.keyboard.type('linha 1'); await p.keyboard.down('Shift'); await p.keyboard.press('Enter'); await p.keyboard.up('Shift'); await p.keyboard.type('linha 2');
  const multi = await p.$eval('#chat-text', e => e.value);
  await p.keyboard.press('Enter'); await waitIdle(p);
  const k2 = await st(p);
  await shot(p, 'escuro-1440');
  await p.keyboard.press('Escape'); await sleep(400);
  const k3 = await st(p);
  const count = await p.evaluate(() => document.getElementById('chat-count')?.textContent.trim());
  R('CA23-teclado', { ok: k1.open && k1.focus === 'chat-text' && multi === 'linha 1\nlinha 2' && k2.focus === 'chat-text' && !k3.open && k3.focus === 'chat-btn',
    k1: [k1.open, k1.focus], multi, k2focus: k2.focus, k3: [k3.open, k3.focus], count });
  if (axe) {
    await p.focus('#chat-btn'); await p.keyboard.press('Enter'); await sleep(800);
    await p.addScriptTag({ content: axe });
    const ax = await p.evaluate(async () => { const r = await axe.run('#chat', { runOnly: ['wcag2aa'] }); return r.violations.map(v => ({ id: v.id, n: v.nodes.length, ex: v.nodes.slice(0, 2).map(n => n.target.join(' ')) })); });
    R('CA23-contraste-escuro', { ok: ax.length === 0, ax });
  }
  await p.close();
  // 390 claro: cabeçalho só ícone com aria-label
  p = await page(390, 'light');
  const b390 = await p.$eval('#chat-btn', e => ({ label: e.getAttribute('aria-label'), visibleText: e.innerText.trim(), h: Math.round(e.getBoundingClientRect().height) }));
  await shot(p, 'cabecalho-390');
  await p.click('#chat-btn'); await sleep(900);
  const s390 = await st(p);
  await shot(p, 'aberto-390-claro');
  R('390', { ok: !!b390.label && b390.h >= 44 && !s390.hscroll && s390.open, b390, hscroll: s390.hscroll });
  await p.close();

  R('pageErrors', out.errors);
  console.log(JSON.stringify(out, null, 2));
  await Promise.race([b.close(), sleep(5000)]); process.exit(0);
})().catch(e => { console.error('FALHOU', e); console.log(JSON.stringify(out, null, 2)); process.exit(1); });
