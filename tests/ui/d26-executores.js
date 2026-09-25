// D26 (50366913d891) — tela Executores e bloco "Executores desta demanda" contra o SERVIDOR REAL do worktree
// (QA; roteiro original do Frontend, sem nenhuma rota simulada: o fetch só é ESPIONADO para conferir os corpos dos POST).
// Dados temporários (nunca a 7070 nem o log real) e `claude`/`codex` FALSOS no PATH do servidor, CODEX_HOME vazio
// (Codex "sem login"). Checklist e passo a passo: tests/ui/checklist-executores-d26.md. Duas fases:
//   PHASE=exec → tela Executores (salvar 409/ack, versão desatualizada, aplicar a todos, política, 1440/390, temas)
//   PHASE=dem  → bloco da demanda (Diferente, B8/B9, "usar o padrão nesta demanda", "Trocar só nesta demanda", sino)
//   docker run --rm --add-host=host.docker.internal:host-gateway -e NODE_PATH=/usr/src/app/node_modules \
//     -e PORT=<porta> -e PHASE=exec -v "$OUT:/out" -v "$PWD/tests/ui:/shots" zenika/alpine-chrome:with-puppeteer \
//     node /shots/d26-executores.js
// Saída: $OUT/d26-<fase>-result.json + capturas. Código ≠ 0 se alguma verificação falhar.
const puppeteer = require('puppeteer');
const net = require('net');
const fs = require('fs');
const PORT = Number(process.env.PORT || 17526), BASE = `http://127.0.0.1:${PORT}/`, OUT = process.env.OUT || '/out';
const PHASE = process.env.PHASE || 'exec', DEM = process.env.DEM || '50366913d891';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = { phase: PHASE, checks: [], errors: [] };
const C = (name, ok, info) => { out.checks.push({ name, ok: !!ok, info }); console.error(`${ok ? 'ok ' : 'FALHOU'} ${name}${info !== undefined ? ' ' + JSON.stringify(info).slice(0, 300) : ''}`); };
const relay = port => new Promise(res => net.createServer(c => { const u = net.connect(port, 'host.docker.internal'); c.pipe(u).pipe(c); u.on('error', () => c.destroy()); c.on('error', () => u.destroy()); }).listen(port, '127.0.0.1', res));
// espião (não simula nada): registra método/caminho/corpo dos POST e devolve a resposta REAL do servidor
const SPY = () => {
  window.__posts = [];
  const of = window.fetch.bind(window);
  window.fetch = async (u, opt = {}) => {
    const path = String(u).replace(/^https?:\/\/[^/]+/, ''), m = (opt.method || 'GET').toUpperCase();
    const r = await of(u, opt);
    if (m !== 'GET' && /\/api\/(executores|demand\/executores)/.test(path)) window.__posts.push({ path, body: opt.body ? JSON.parse(opt.body) : null, status: r.status });
    return r;
  };
};

(async () => {
  await relay(PORT);
  const b = await puppeteer.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'], executablePath: process.env.PUPPETEER_EXECUTABLE_PATH });
  const page = async (w, theme, hash) => {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: w > 500 ? 900 : 844, deviceScaleFactor: 1 });
    p.on('pageerror', e => out.errors.push(String(e).slice(0, 300)));
    p.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|EventSource|net::ERR/.test(m.text())) out.errors.push(m.text().slice(0, 300)); });
    await p.evaluateOnNewDocument(t => { try { localStorage.setItem('sc-theme', t); } catch (e) { } }, theme);
    await p.evaluateOnNewDocument(SPY);
    await p.goto(BASE + hash, { waitUntil: 'domcontentloaded' });
    await p.waitForFunction(() => typeof state !== 'undefined' && state, { timeout: 60000 }); await sleep(1500);
    return p;
  };
  const hscroll = p => p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  const txt = (p, sel) => p.$eval(sel, e => e.innerText).catch(() => '');
  const posts = p => p.evaluate(() => window.__posts || []);
  const api = (p, path, method = 'GET', body) => p.evaluate(async (path, method, body) => {
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, json: await r.json().catch(() => null) };
  }, path, method, body);
  try {
    if (PHASE === 'exec') {
      const p = await page(1440, 'light', '#/squad');
      const v0 = (await api(p, '/api/executores')).json.version;
      C('link na tela da squad', await p.$('a[href="#/squad/executores"]') !== null);
      await p.click('a[href="#/squad/executores"]'); await sleep(1500);
      C('menu Squad ativo', await p.$eval('#menu a[data-nav="squad"]', a => a.getAttribute('aria-current')) === 'page');
      C('foco no h1', await p.evaluate(() => document.activeElement?.tagName) === 'H1');
      const rows = await p.$$eval('.ex-tbl tbody tr:not(.ex-wrow)', t => t.length);
      C('9 linhas (padrão + 8)', rows === 9, rows);
      C('Orquestrador: Codex desabilitado (Q2)', await p.$eval('#ex-r-orquestrador option[value="codex"]', o => o.disabled).catch(() => false));
      C('motivo Q2 visível', /aguardando decisão do humano \(Q2\)/.test(await txt(p, '#ex-w-orquestrador')));
      C('variável ignorada (SQUAD_RUNNER no ambiente do servidor)', /SQUAD_RUNNER/.test(await txt(p, '#main')));
      C('estado real: codex sem login (CODEX_HOME vazio)', /sem login/.test(await txt(p, '#main')));
      C('efetivo recente com chip do run real', /gpt-5\.6-sol · OpenAI/.test(await txt(p, '.ex-tbl')), (await txt(p, '.ex-tbl')).slice(0, 400));
      C('histórico com antes → depois', /usar o padrão\s*→(\s*para)?\s*Claude Code · sonnet/.test(await txt(p, '.ex-hist')), (await txt(p, '.ex-hist')).slice(0, 300));
      C('Salvar desabilitado sem mudança', await p.$eval('#ex-save', b => b.disabled));
      await p.screenshot({ path: `${OUT}/d26-real-executores-1440-claro.png`, fullPage: true });
      await p.focus('#ex-r-qa'); await p.keyboard.press('ArrowDown'); await p.keyboard.press('ArrowDown'); await sleep(400);
      const v = await p.$eval('#ex-r-qa', s => s.value);
      C('teclado: select mudou e manteve o foco', v === 'codex' && await p.evaluate(() => document.activeElement?.id) === 'ex-r-qa', v);
      C('aviso Codex (leitura não isolada)', /sandbox read-only do Codex não restringe leitura/.test(await txt(p, '#main')));
      await p.type('#ex-m-qa', 'claude-opus-5-5'); await p.keyboard.press('Tab'); await sleep(300);
      C('modelo incompatível bloqueia', await p.$eval('#ex-save', b => b.disabled) && /Anthropic/.test(await txt(p, '#ex-w-qa')));
      await p.click('#ex-m-qa', { clickCount: 3 }); await p.keyboard.press('Backspace'); await p.type('#ex-m-qa', 'gpt-5.6-sol'); await p.keyboard.press('Tab'); await sleep(300);
      await p.click('#ex-save'); await sleep(1500);
      const p409 = (await posts(p)).filter(x => x.path === '/api/executores').pop();
      C('servidor real devolveu 409 (codex sem login)', p409?.status === 409, p409);
      C('409 → Salvar mesmo assim', await p.$('#ex-save-ack') !== null && await p.evaluate(() => document.activeElement?.id) === 'ex-save-ack');
      C('409 marca a linha do QA', /Codex sem login/.test(await txt(p, '#ex-w-qa')), await txt(p, '#ex-w-qa'));
      await p.screenshot({ path: `${OUT}/d26-real-executores-409-1440.png`, clip: { x: 0, y: 0, width: 1440, height: 900 } });
      await p.keyboard.press('Enter'); await sleep(1500);
      const last = (await posts(p)).filter(x => x.path === '/api/executores').pop();
      C('reenvio com acknowledge → 200', last?.status === 200 && last?.body?.acknowledge === true && last?.body?.agents?.qa?.runner === 'codex' && last.body.baseVersion === v0, last);
      C('mensagem salva (versão real)', new RegExp(`Configuração salva \\(versão ${v0 + 1}\\)`).test(await txt(p, '.ex-msg')), await txt(p, '.ex-msg'));
      C('histórico mostra "salvo mesmo assim"', /salvo mesmo assim/.test(await txt(p, '.ex-hist')));
      const cfg = (await api(p, '/api/executores')).json;
      C('servidor gravou QA = codex · gpt-5.6-sol', cfg.config.agents.qa?.runner === 'codex' && cfg.config.agents.qa?.model === 'gpt-5.6-sol' && cfg.version === v0 + 1, cfg.config.agents.qa);
      await p.select('#ex-r-orquestrador', ''); await sleep(300); await p.select('#ex-r-squad', 'codex'); await sleep(300);
      C('padrão Codex + Orquestrador herdando = bloqueado', await p.$eval('#ex-save', b => b.disabled) && /precisa ficar em Claude Code/.test(await txt(p, '#ex-w-orquestrador')));
      await p.click('[data-ex="discard"]'); await sleep(300);
      // versão desatualizada: outra "aba" (fetch direto ao servidor real) muda a configuração
      await p.select('#ex-r-devops', 'claude'); await sleep(200);
      const bump = await api(p, '/api/executores', 'POST', { baseVersion: v0 + 1, policy: { onUnavailable: 'parar' } });
      C('outra aba salvou (200)', bump.status === 200, bump);
      await p.click('#ex-save'); await sleep(1000);
      C('409 versão desatualizada + recarregar', /mudou em outro lugar/.test(await txt(p, '.ex-msg')) && await p.$('[data-ex="reload-discard"]') !== null, await txt(p, '.ex-msg'));
      await p.click('[data-ex="reload-discard"]'); await sleep(1200);
      const v2 = (await api(p, '/api/executores')).json.version;
      await p.select('#ex-all-r', 'codex'); await sleep(200); await p.click('#ex-all-open'); await sleep(300);
      const conf = await txt(p, '.ex-confirm');
      C('confirmação na tela (texto do contrato)', /O padrão da squad passa a ser Codex e os 8 agentes voltam a usar o padrão\. Demandas já iniciadas mantêm a configuração delas\./.test(conf));
      C('confirmação diz que o Orquestrador fica no Claude', /O Orquestrador fica em Claude Code/.test(conf));
      await p.screenshot({ path: `${OUT}/d26-real-aplicar-a-todos-1440.png` });
      await p.click('#ex-all-go'); await sleep(1200);
      C('aplicar: 409 real → Aplicar mesmo assim', /Aplicar mesmo assim/.test(await txt(p, '#ex-all-go')));
      await p.click('#ex-all-go'); await sleep(1500);
      const la = (await posts(p)).filter(x => x.path === '/api/executores/aplicar-a-todos').pop();
      C('aplicar: POST runner codex + ack → 200', la?.status === 200 && la?.body?.runner === 'codex' && la?.body?.acknowledge === true && la.body.baseVersion === v2, la);
      C('aplicar: mensagem Q2', /O Orquestrador ficou em Claude Code/.test(await txt(p, '.ex-msg')), await txt(p, '.ex-msg'));
      const cfg2 = (await api(p, '/api/executores')).json.config;
      C('servidor: squad codex, 7 null, Orquestrador claude', cfg2.squad.runner === 'codex' && cfg2.agents.orquestrador?.runner === 'claude' && Object.entries(cfg2.agents).filter(([k, x]) => k !== 'orquestrador' && x === null).length === 7, cfg2);
      await p.click('#ex-pol-parar'); await sleep(300);
      C('política parar explica', /O agente não inicia/.test(await txt(p, '.ex-pol')));
      C('sem rolagem horizontal 1440', !(await hscroll(p)));
      await p.close();
      for (const [w, th] of [[390, 'dark'], [1440, 'dark'], [390, 'light']]) {
        const q = await page(w, th, '#/squad/executores'); await sleep(800);
        C(`${w} ${th}: sem rolagem horizontal`, !(await hscroll(q)));
        C(`${w} ${th}: tema`, await q.evaluate(() => document.documentElement.dataset.theme) === th);
        await q.screenshot({ path: `${OUT}/d26-real-executores-${w}-${th === 'light' ? 'claro' : 'escuro'}.png`, fullPage: true });
        await q.close();
      }
    } else {
      const t = await page(1440, 'light', '#/painel'); const code = await t.evaluate(d => demandCode(d), DEM); await t.close();
      C('código da demanda', !!code, code);
      for (const [w, th] of [[1440, 'light'], [390, 'dark'], [1440, 'dark'], [390, 'light']]) {
        const d = await page(w, th, `#/demandas/${code}/executores`);
        await sleep(800);
        const sec = await txt(d, '#sec-executores');
        if (w === 1440 && th === 'light') {
          C('demanda: TOC tem Executores', await d.$(`nav.toc a[href="#/demandas/${code}/executores"]`) !== null);
          C('demanda: Diferente com motivo executor (Arquiteto)', /Diferente\s*executor diferente do configurado/.test(sec), sec.slice(0, 600));
          C('demanda: Diferente fallback (QA sem login)', /sem login: rodou no padrão/.test(sec));
          C('demanda: origem trocado nesta demanda', /trocado nesta demanda/.test(sec));
          C('demanda: 2 marcas Diferente', (await d.$$eval('.ex-diff', x => x.length)) === 2, await d.$$eval('.ex-diff', x => x.length));
          const al = await txt(d, '.dem-alerts');
          C('demanda: B8 real com ações', /Tentar de novo/.test(al) && /Usar o padrão nesta demanda/.test(al), al.slice(0, 300));
          C('demanda: B9 real (Arquiteto rodou em Codex)', /Arquiteto rodou em Codex/.test(al));
          await d.screenshot({ path: `${OUT}/d26-real-demanda-alertas-1440.png` });
          await d.click('#bell'); await sleep(500);
          C('sino: B8 bloqueio', /DevOps: Codex indisponível/.test(await txt(d, '#notif-panel')), (await txt(d, '#notif-panel')).slice(0, 300));
          await d.keyboard.press('Escape'); await sleep(200);
          await d.click('[data-ex="al-retry"]'); await sleep(1200);
          C('B8: tentar de novo → checar (real)', (await posts(d)).some(x => x.path === '/api/executores/checar' && x.status === 200));
          await d.click('[data-ex="al-default"]'); await sleep(1500);
          const pd = (await posts(d)).filter(x => x.path === '/api/demand/executores').pop();
          C('B8: usar o padrão nesta demanda → POST 200', pd?.status === 200 && pd?.body?.demand === DEM && pd.body.role === 'devops' && pd.body.runner === 'claude', pd);
          await sleep(3500);
          const live = (await api(d, '/api/live')).json;
          C('B8 fechado no servidor', !live.alerts.some(a => a.kind === 'executor-indisponivel' && a.demand === DEM));
          await d.click(`[data-ex="dem-open"]`); await sleep(400);
          C('trocar: foco no papel', await d.evaluate(() => document.activeElement?.id?.startsWith('exd-role-')));
          await d.select(`#exd-role-${DEM}`, 'orquestrador'); await sleep(200); await d.select(`#exd-runner-${DEM}`, 'codex'); await sleep(300);
          C('trocar: Orquestrador Codex recusado (Q2)', await d.$eval(`#exd-go-${DEM}`, b => b.disabled) && /Q2/.test(await txt(d, '#sec-executores')));
          await d.select(`#exd-role-${DEM}`, 'backend'); await sleep(300);
          await d.click(`#exd-go-${DEM}`); await sleep(1200);
          C('trocar: 409 real → Trocar mesmo assim', /Trocar mesmo assim/.test(await txt(d, `#exd-go-${DEM}`)));
          await d.click(`#exd-go-${DEM}`); await sleep(1500);
          const pt = (await posts(d)).filter(x => x.path === '/api/demand/executores').pop();
          C('trocar: POST backend codex ack → 200', pt?.status === 200 && pt?.body?.role === 'backend' && pt.body.runner === 'codex' && pt.body.acknowledge === true, pt);
          C('trocar: mensagem ok', /Backend: Codex nesta demanda/.test(await txt(d, '#sec-executores')));
          await d.screenshot({ path: `${OUT}/d26-real-demanda-trocar-1440.png` });
        }
        C(`demanda ${w} ${th}: sem rolagem horizontal`, !(await hscroll(d)));
        await d.evaluate(() => document.getElementById('sec-executores')?.scrollIntoView());
        await d.screenshot({ path: `${OUT}/d26-real-demanda-${w}-${th === 'light' ? 'claro' : 'escuro'}.png` });
        await d.close();
      }
    }
  } catch (e) { out.errors.push('EXC ' + String(e && e.stack || e).slice(0, 600)); }
  C('sem erros de página', out.errors.length === 0, out.errors);
  fs.writeFileSync(`${OUT}/d26-${PHASE}-result.json`, JSON.stringify(out, null, 2));
  await b.close();
  process.exit(out.checks.every(c => c.ok) ? 0 : 1);
})();
