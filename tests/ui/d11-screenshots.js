// D11 (642a73cb38e5) — faixa de consumo da IA no Squad Control. Executado em Docker:
//   docker run --rm --add-host=host.docker.internal:host-gateway -v "$PWD/tests/ui:/shots" -v "$WORK:/work" \
//     -w /home/pptruser ghcr.io/puppeteer/puppeteer:latest node /shots/d11-screenshots.js
// REAL = servidor com os dados reais (Codex real, Claude sem statusline); FIX = servidor com SQUAD_ROOT_DATA e
// CODEX_HOME de fixture em /work (snapshot do Claude e rollout do Codex escritos por este script).
const puppeteer = require('puppeteer');
const fs = require('fs');
const REAL = process.env.REAL || 'http://host.docker.internal:7098/';
const FIX = process.env.FIX || 'http://host.docker.internal:7099/';
const SNAP = '/work/data/.squad/usage/claude.json';
const ROLL = '/work/codex/sessions/2026/09/23/rollout-2026-09-23T00-00-00-qa-fixture.jsonl';
const VIEWS = ['execucoes', 'decisoes', 'evidencias', 'politicas', 'agentes', 'demandas'];
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
  const go = async (p, v) => { await p.evaluate(v => { const el = document.querySelector(`nav a[data-view="${v}"]`); el && el.click(); }, v); await sleep(700); };
  const strip = p => p.evaluate(() => {
    const el = document.querySelector('#ai-usage'); const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    const de = document.documentElement;
    return { visible: !el.hidden && cs.display !== 'none' && r.height > 0, top: Math.round(r.top), height: Math.round(r.height),
      position: cs.position, ariaLive: el.getAttribute('aria-live'), provs: el.querySelectorAll('.u-prov').length,
      provClasses: [...el.querySelectorAll('.u-prov')].map(x => x.className),
      provTops: [...el.querySelectorAll('.u-prov')].map(x => Math.round(x.getBoundingClientRect().top)),
      meters: [...el.querySelectorAll('[role=meter]')].map(m => ({ now: m.getAttribute('aria-valuenow'), min: m.getAttribute('aria-valuemin'),
        max: m.getAttribute('aria-valuemax'), label: m.getAttribute('aria-label'), text: m.getAttribute('aria-valuetext') })),
      text: el.innerText.replace(/\s+/g, ' ').trim(), titles: [...el.querySelectorAll('[title]')].map(x => x.title),
      scrollWidth: de.scrollWidth, clientWidth: de.clientWidth,
      clipped: [...el.querySelectorAll('*')].filter(e => e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow !== 'visible' && !e.classList.contains('u-meter')).length };
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
        afterScroll: { visible: s1.visible, top: s1.top, inViewport: s1.top >= 0 && s1.top < 5 },
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
        return { bell: hit(document.querySelector('#bell')), tabs: [...document.querySelectorAll('.tabs button')].map(b => ({ t: b.textContent, ...hit(b) })),
          sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
      });
      await p.click('#bell'); await sleep(500);
      res.notif = await p.evaluate(() => { const n = document.querySelector('#notif-panel'); const r = n.getBoundingClientRect(); return { open: !n.hidden, left: Math.round(r.left), right: Math.round(r.right), vw: innerWidth, sw: document.documentElement.scrollWidth }; });
      await p.screenshot({ path: `/shots/d11-real-sino-390.png` });
      await p.click('#bell'); await sleep(300);
      await p.evaluate(() => document.querySelector('.tabs button[data-tab="demandas"]').click()); await sleep(700);
      res.tabDemandas = await p.evaluate(() => document.querySelector('nav a.on')?.dataset.view);
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
      const clip = await p.evaluate(() => { const r = document.querySelector('#ai-usage').getBoundingClientRect(); return { x: 0, y: Math.max(0, r.top - 4), width: innerWidth, height: r.height + 8 }; });
      await p.screenshot({ path: `/shots/d11-claude-${name}-${w}.png`, clip });
    }
    out['fix-' + w] = res;
    await p.close();
  }

  // ---------- 3) Altura da faixa entre 600 e 900 px (e 1440) no estado de texto mais longo ----------
  claudeSnap(85, 97); codexRollout(83, 96);
  out.heights = {};
  for (const w of [600, 601, 700, 800, 900, 1024, 1440]) {
    const p = await newPage(w, 900);
    await p.goto(FIX, { waitUntil: 'networkidle2' }); await sleep(1500);
    const s = await strip(p);
    out.heights[w] = { height: s.height, stacked: s.provTops.length === 2 && s.provTops[0] !== s.provTops[1], sw: s.scrollWidth, cw: s.clientWidth };
    if ([600, 700, 900].includes(w)) await p.screenshot({ path: `/shots/d11-largura-${w}.png`, clip: await p.evaluate(() => { const r = document.querySelector('#ai-usage').getBoundingClientRect(); return { x: 0, y: 0, width: innerWidth, height: r.bottom + 8 }; }) });
    await p.close();
  }
  // stale + none também medidos (textos de alerta)
  claudeSnap(40, 55, 30); fs.writeFileSync(ROLL, '');
  for (const w of [700, 900, 1440]) {
    const p = await newPage(w, 900);
    await p.goto(FIX, { waitUntil: 'networkidle2' }); await sleep(1500);
    const s = await strip(p);
    out.heights['stale+none-' + w] = { height: s.height, text: s.text };
    await p.close();
  }

  // ---------- 4) Foco e texto digitado preservados durante >= 2 ciclos; faixa atualiza ----------
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    claudeSnap(30, 50); codexRollout(12, 30);
    const p = await newPage(w, h);
    await p.goto(FIX, { waitUntil: 'networkidle2' }); await sleep(1500);
    await go(p, 'demandas');
    await p.focus('#dem-title'); await p.keyboard.type('Titulo digitado pelo QA');
    await p.focus('#dem-detail'); await p.keyboard.type('Detalhe em edição — não pode sumir');
    const before = await strip(p);
    claudeSnap(88, 50);           // muda o valor do Claude
    await sleep(7000);             // >= 2 ciclos de 3 s
    const mid = await strip(p);
    await p.keyboard.type(' +mais');
    claudeSnap(96, 51); await sleep(3500);
    const after = await strip(p);
    const f = await p.evaluate(() => ({ active: document.activeElement && document.activeElement.id, title: document.querySelector('#dem-title').value, detail: document.querySelector('#dem-detail').value }));
    out['focus-' + w] = { before: before.meters.map(m => m.now), mid: mid.meters.map(m => m.now), after: after.meters.map(m => m.now), ...f };
    await p.screenshot({ path: `/shots/d11-foco-demanda-${w}.png` });
    await p.close();
  }
  claudeSnap(42.5, 61); codexRollout(83, 96);
  console.log(JSON.stringify(out, null, 1));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
