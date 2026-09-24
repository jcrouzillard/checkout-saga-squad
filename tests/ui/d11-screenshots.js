// D11 (642a73cb38e5) — faixa de consumo da IA no Squad Control. Executado em Docker:
// D13 (efe387a35d71): migrado para a navegação por rotas de hash (menu único; sem .tabs). As telas antigas são
//   abertas pelos aliases da §5 do contrato (#execucoes, #/decisoes, …) e o formulário fica em #/demandas/nova.
//   Montagens usadas no D13: -v "$DATA:/work/data" -v "$CODEX_HOME_FIX:/work/codex" (FIX = server.py com SQUAD_ROOT_DATA=$DATA e
//   CODEX_HOME=$CODEX_HOME_FIX; a pasta sessions/2026/09/23 precisa existir). REAL = dados reais, somente leitura.
//   docker run --rm --add-host=host.docker.internal:host-gateway -e NODE_PATH=/home/pptruser/node_modules -v "$PWD/tests/ui:/shots" -v "$WORK:/work" \
//     -w /home/pptruser ghcr.io/puppeteer/puppeteer:latest node /shots/d11-screenshots.js
// REAL = servidor com os dados reais (Codex real, Claude sem statusline); FIX = servidor com SQUAD_ROOT_DATA e
// CODEX_HOME de fixture em /work (snapshot do Claude e rollout do Codex escritos por este script).
const puppeteer = require('puppeteer');
const fs = require('fs');
const REAL = process.env.REAL || 'http://host.docker.internal:7112/';
const FIX = process.env.FIX || 'http://host.docker.internal:7113/';
const SNAP = '/work/data/.squad/usage/claude.json';
const ROLL = '/work/codex/sessions/2026/09/23/rollout-2026-09-23T00-00-00-qa-fixture.jsonl';
const VIEWS = ['execucoes', 'decisoes', 'evidencias', 'politicas', 'agentes', 'demandas'];
// D13: tela antiga -> rota nova (aliases do contrato ui-navegacao-squad-control §5)
const ROUTE = { painel: '#/painel', execucoes: '#execucoes', decisoes: '#/decisoes', evidencias: '#/evidencias', politicas: '#/politicas',
  agentes: '#/agentes', demandas: '#/demandas', nova: '#/demandas/nova', observabilidade: '#/observabilidade' };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const iso = d => d.toISOString().replace(/\.\d+Z$/, 'Z');
const epoch = ms => Math.floor(ms / 1000);

function claudeSnap(five, week, ageMin = 0) {
  const now = Date.now();
  fs.mkdirSync('/work/data/.squad/usage', { recursive: true });
  fs.writeFileSync(SNAP, JSON.stringify({ collectedAt: iso(new Date(now - ageMin * 60e3)),
    fiveHour: { usedPercent: five, resetsAt: iso(new Date(now + 2 * 3600e3 + 51 * 60e3)) },
    sevenDay: { usedPercent: week, resetsAt: iso(new Date(now + 3 * 86400e3)) } }));
}
function codexRollout(p, s) {
  const now = Date.now();
  fs.writeFileSync(ROLL, JSON.stringify({ timestamp: new Date(now).toISOString(), type: 'event_msg', payload: { type: 'token_count',
    rate_limits: { limit_id: 'codex', plan_type: 'plus',
      primary: { used_percent: p, window_minutes: 300, resets_at: epoch(now + 3 * 3600e3) },
      secondary: { used_percent: s, window_minutes: 10080, resets_at: epoch(now + 4 * 86400e3) } } } }) + '\n');
}

(async () => {
  const b = await puppeteer.launch({ args: ['--no-sandbox'] });
  const out = { errors: [] };
  const newPage = async (w, h) => {
    const p = await b.newPage();
    p.on('console', m => { if (m.type() === 'error') out.errors.push(`${w}px console: ${m.text()}`); });
    p.on('pageerror', e => out.errors.push(`${w}px pageerror: ${e.message}`));
    await p.setViewport({ width: w, height: h });
    return p;
  };
  const go = async (p, v) => { await p.evaluate(h => { location.hash = h; }, ROUTE[v]); await sleep(900); };
  const strip = p => p.evaluate(() => {
    const el = document.querySelector('#ai-usage'); const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    const de = document.documentElement;
    // D14 (§6.1): a faixa fica sticky logo abaixo do cabeçalho fixo (top: var(--hdr-h)), não mais no topo 0.
    const hdr = document.querySelector('#hdr'), hr = hdr.getBoundingClientRect();
    return { visible: !el.hidden && cs.display !== 'none' && r.height > 0, top: Math.round(r.top), height: Math.round(r.height),
      stickyTop: Math.round(parseFloat(cs.top) || 0), hdrBottom: Math.round(hr.bottom), hdrSticky: getComputedStyle(hdr).position === 'sticky',
      position: cs.position, ariaLive: el.getAttribute('aria-live'), provs: el.querySelectorAll('.u-prov').length,
      provClasses: [...el.querySelectorAll('.u-prov')].map(x => x.className),
      provTops: [...el.querySelectorAll('.u-prov')].map(x => Math.round(x.getBoundingClientRect().top)),
      meters: [...el.querySelectorAll('[role=meter]')].map(m => ({ now: m.getAttribute('aria-valuenow'), min: m.getAttribute('aria-valuemin'),
        max: m.getAttribute('aria-valuemax'), label: m.getAttribute('aria-label'), text: m.getAttribute('aria-valuetext') })),
      text: el.innerText.replace(/\s+/g, ' ').trim(), titles: [...el.querySelectorAll('[title]')].map(x => x.title),
      scrollWidth: de.scrollWidth, clientWidth: de.clientWidth,
      clipped: [...el.querySelectorAll('*')].filter(e => e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== 'visible' && !e.classList.contains('u-meter')).length,
      // D14-QA-4: nenhum conteúdo da página visível acima da faixa (só o cabeçalho, quando fixo, pode estar lá).
      contentAbove: (() => { const hits = []; if (r.top > 1) for (const x of [0.1, 0.5, 0.9]) for (const y of [0.25, 0.75]) {
        const t = document.elementFromPoint(innerWidth * x, r.top * y); if (t && !hdr.contains(t) && t !== de && t !== document.body) hits.push(t.tagName + (t.id ? '#' + t.id : '')); }
        return hits; })() };
  });
  const scrollBottom = async p => { await p.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight)); await sleep(250); };
  const scrollTop = async p => { await p.evaluate(() => window.scrollTo(0, 0)); await sleep(150); };

  // ---------- 1) Dados reais (Codex stale, Claude none): 6 telas + Observabilidade, 1440 e 390 ----------
  for (const [w, h] of [[1440, 1000], [390, 844]]) {
    const p = await newPage(w, h);
    await p.goto(REAL, { waitUntil: 'networkidle2' }); await sleep(2500);
    const res = {};
    for (const v of VIEWS) {
      await go(p, v); await scrollTop(p);
      const s0 = await strip(p);
      await scrollBottom(p);
      const scrolled = await p.evaluate(() => window.scrollY);
      const s1 = await strip(p);
      res[v] = { atTop: { visible: s0.visible, top: s0.top, height: s0.height }, scrolledY: scrolled,
        afterScroll: { visible: s1.visible, top: s1.top, hdrBottom: s1.hdrBottom, stickyTop: s1.stickyTop, hdrSticky: s1.hdrSticky,
          inViewport: s1.top >= 0 && s1.top < 900, belowHeader: Math.abs(s1.top - s1.stickyTop) <= 4 && (!s1.hdrSticky || Math.abs(s1.top - s1.hdrBottom) <= 4),
          contentAbove: s1.contentAbove, noContentAbove: s1.contentAbove.length === 0 },
        position: s0.position, provs: s0.provs, provTops: s0.provTops, sw: s1.scrollWidth, cw: s1.clientWidth, clipped: s1.clipped };
      if (v === 'execucoes' || v === 'demandas') { await p.screenshot({ path: `/shots/d11-real-${v}-scroll-${w}.png` }); }
      await scrollTop(p);
      if (v === 'execucoes') { await p.screenshot({ path: `/shots/d11-real-${v}-${w}.png` }); res.detail = s0; }
    }
    await go(p, 'observabilidade'); await sleep(3500);
    res.observabilidade = await strip(p);
    await p.screenshot({ path: `/shots/d11-real-observabilidade-${w}.png` });
    await go(p, 'execucoes'); await sleep(3500);
    res.backFromObs = (await strip(p)).visible;
    if (w === 390) {
      // cabeçalho/sino/abas usáveis a 390 px
      res.header = await p.evaluate(() => {
        const hit = el => { const r = el.getBoundingClientRect(); const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return { in: r.left >= 0 && r.right <= innerWidth, h: Math.round(r.height), hit: !!t && (t === el || el.contains(t)) }; };
        return { bell: hit(document.querySelector('#bell')), tabs: document.querySelectorAll('.tabs').length, menu: [...document.querySelectorAll('#menu a')].map(b => ({ t: b.textContent.trim(), ...hit(b) })),
          sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
      });
      await p.click('#bell'); await sleep(500);
      res.notif = await p.evaluate(() => { const n = document.querySelector('#notif-panel'); const r = n.getBoundingClientRect(); return { open: !n.hidden, left: Math.round(r.left), right: Math.round(r.right), vw: innerWidth, sw: document.documentElement.scrollWidth }; });
      await p.screenshot({ path: `/shots/d11-real-sino-390.png` });
      await p.click('#bell'); await sleep(300);
      await p.evaluate(() => document.querySelector('#menu a[data-nav="demandas"]').click()); await sleep(700);
      res.tabDemandas = await p.evaluate(() => document.querySelector('#menu a[aria-current="page"]')?.dataset.nav);
    }
    out['real-' + w] = res;
    await p.close();
  }

  // ---------- 2) Fixture: estados do Claude (e Codex fresco com níveis) ----------
  const states = [
    ['fresh', () => { claudeSnap(42.5, 61); codexRollout(83, 96); }],
    ['atencao', () => { claudeSnap(85, 70); codexRollout(12, 30); }],
    ['critico', () => { claudeSnap(97, 99.5); codexRollout(12, 30); }],
    ['stale', () => { claudeSnap(40, 55, 30); codexRollout(12, 30); }],
    ['none', () => { try { fs.unlinkSync(SNAP); } catch (e) {} codexRollout(12, 30); }],
    ['corrompido', () => { fs.writeFileSync(SNAP, '{isto não é json'); codexRollout(12, 30); }],
  ];
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    const p = await newPage(w, h);
    await p.goto(FIX, { waitUntil: 'networkidle2' }); await sleep(1500);
    await go(p, 'execucoes');
    const res = {};
    for (const [name, setup] of states) {
      setup(); await sleep(3800);
      const s = await strip(p);
      const api = await p.evaluate(async () => (await fetch('/api/state').then(r => ({ status: r.status, j: r })).then(async x => ({ status: x.status, usage: (await x.j.json()).usage }))));
      res[name] = { height: s.height, provTops: s.provTops, text: s.text, titles: s.titles, meters: s.meters, provClasses: s.provClasses, sw: s.scrollWidth, cw: s.clientWidth,
        apiStatus: api.status, api: api.usage.providers.map(x => ({ id: x.id, status: x.status, reason: x.reason, five: x.fiveHour && x.fiveHour.usedPercent, week: x.week && x.week.usedPercent })) };
      // G3-D13 ressalva 1: a rota pode rolar a página; o clip do puppeteer é em coordenadas da página, então rola ao topo
      // e soma window.scrollY ao top do getBoundingClientRect (coordenada absoluta da faixa).
      await scrollTop(p);
      const clip = await p.evaluate(() => { const r = document.querySelector('#ai-usage').getBoundingClientRect(); return { x: 0, y: Math.max(0, r.top + window.scrollY - 4), width: innerWidth, height: r.height + 8 }; });
      await p.screenshot({ path: `/shots/d11-claude-${name}-${w}.png`, clip });
    }
    out['fix-' + w] = res;
    await p.close();
  }

  // ---------- 3) Altura da faixa por estado x largura (CA8: <= 72 px a partir de 600 px; 390 px só medido) ----------
  // Revalidação D11-QA-1: todos os estados (fresh/atencao/critico/stale/none + texto mais longo) em 1440/900/700/600/390.
  const hstates = [['longo', () => { claudeSnap(85, 97); codexRollout(83, 96); }], ...states.filter(s => s[0] !== 'corrompido'),
    ['stale+none', () => { claudeSnap(40, 55, 30); fs.writeFileSync(ROLL, ''); }]];
  out.heights = {};
  for (const w of [1440, 900, 700, 601, 600, 390]) {
    const p = await newPage(w, 900);
    await p.goto(FIX, { waitUntil: 'networkidle2' }); await sleep(1200);
    out.heights[w] = {};
    for (const [name, setup] of hstates) {
      setup(); await sleep(3800);
      const s = await strip(p);
      out.heights[w][name] = { height: s.height, stacked: s.provTops.length === 2 && s.provTops[0] !== s.provTops[1], overflowX: s.scrollWidth > s.clientWidth,
        text: s.text, titles: s.titles, valuetext: s.meters.map(m => m.text) };
      if (name === 'longo' && [600, 700, 900].includes(w)) { await scrollTop(p); await p.screenshot({ path: `/shots/d11-largura-${w}.png`, clip: await p.evaluate(() => { const r = document.querySelector('#ai-usage').getBoundingClientRect(); return { x: 0, y: 0, width: innerWidth, height: r.bottom + window.scrollY + 8 }; }) }); }
    }
    await p.close();
  }

  // ---------- 4) Foco e texto digitado preservados durante >= 2 ciclos; faixa atualiza ----------
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    claudeSnap(30, 50); codexRollout(12, 30);
    const p = await newPage(w, h);
    await p.goto(FIX, { waitUntil: 'networkidle2' }); await sleep(1500);
    await go(p, 'nova');
    await p.focus('#dem-title'); await p.keyboard.type('Titulo digitado pelo QA');
    await p.focus('#dem-detail'); await p.keyboard.type('Detalhe em edição — não pode sumir');
    const before = await strip(p);
    // D14-QA-3: do write do snapshot no disco até o medidor do Claude mostrar o novo valor (meta <= 3 s).
    const claudeNow = () => p.evaluate(() => [...document.querySelectorAll('#ai-usage [role=meter]')].find(m => /claude/i.test(m.getAttribute('aria-label') || ''))?.getAttribute('aria-valuenow'));
    const lat = [];
    for (const v of [88, 64, 91]) {
      claudeSnap(v, 50); const t0 = Date.now(); let ms = null;
      while (Date.now() - t0 < 16000) { if (+(await claudeNow()) === v) { ms = Date.now() - t0; break; } await sleep(50); }
      lat.push(ms);
    }
    claudeSnap(88, 50); await sleep(3500);
    const mid = await strip(p);
    await p.keyboard.type(' +mais');
    claudeSnap(96, 51); await sleep(3500);
    const after = await strip(p);
    const f = await p.evaluate(() => ({ active: document.activeElement && document.activeElement.id, title: document.querySelector('#dem-title').value, detail: document.querySelector('#dem-detail').value }));
    out['focus-' + w] = { usageLatencyMs: lat, before: before.meters.map(m => m.now), mid: mid.meters.map(m => m.now), after: after.meters.map(m => m.now), ...f };
    await p.screenshot({ path: `/shots/d11-foco-demanda-${w}.png` });
    await p.close();
  }
  claudeSnap(42.5, 61); codexRollout(83, 96);
  console.log(JSON.stringify(out, null, 1));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
