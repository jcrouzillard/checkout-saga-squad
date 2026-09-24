// D14 (1e3d3c894630) — governança ao vivo do Squad Control: CA-U1..U3, modo sem F1, contraste (axe-core), tarefas T1–T6
// e capturas por tela para o checklist de heurísticas (tests/ui/checklist-governanca-d14.md).
// Executado em Docker (servidores do worktree no host):
//   docker run --rm --platform linux/amd64 --add-host=host.docker.internal:host-gateway -e NODE_PATH=/home/pptruser/node_modules \
//     -v "$PWD/tests/ui:/shots" -v "$W14/data:/work/data" -v "$W14/trans:/work/trans" -v "$W14/ctl:/work/ctl" -v "$AXE:/work/axe.min.js" \
//     -w /home/pptruser ghcr.io/puppeteer/puppeteer:latest node /shots/d14-governanca.js
// FIX = servidor com SQUAD_ROOT_DATA=$W14/data (CÓPIA temporária do log real) e SQUAD_TRANSCRIPTS=$W14/trans (sintético).
//   O script acrescenta fixtures nessa cópia (D15..D19) e transcrições sintéticas (Orquestrador, Backend parado, Frontend).
// CA-U3 exige um vigia no host que para/sobe o servidor FIX quando o script grava "stop"/"start" em /work/ctl/cmd
//   (ver checklist). Nunca aponte FIX para o log real.
const puppeteer = require('puppeteer');
const fs = require('fs');
const FIX = process.env.FIX || 'http://host.docker.internal:7128/';
const LOG = '/work/data/docs/squad/memory/decisions.jsonl';
const TR = '/work/trans';
const AXE = '/work/axe.min.js';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const iso = (ms = Date.now()) => new Date(ms).toISOString().replace(/\.\d+Z$/, '+00:00');
const readLog = () => fs.readFileSync(LOG, 'utf8').trim().split('\n').map(l => JSON.parse(l));
const append = evs => fs.appendFileSync(LOG, evs.map(e => JSON.stringify(e)).join('\n') + '\n');
const rid = p => `${p}${Math.random().toString(16).slice(2, 12)}`;
const out = { errors: [], results: {} };
const R = (k, v) => { out.results[k] = v; console.error(`[${k}] ${JSON.stringify(v).slice(0, 600)}`); };
// ids hexadecimais de 12 caracteres: o servidor só reconhece `--demand <id>` no prompt da transcrição nesse formato.
const D15 = 'fa15aaaaaaaa', D16 = 'fb16bbbbbbbb', D17 = 'fc17cccccccc', D18 = 'fd18dddddddd', D19 = 'fe19eeeeeeee';

// ---------------- fixtures (só na cópia temporária)
function jl(path, rows, ageS) {
  fs.mkdirSync(require('path').dirname(path), { recursive: true });
  fs.writeFileSync(path, rows.map(r => JSON.stringify(r)).join('\n') + '\n');
  const t = (Date.now() - ageS * 1000) / 1000; fs.utimesSync(path, t, t);
}
const asst = (content, sAgo) => ({ type: 'assistant', timestamp: new Date(Date.now() - sAgo * 1000).toISOString(), message: { model: 'claude-opus-5-5', content } });
const user = (content, sAgo) => ({ type: 'user', timestamp: new Date(Date.now() - sAgo * 1000).toISOString(), message: { content } });
const FRONT = `${TR}/sess-qa/subagents/agent-fe01.jsonl`;
function seed() {
  if (!readLog().some(e => e.id === D15)) {
    const ago = m => iso(Date.now() - m * 60000), ev = [];
    const dem = (id, title, m, extra = []) => { ev.push({ id, ts: ago(m), agent: 'humano', type: 'task', to: 'orquestrador', title: `Demanda: ${title}`, detail: 'Fixture do QA (D14).', priority: 'normal', kind: 'operacao' }, ...extra); };
    const start = (d, m) => ({ id: d + '-s', ts: ago(m), agent: 'humano', type: 'start', to: 'orquestrador', demand: d, title: 'Iniciar', priority: 'normal', route: 'padrao', target: 'auto' });
    const g = (d, gate, reco, conf, m, to = 'orquestrador') => ({ id: rid('qg'), ts: ago(m), agent: 'auditor', type: 'gate', gate, demand: d, recommendation: reco, confidence: conf, risk: 'moderado', to, title: `${gate}: ${reco}`, detail: 'Parecer de fixture do QA' });
    dem(D15, 'QA fixture — gate devolvido com 62%', 40, [start(D15, 39), { id: D15 + '-h', ts: ago(35), agent: 'frontend', type: 'handoff', to: 'auditor', demand: D15, title: 'Implementação pronta' }, g(D15, 'G2', 'RETURN', 0.62, 30, 'frontend')]);
    dem(D16, 'QA fixture — triagem com perguntas', 25, [{ id: D16 + '-v', ts: ago(20), agent: 'arquiteto', type: 'validation', demand: D16, status: 'perguntas', title: 'Triagem: 2 perguntas', questions: [{ id: 'q1', text: 'Qual o escopo?' }, { id: 'q2', text: 'Qual o prazo?' }] }]);
    dem(D17, 'QA fixture — confiança 69,5%', 15, [start(D17, 14), g(D17, 'G2', 'APPROVE', 0.695, 10, 'qa')]);
    dem(D18, 'QA fixture — risco aceito', 12, [start(D18, 11), g(D18, 'G1', 'APPROVE', 0.64, 9), { id: rid('qh'), ts: ago(8), agent: 'humano', type: 'human', demand: D18, gate: 'G1', recommendation: 'APPROVE', title: 'Humano: APPROVE' }]);
    dem(D19, 'QA fixture — medição CA-U2', 6, [start(D19, 5)]);
    append(ev);
  }
  // Orquestrador (sessão principal) com Agent pendente para o Backend; Backend parado há 11 min; Frontend trabalhando na D15.
  jl(`${TR}/sess-qa.jsonl`, [user('plantão D14 QA', 900),
    asst([{ type: 'tool_use', id: 'tu-be01', name: 'Agent', input: { description: 'Backend · D15: correção', prompt: '...' } }], 800),
    user([{ type: 'tool_result', tool_use_id: 'tu-be01', content: [{ type: 'text', text: 'Async agent launched successfully.\nagentId: be01 (internal)' }] }], 799),
    asst([{ type: 'tool_use', id: 'tu-fe01', name: 'Agent', input: { description: 'Frontend · D15: correção', prompt: '...' } }], 700),
    user([{ type: 'tool_result', tool_use_id: 'tu-fe01', content: [{ type: 'text', text: 'Async agent launched successfully.\nagentId: fe01 (internal)' }] }], 699)], 5);
  const sub = `${TR}/sess-qa/subagents`;
  jl(`${sub}/agent-be01.jsonl`, [user(`Backend: D15 --demand ${D15}`, 800),
    asst([{ type: 'tool_use', id: 'b1', name: 'Bash', input: { command: 'docker compose up --build order-service', description: 'subir o order-service' } }], 660)], 660);
  fs.writeFileSync(`${sub}/agent-be01.meta.json`, JSON.stringify({ description: 'Backend: D15 correção', toolUseId: 'tu-be01' }));
  jl(FRONT, [user(`Frontend: D15 --demand ${D15}`, 700),
    asst([{ type: 'tool_use', id: 'f0', name: 'Read', input: { file_path: 'squad-control/index.html' } }], 30),
    user([{ type: 'tool_result', tool_use_id: 'f0', content: 'ok' }], 29)], 2);
  fs.writeFileSync(`${sub}/agent-fe01.meta.json`, JSON.stringify({ description: 'Frontend: D15 correção', toolUseId: 'tu-fe01' }));
}
const touchFront = rows => { fs.appendFileSync(FRONT, rows.map(r => JSON.stringify(r)).join('\n') + '\n'); };

// ---------------- páginas
let browser;
async function newPage(w, opts = {}) {
  const ctx = await (browser.createBrowserContext ? browser.createBrowserContext() : browser.createIncognitoBrowserContext());
  const p = await ctx.newPage(); p._ctx = ctx; p._reqs = []; p._clicks = [];
  await p.setViewport({ width: w, height: w <= 400 ? 844 : 900 });
  if (opts.theme) await p.evaluateOnNewDocument(t => { try { localStorage.setItem('sc-theme', t); } catch (e) {} }, opts.theme);
  if (opts.scheme) await p.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: opts.scheme }]);
  await p.setRequestInterception(true);
  p.on('request', r => {
    const u = r.url();
    if (u.startsWith(FIX)) p._reqs.push({ t: Date.now(), u: u.replace(FIX, '/').replace(/\?.*$/, ''), m: r.method() });
    if (opts.noLive && u.includes('/api/live')) return r.respond({ status: 404, contentType: 'text/plain', body: 'not found' });
    if (r.method() === 'POST' && opts.readOnly) return r.abort();
    r.continue();
  });
  p.on('console', m => { if (m.type() === 'error' && !/favicon|localhost:(3000|16686|8090|8081)|ERR_CONNECTION|Failed to load resource/.test(m.text() + (m.location()?.url || ''))) out.errors.push(`${w}px console: ${m.text()}`); });
  p.on('pageerror', e => out.errors.push(`${w}px pageerror: ${e.message}`));
  return p;
}
const go = async (p, hash) => { if (!p.url().startsWith(FIX)) { await p.goto(FIX + hash, { waitUntil: 'networkidle2' }); await sleep(1500); } else { await p.evaluate(h => { location.hash = h; }, hash); await sleep(900); } };
async function clk(p, sel, text, label) {
  for (let i = 0; i < 4; i++) {
    try {
      const h = await p.evaluateHandle((sel, text) => { const re = text ? new RegExp(text) : null; return [...document.querySelectorAll(sel)].find(e => (!re || re.test(e.textContent)) && e.getClientRects().length) || null; }, sel, text || '');
      const el = h.asElement(); if (!el) throw new Error(`não encontrado: ${sel} ${text || ''}`);
      await el.evaluate(e => e.scrollIntoView({ block: 'center' })); await el.click(); p._clicks.push(label || sel); await sleep(700); return;
    } catch (e) { if (i === 3 || !/detached|not clickable|not an Element/.test(String(e))) throw e; await sleep(300); }
  }
}
const visible = (p, sel) => p.evaluate(sel => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return { top: Math.round(r.top), bottom: Math.round(r.bottom), inView: r.top >= 0 && r.bottom <= innerHeight && r.height > 0, text: e.innerText.replace(/\s+/g, ' ').trim().slice(0, 200) }; }, sel);
async function scenario(name, fn) {
  if (process.env.ONLY && !new RegExp(process.env.ONLY).test(name)) return;
  const t0 = Date.now();
  try { await fn(); } catch (e) { R(name, { error: String(e && e.stack || e).slice(0, 700) }); }
  console.error(`-- ${name} ${Math.round((Date.now() - t0) / 1000)} s`);
}
const ctl = async cmd => { try { fs.unlinkSync('/work/ctl/ack'); } catch (e) {} fs.writeFileSync('/work/ctl/cmd', cmd); for (let i = 0; i < 100; i++) { if (fs.existsSync('/work/ctl/ack')) return true; await sleep(100); } return false; };

const ROUTES = ['#/painel', '#/demandas', '#/demandas/D15', '#/squad', '#/auditoria/alertas', '#/demandas/nova', '#/auditoria/politicas'];

(async () => {
  browser = await puppeteer.launch({ args: ['--no-sandbox'] });
  seed(); await sleep(2500);

  // ===== CA-U1: primeira tela sem rolar/clicar (1440x900 e 390x844), a partir de qualquer rota =====
  for (const w of [1440, 390]) await scenario(`CA-U1-${w}`, async () => {
    const p = await newPage(w, { readOnly: true });
    const res = {};
    for (const h of [...ROUTES, '#/auditoria/eventos', '#/produto/grafana']) {
      await go(p, h); await p.evaluate(() => window.scrollTo(0, 0)); await sleep(200);
      res[h] = await p.evaluate(() => {
        const ctrs = [...document.querySelectorAll('#ctrs a')].map(a => { const r = a.getBoundingClientRect(); return { t: a.getAttribute('aria-label'), inView: r.top >= 0 && r.bottom <= innerHeight && r.width > 0 }; });
        const live = document.querySelector('#live-ind'); const lr = live.getBoundingClientRect();
        return { ctrs, live: live.innerText.trim(), liveInView: lr.bottom <= innerHeight && lr.width > 0, sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
      });
    }
    await go(p, '#/painel'); await p.evaluate(() => window.scrollTo(0, 0)); await sleep(300);
    const painel = await p.evaluate(() => {
      const box = e => { if (!e) return null; const r = e.getBoundingClientRect(); return { top: Math.round(r.top), bottom: Math.round(r.bottom), inView: r.top >= 0 && r.bottom <= innerHeight, text: e.innerText.replace(/\s+/g, ' ').slice(0, 140) }; };
      return { mynext: box(document.querySelector('.mynext')), bloq: [...document.querySelectorAll('#alertas ul[aria-labelledby="h-bloqueio"] > li')].slice(0, 2).map(box),
        aviso: [...document.querySelectorAll('#alertas ul[aria-labelledby="h-aviso"] > li')].slice(0, 2).map(box), vh: innerHeight };
    });
    await p.screenshot({ path: `/shots/d14-primeira-tela-${w}.png` });
    const allCtrs = Object.values(res).every(r => r.ctrs.length === 3 && r.ctrs.every(c => c.inView) && r.liveInView);
    const ok = allCtrs && painel.mynext?.inView && (w === 1440 ? painel.bloq.length >= 2 && painel.bloq.every(b => b.inView) && painel.aviso.length >= 2 && painel.aviso.every(b => b.inView) : painel.bloq[0]?.inView);
    R(`CA-U1-${w}`, { ok, allCtrs, painel, routes: res });
    await p._ctx.close();
  });

  // ===== CA-U2: do fato à tela <= 3 s (10 repetições x 3 fatos: gate RETURN, ferramenta na transcrição, progress com passo) =====
  await scenario('CA-U2', async () => {
    const p = await newPage(1440);
    await go(p, '#/painel'); await sleep(2000);
    const reps = [];
    for (let i = 1; i <= 10; i++) {
      const r = { i };
      // (a) gate RETURN => bloqueio B1 na central
      const gid = rid('u2g');
      let t0 = Date.now();
      append([{ id: gid, ts: iso(), agent: 'auditor', type: 'gate', gate: 'G2', demand: D19, recommendation: 'RETURN', confidence: 0.8, risk: 'baixo', to: 'backend', title: `G2: RETURN (U2 ${i})` }]);
      r.gate = await p.waitForFunction(id => !!document.querySelector(`[data-alert$=":${id}"]`), { timeout: 8000, polling: 50 }, gid).then(() => Date.now() - t0).catch(() => null);
      append([{ id: rid('u2h'), ts: iso(), agent: 'humano', type: 'human', demand: D19, gate: 'G2', recommendation: 'OVERRIDE', title: 'Humano: OVERRIDE (reinicia o ciclo)', note: 'QA U2' }]);
      await sleep(400);
      // (b) ferramenta começa na transcrição do Frontend => cartão mostra "Executando: U2 passo i"
      t0 = Date.now();
      touchFront([asst([{ type: 'tool_use', id: `u2t${i}`, name: 'Bash', input: { command: `echo ${i}`, description: `U2 passo ${i}` } }], 0)]);
      r.tool = await p.waitForFunction(i => (document.querySelector('#main [data-agent="frontend"]')?.innerText || '').includes(`▶ Executando: U2 passo ${i}`), { timeout: 8000, polling: 50 }, i).then(() => Date.now() - t0).catch(() => null);
      t0 = Date.now();
      touchFront([user([{ type: 'tool_result', tool_use_id: `u2t${i}`, content: 'ok' }], 0)]);
      r.toolEnd = await p.waitForFunction(i => !(document.querySelector('#main [data-agent="frontend"]')?.innerText || '').includes(`▶ Executando: U2 passo ${i}`), { timeout: 8000, polling: 50 }, i).then(() => Date.now() - t0).catch(() => null);
      // (c) progress com --step => passo do cartão do Frontend
      t0 = Date.now();
      append([{ id: rid('u2p'), ts: iso(), agent: 'frontend', type: 'progress', demand: D15, title: `Marco U2 ${i}`, step: `U2 etapa ${i}` }]);
      r.step = await p.waitForFunction(i => (document.querySelector('#main [data-agent="frontend"]')?.innerText || '').includes(`U2 etapa ${i}`), { timeout: 8000, polling: 50 }, i).then(() => Date.now() - t0).catch(() => null);
      reps.push(r); console.error(`U2 ${JSON.stringify(r)}`);
      await sleep(300 + Math.random() * 1200);   // desalinha em relação ao ciclo de 1,5 s
    }
    const all = reps.flatMap(r => [r.gate, r.tool, r.toolEnd, r.step]);
    const max = Math.max(...all.map(x => x ?? 99999));
    const reqs = p._reqs.filter(x => x.u.startsWith('/api/'));
    const byU = reqs.reduce((a, x) => (a[x.u] = (a[x.u] || 0) + 1, a), {});
    R('CA-U2', { ok: all.every(x => x != null && x <= 3000), max, reps, requests: byU });
    await p.screenshot({ path: '/shots/d14-ca-u2-1440.png' });
    await p._ctx.close();
  });

  // ===== CA-U3: indicador e decisões com dado defasado (para e sobe o servidor FIX) =====
  await scenario('CA-U3', async () => {
    const p = await newPage(1440, { readOnly: true });
    await go(p, '#/demandas/D15/gates'); await sleep(2000);
    const st = () => p.evaluate(() => ({ live: document.querySelector('#live-ind').innerText.replace(/\s+/g, ' ').trim(), sr: document.querySelector('#live-sr').textContent,
      srvDown: !document.querySelector('#srv-down').hidden ? document.querySelector('#srv-down').innerText.trim() : null,
      btns: [...document.querySelectorAll('[data-human]')].map(b => ({ t: b.textContent.trim(), dis: b.disabled, title: b.title })),
      lastOkAt, now: Date.now() }));
    const before = await st();
    const stopped = await ctl('stop');
    const tStop = Date.now(); const lastOk0 = (await st()).lastOkAt;
    let tLate = null, tOff = null, atOff = null, samples = [];
    while (Date.now() - tStop < 19000) {
      const s = await st(); samples.push([s.now - s.lastOkAt, s.live.slice(0, 30)]);
      if (tLate == null && /Atrasado/.test(s.live)) tLate = (s.now - s.lastOkAt) / 1000;
      if (tOff == null && /Sem conexão/.test(s.live)) { tOff = (s.now - s.lastOkAt) / 1000; atOff = s; }
      if (tOff != null && Date.now() - tStop > 17500) break;
      await sleep(100);
    }
    await p.screenshot({ path: '/shots/d14-sem-conexao-1440.png' });
    const started = await ctl('start');
    const tStart = Date.now();
    const back = await p.waitForFunction(() => /Ao vivo/.test(document.querySelector('#live-ind').innerText), { timeout: 10000, polling: 50 }).then(() => (Date.now() - tStart) / 1000).catch(() => null);
    await sleep(500);
    const after = await st();
    const disOk = atOff && atOff.btns.length > 0 && atOff.btns.every(b => b.dis && /Sem dados atuais/.test(b.title));
    R('CA-U3', { ok: stopped && started && tLate >= 5 && tLate <= 6.5 && tOff > 15 && tOff <= 16.5 && disOk && back != null && back <= 3 && after.btns.every(b => !b.dis),
      before: { live: before.live, btns: before.btns }, tLateS: tLate, tOffS: tOff, atOff: atOff && { live: atOff.live, sr: atOff.sr, srvDown: atOff.srvDown, btns: atOff.btns }, reconnectS: back, after: { live: after.live, btns: after.btns }, reload: false });
    await p._ctx.close();
  });

  // ===== Modo sem F1 (/api/live -> 404): mesmas contagens, sem undefined/NaN; texto da regra de 69,5% =====
  await scenario('sem-F1', async () => {
    const snap = async p => p.evaluate(() => ({ ctrs: [...document.querySelectorAll('#ctrs a')].map(a => a.getAttribute('aria-label')), cpainel: document.querySelector('#c-painel').textContent,
      bloq: [...document.querySelectorAll('#alertas ul[aria-labelledby="h-bloqueio"] > li')].map(l => l.querySelector('b')?.textContent),
      aviso: [...document.querySelectorAll('#alertas ul[aria-labelledby="h-aviso"] > li')].map(l => l.querySelector('b')?.textContent),
      states: [...document.querySelectorAll('#main [data-agent]')].map(a => a.dataset.agent + ':' + (a.querySelector('.state')?.textContent || '')),
      rule0695: [...document.querySelectorAll('[data-alert]')].filter(l => /D17/.test(l.innerText)).map(l => l.querySelector('details p')?.textContent)[0] || null,
      live: document.querySelector('#live-ind').innerText.replace(/\s+/g, ' ').trim(), liveTitle: document.querySelector('#live-ind').title }));
    const res = {};
    for (const mode of ['live', 'noLive']) {
      const p = await newPage(1440, { readOnly: true, noLive: mode === 'noLive' });
      await go(p, '#/painel'); await sleep(4000);
      res[mode] = await snap(p);
      const bad = [];
      for (const h of ROUTES.concat(['#/squad?agente=orquestrador', '#/squad?agente=backend', '#/auditoria/eventos'])) {
        await go(p, h); await sleep(400);
        const t = await p.evaluate(() => document.body.innerText);
        // "sem undefined" aparece em textos reais do log (handoffs antigos do QA): não é defeito de renderização.
        if (/(?<!sem |0 )\bundefined\b|\bNaN\b|\[object Object\]/.test(t)) bad.push(h);
      }
      res[mode].undefinedIn = bad;
      await go(p, '#/demandas/D17/gates'); await sleep(500);
      res[mode].gateText0695 = await p.evaluate(() => (document.querySelector('#main')?.innerText.match(/[^\n]*(69|70)[,.]?\d*%[^\n]*/g) || []).slice(0, 4));
      await p.evaluate(() => { location.hash = '#/painel'; }); await sleep(800);
      if (mode === 'noLive') await p.screenshot({ path: '/shots/d14-sem-f1-1440.png' });
      res[mode].reqs = p._reqs.filter(x => x.u.startsWith('/api/')).reduce((a, x) => (a[x.u] = (a[x.u] || 0) + 1, a), {});
      await p._ctx.close();
    }
    const same = JSON.stringify([res.live.ctrs, res.live.bloq.length, res.live.aviso.length]) === JSON.stringify([res.noLive.ctrs, res.noLive.bloq.length, res.noLive.aviso.length]);
    R('sem-F1', { ok: same && !res.live.undefinedIn.length && !res.noLive.undefinedIn.length, same, ...res });
  });

  // ===== Revalidação D14-QA-1: percentual com casa decimal só perto do limite e barra da recomendação proporcional =====
  await scenario('pct-reco', async () => {
    const p = await newPage(1440, { readOnly: true });
    const res = {};
    for (const [code, expect] of [['D15', 62], ['D17', 69.5]]) {
      await go(p, `#/demandas/${code}`); await sleep(1500);
      res[code] = await p.evaluate(() => { const r = document.querySelector('.reco'); const bar = r?.querySelector('.bar > div');
        return r && { conf: r.querySelector('.conf')?.textContent, style: bar.getAttribute('style'), ratio: bar.getBoundingClientRect().width / bar.parentElement.getBoundingClientRect().width }; });
      res[code].barOk = !!res[code] && Math.abs(res[code].ratio * 100 - expect) <= 1;
      if (code === 'D15') { const el = await p.$('.reco'); if (el) await el.screenshot({ path: '/shots/d14-reco-barra-1440.png' }); }
    }
    R('pct-reco', { ok: res.D15.barOk && res.D17.barOk && /^69,5%/.test(res.D17.conf) && /^62%/.test(res.D15.conf), ...res });
    await p._ctx.close();
  });

  // ===== Contraste com axe-core (claro/escuro x 1440/390 x 7 telas) + CA-T2 persistência do tema =====
  await scenario('axe', async () => {
    const res = {};
    for (const theme of ['light', 'dark']) for (const w of [1440, 390]) {
      const p = await newPage(w, { readOnly: true, theme });
      for (const h of [...ROUTES, '#/squad?agente=orquestrador']) {
        await go(p, h); await sleep(500);
        if (!(await p.evaluate(() => !!window.axe))) await p.addScriptTag({ path: AXE });
        const r = await p.evaluate(async () => {
          const x = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] }, resultTypes: ['violations'] });
          return { theme: document.documentElement.dataset.theme, v: x.violations.map(v => ({ id: v.id, impact: v.impact, n: v.nodes.length, ex: v.nodes.slice(0, 3).map(n => `${n.target.join(' ')} :: ${(n.any[0]?.message || n.failureSummary || '').slice(0, 160)}`) })) };
        });
        res[`${theme}-${w}-${h}`] = r;
      }
      await go(p, '#/painel'); await sleep(300);
      await p.screenshot({ path: `/shots/d14-painel-${theme === 'light' ? 'claro' : 'escuro'}-${w}.png` });
      await p._ctx.close();
    }
    const contrast = Object.entries(res).filter(([, r]) => r.v.some(v => v.id === 'color-contrast')).map(([k, r]) => ({ k, ...r.v.find(v => v.id === 'color-contrast') }));
    const others = {}; for (const r of Object.values(res)) for (const v of r.v) if (v.id !== 'color-contrast') others[v.id] = (others[v.id] || { impact: v.impact, n: 0, ex: v.ex }), others[v.id].n += v.n;
    const themeWrong = Object.entries(res).filter(([k, r]) => !k.startsWith(r.theme)).map(([k]) => k);
    // CA-T2: tema persiste após F5 (escolha pelo botão) e "Sistema" segue prefers-color-scheme
    const p = await newPage(1440, { readOnly: true, scheme: 'dark' });
    await go(p, '#/painel');
    const sys = await p.evaluate(() => [document.documentElement.dataset.theme, document.querySelector('#theme-lbl').textContent]);
    await clk(p, '#theme-btn', null, 'tema'); const t1 = await p.evaluate(() => [document.documentElement.dataset.theme, document.querySelector('#theme-lbl').textContent]);
    await p.reload({ waitUntil: 'domcontentloaded' });
    const early = await p.evaluate(() => document.documentElement.dataset.theme);
    await sleep(1200); const t2 = await p.evaluate(() => [document.documentElement.dataset.theme, document.querySelector('#theme-lbl').textContent, localStorage.getItem('sc-theme')]);
    await p._ctx.close();
    R('axe', { ok: !contrast.length, contrast, others, themeWrong, pages: Object.keys(res).length, temaT2: { sistemaComEscuro: sys, aposClique: t1, noDomContentLoaded: early, aposF5: t2 } });
  });

  // ===== Tarefas T1–T6 (1440 e 390) + capturas por tela para as heurísticas =====
  for (const w of [1440, 390]) await scenario(`tarefas-${w}`, async () => {
    const T = {};
    let p = await newPage(w, { readOnly: true });
    // T1: há algo bloqueado? quem precisa agir? (0 cliques)
    let t0 = Date.now(); await p.goto(FIX + '#/painel', { waitUntil: 'domcontentloaded' });
    await p.waitForFunction(() => document.querySelectorAll('#ctrs a').length === 3 && !!document.querySelector('.mynext'), { timeout: 8000, polling: 50 });
    T.T1 = { ms: Date.now() - t0, clicks: 0, ...(await p.evaluate(() => ({ ctrs: [...document.querySelectorAll('#ctrs a')].map(a => a.getAttribute('aria-label')), next: document.querySelector('.mynext').innerText.replace(/\s+/g, ' ').slice(0, 160),
      quem: [...document.querySelectorAll('#alertas ul[aria-labelledby="h-bloqueio"] > li .who')].slice(0, 3).map(x => x.innerText.replace(/\s+/g, ' ')) }))) };
    await sleep(800);
    await p.screenshot({ path: `/shots/d14-painel-${w}.png` });
    await p.screenshot({ path: `/shots/d14-barra-global-${w}.png`, clip: await p.evaluate(() => { const r = document.querySelector('#hdr').getBoundingClientRect(); return { x: 0, y: 0, width: innerWidth, height: Math.ceil(r.bottom) + 2 }; }) });
    // T2: o que o Backend está fazendo agora e desde quando? (<= 1 clique)
    p._clicks = []; await clk(p, '#main [data-agent="backend"]', null, 'cartão Backend');
    T.T2 = { clicks: p._clicks.length, drawer: await p.evaluate(() => { const d = document.querySelector('#drawer'); return { open: !d.hidden, secs: [...d.querySelectorAll('h3,h4')].map(h => h.textContent.trim()).slice(0, 9), agora: d.innerText.replace(/\s+/g, ' ').slice(0, 400) }; }) };
    await p.screenshot({ path: `/shots/d14-gaveta-backend-${w}.png` });
    // T5: qual agente está sem progresso e o que verificar (<= 1 clique): central -> "Ver integrante"
    await go(p, '#/painel'); p._clicks = [];
    const t5 = await p.evaluate(() => [...document.querySelectorAll('[data-alert^="agent-stalled"]')].map(l => l.innerText.replace(/\s+/g, ' ').slice(0, 200)));
    await clk(p, '[data-alert^="agent-stalled"] .act a', 'Ver integrante', 'Ver integrante');
    T.T5 = { clicks: p._clicks.length, item: t5, drawer: await p.evaluate(() => { const d = document.querySelector('#drawer'); return { open: !d.hidden, txt: d.innerText.replace(/\s+/g, ' ').slice(0, 300), hash: location.hash }; }) };
    // T3: o Orquestrador está esperando alguém? (cartão no Painel: 0 cliques; gaveta: 1)
    await go(p, '#/painel'); p._clicks = [];
    const card = await p.evaluate(() => document.querySelector('#main [data-agent="orquestrador"]')?.innerText.replace(/\s+/g, ' '));
    await clk(p, '#main [data-agent="orquestrador"]', null, 'cartão Orquestrador');
    T.T3 = { clicks: p._clicks.length, card, espera: await p.evaluate(() => document.querySelector('#drawer')?.innerText.match(/Espera de ação[\s\S]{0,300}/)?.[0].replace(/\s+/g, ' ')) };
    await p.screenshot({ path: `/shots/d14-gaveta-orquestrador-${w}.png` });
    await go(p, '#/squad'); await sleep(400); await p.screenshot({ path: `/shots/d14-squad-${w}.png`, fullPage: w === 1440 });
    // T4: decidir o gate pendente a partir de outra tela (Auditoria): contador "Você"/bloqueios -> Decidir -> botão
    await go(p, '#/auditoria/eventos'); p._clicks = [];
    await clk(p, '#ctrs a.ctr.bloq', null, 'contador bloqueios');
    await clk(p, '#alertas [data-alert*="qg"] .act a, #alertas .act a', 'Decidir G2', 'Decidir G2');
    const t4 = await p.evaluate(() => ({ hash: location.hash, btns: [...document.querySelectorAll('[data-human]')].filter(b => b.getClientRects().length && !b.disabled).map(b => b.textContent.trim()) }));
    T.T4 = { clicksAteBotaoDeDecisao: p._clicks.length, clicksComDecisao: p._clicks.length + 1, ...t4 };
    await p.screenshot({ path: `/shots/d14-demanda-${w}.png`, fullPage: w === 1440 });
    // T6: quem fechou o bloqueio de G2 (D6 real: gate-return) e quando? Auditoria -> Alertas -> filtro Demanda
    await go(p, '#/painel'); p._clicks = [];
    await clk(p, '#menu a[data-nav="auditoria"]', null, 'menu Auditoria');
    await clk(p, '#main a', '^Alertas$', 'aba Alertas');
    await p.select('#f-ademanda', 'D6'); p._clicks.push('filtro Demanda = D6'); await sleep(900);
    T.T6 = { clicks: p._clicks.length, hash: await p.evaluate(() => location.hash), rows: await p.evaluate(() => [...document.querySelectorAll('#main table tbody tr')].map(tr => tr.innerText.replace(/\s+/g, ' ').slice(0, 220)).filter(t => /G2/.test(t)).slice(0, 3)) };
    await p.screenshot({ path: `/shots/d14-auditoria-alertas-${w}.png`, fullPage: w === 1440 });
    await go(p, '#/demandas'); await p.screenshot({ path: `/shots/d14-demandas-${w}.png`, fullPage: w === 1440 });
    await go(p, '#/demandas/nova'); await p.screenshot({ path: `/shots/d14-nova-demanda-${w}.png` });
    await go(p, '#/auditoria/politicas'); await sleep(800);
    await p.evaluate(() => document.querySelector('#legenda')?.scrollIntoView()); await sleep(300);
    await p.screenshot({ path: `/shots/d14-politicas-legenda-${w}.png` });
    // Sondas para heurísticas (H1–H10) por tela
    const probe = async h => { await go(p, h); await sleep(500); return p.evaluate(() => ({ sev: document.querySelectorAll('#main .sev').length, state: document.querySelectorAll('#main .state').length, porque: document.querySelectorAll('#main details summary').length,
      visto: document.querySelectorAll('#main [data-seen]').length, crumbs: document.querySelectorAll('#main nav.crumbs li').length, h1: document.querySelector('#main h1')?.textContent.trim(), filtros: document.querySelectorAll('#main [data-filter]').length,
      legendaLink: !!document.querySelector('#main a[href*="politicas"]'), sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, overflowX: document.documentElement.scrollWidth > document.documentElement.clientWidth })); };
    T.probes = {}; for (const h of ['#/painel', '#/demandas/D15', '#/squad', '#/demandas', '#/auditoria/alertas', '#/demandas/nova']) T.probes[h] = await probe(h);
    // CA-T3: escala de cinza — severidades/estados carregam ícone + palavra
    T.T3cor = await p.evaluate(() => ({ sevSemTexto: [...document.querySelectorAll('.sev')].filter(s => !s.textContent.trim() || !s.querySelector('svg')).length, stateSemIcone: [...document.querySelectorAll('.state')].filter(s => !s.querySelector('.ic') || !s.textContent.replace(/[●○▲■◷✓]/g, '').trim()).length }));
    R(`tarefas-${w}`, T);
    await p._ctx.close();
  });

  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
