// D16 (841f9a27e64a) — demandas de bug: fluxo da UI ponta a ponta (QA). Checklist: tests/ui/checklist-bugs-d16.md.
// Revalidação (após e565020/6ec999a): QA-D16-5 (aviso da máscara, "Mostrando 200 de N linhas", arquivo inteiro mascarado)
// e QA-D16-6 (409 com o verbo certo) viram condição de `ok`; `exigeLeitura` só registra a recomendação ao Frontend.
// Servidor do WORKTREE com dados TEMPORÁRIOS (nunca o :7070 nem o log real), Jaeger/Grafana/Prometheus SIMULADOS e
// `docker compose logs` SIMULADO (tests/ui/d16_simulados.py, tests/ui/d16-docker-simulado):
//   S=<scratch>; mkdir -p $S/data/docs/squad/memory $S/main $S/trans; cp docs/squad/memory/decisions.jsonl $S/data/docs/squad/memory/
//   printf 'GRAFANA_PORT=3001\n' > $S/main/.env; python3 tests/ui/d16_simulados.py files $S/files
//   python3 tests/ui/d16_simulados.py prod 17991 &
//   SQUAD_ROOT_DATA=$S/data SQUAD_LOG=$S/data/docs/squad/memory/decisions.jsonl SQUAD_TRANSCRIPTS=$S/trans SQUAD_MAIN_ROOT=$S/main \
//     SQUAD_TESTENV_SPAWN=0 SQUAD_TESTENV_PROBE=0 SQUAD_REPO_VISIBILITY=PUBLIC SQUAD_PROD_JAEGER=http://127.0.0.1:17991 \
//     SQUAD_PROD_GRAFANA=http://127.0.0.1:17991 SQUAD_PROD_PROMETHEUS=http://127.0.0.1:17991 SQUAD_DOCKER=$PWD/tests/ui/d16-docker-simulado \
//     SQUAD_GH=/usr/bin/false SQUAD_GIT=/usr/bin/false GRAFANA_PORT=3001 python3 tools/squad/server.py --port 7161 &
//   docker run --rm --add-host=host.docker.internal:host-gateway -e NODE_PATH=/home/pptruser/node_modules \
//     -v "$PWD/tests/ui:/shots" -v "$S/files:/work/files:ro" -v "$S/data:/work/data:ro" \
//     -w /home/pptruser ghcr.io/puppeteer/puppeteer:latest node /shots/d16-bugs.js
// As rotas /api/bug/* exigem Host 127.0.0.1/localhost (anti-DNS-rebinding): o script abre um repasse TCP DENTRO do
// container (127.0.0.1:7161 → host.docker.internal:7161) e navega por http://127.0.0.1:7161, com o Host original.
const puppeteer = require('puppeteer');
const net = require('net');
const fs = require('fs');
const PORT = Number(process.env.PORT || 7161);
const BASE = `http://127.0.0.1:${PORT}/`;
const FILES = '/work/files', DATA = '/work/data';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = { results: {}, errors: [] };
const R = (k, v) => { out.results[k] = v; console.error(`[${k}] ${JSON.stringify(v).slice(0, 700)}`); };
const SENSITIVE = ['c-9f31a7', 'Rua das Acacias Ficticias', '04567-321', 'ana.ficticia@exemplo.com.br', 'kafka-s3cr3t-inventado',
  'pg-s3cr3t-inventado', 'hunter2-inventado', 'tok_live_inventado', 'cvv-999', 'pin-4321', 'frase secreta inventada', '529.982.247-25', '8.8.4.4'];

function relay(port, host = 'host.docker.internal') {
  return new Promise(res => net.createServer(c => { const u = net.connect(port, host); c.pipe(u).pipe(c); u.on('error', () => c.destroy()); c.on('error', () => u.destroy()); })
    .listen(port, '127.0.0.1', res));
}

(async () => {
  await relay(PORT);
  const b = await puppeteer.launch({ args: ['--no-sandbox'] });
  const newPage = async (w) => {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: w > 500 ? 900 : 844, deviceScaleFactor: 1 });
    p._res = []; p._dialogs = [];
    p.on('response', r => { const u = new URL(r.url()); if (u.pathname.startsWith('/api/bug') || (u.pathname === '/api/demand' && r.request().method() === 'POST')) p._res.push({ m: r.request().method(), u: u.pathname, s: r.status() }); });
    p.on('response', async r => { if (new URL(r.url()).pathname === '/api/bug/draft' && r.request().method() === 'POST') { try { p._draft = await r.json(); } catch (e) { /* */ } } });
    p.on('pageerror', e => out.errors.push(String(e).slice(0, 300)));
    p.on('dialog', d => { p._dialogs.push(d.message()); d.dismiss(); });
    await p.goto(BASE, { waitUntil: 'networkidle2' });
    return p;
  };
  const go = async (p, h) => { await p.evaluate(h => { location.hash = h; }, h); await sleep(900); };
  const shot = (p, name, full = true) => p.screenshot({ path: `/shots/d16-${name}.png`, fullPage: full });
  const text = (p, sel = '#main') => p.evaluate(s => document.querySelector(s)?.innerText || '', sel);
  const upload = async (p, inputId, files) => { const h = await p.$(`#${inputId}`); await h.uploadFile(...files.map(f => `${FILES}/${f}`)); await sleep(700); };
  const click = async (p, sel) => { await p.evaluate(s => document.querySelector(s).click(), sel); };
  const waitPreview = (p, scope) => p.waitForFunction(pp => !document.querySelector(`[data-bug-draft="${pp}"].btn:not(.sm)`)?.disabled && document.querySelector(`#${pp === 'new' ? 'dem-bug' : 'bugx-' + pp}-prev`), { timeout: 20000, polling: 100 }, scope).catch(() => null);
  const btnState = (p, sel) => p.evaluate(s => ({ dis: document.querySelector(s)?.disabled, why: document.querySelector(s)?.getAttribute('aria-describedby') && document.getElementById(document.querySelector(s).getAttribute('aria-describedby'))?.textContent }), sel);
  const fill = async (p, { kind, title, detail, link }) => {
    await go(p, '#/demandas/bug');
    await p.waitForSelector('#dem-bug-title', { timeout: 10000 });
    if (kind) await click(p, `#dem-bug-kind-${kind}`);
    await p.click('#dem-bug-title', { clickCount: 3 }); await p.type('#dem-bug-title', title);
    if (detail) await p.type('#dem-bug-detail', detail);
    if (link) await p.type('#dem-bug-link', link);
  };
  const created = {};

  // ========== 1) Botão "Registrar bug" em Demandas e no Painel
  for (const w of [1440, 390]) {
    const p = await newPage(w);
    await go(p, '#/demandas'); await sleep(1500);
    const dem = await p.evaluate(() => [...document.querySelectorAll('#main a.btn')].map(a => a.textContent.trim()));
    await go(p, '#/painel'); await sleep(800);
    const pai = await p.evaluate(() => [...document.querySelectorAll('#main a.btn')].map(a => a.textContent.trim()));
    R(`botao-${w}`, { ok: dem.includes('Registrar bug') && pai.includes('Registrar bug'), dem, pai: pai.slice(0, 6) });
    await go(p, '#/demandas/bug'); await sleep(500);
    await shot(p, `formulario-${w}`);
    await p.close();
  }

  // ========== 2) Bug de PRODUTO: link do Jaeger (simulado) + log do corpus + imagem → prévia, 2 confirmações, 201, página
  for (const w of [1440, 390]) {
    const p = await newPage(w);
    await fill(p, { kind: 'produto', title: `Envio falha com endereço inválido (${w})`, detail: 'Pedido físico cancelado; shipping-service lança IllegalStateException.', link: 'http://localhost:16686/trace/4bf92f3577b34da6a3ce929d0e0e4736' });
    await upload(p, 'dem-bug-files', ['order-service.log', 'tela-erro.png']);
    const before = await btnState(p, '[data-bug-submit="new"]');
    await click(p, '[data-bug-draft="new"].btn:not(.sm)');
    await waitPreview(p, 'new'); await sleep(800);
    await p.evaluate(async () => { for (const i of document.querySelectorAll('#main img.evimg')) { i.loading = 'eager'; i.scrollIntoView(); await new Promise(r => setTimeout(r, 300)); } });
    await sleep(500);
    const prev = await p.evaluate(sens => {
      const pres = [...document.querySelectorAll('#main pre.buglog')].map(x => x.textContent);
      const all = pres.join('\n');
      return { pres: pres.length, masked: /\[MASCARADO:/.test(all), leaked: sens.filter(s => all.includes(s)), imgs: [...document.querySelectorAll('#main img.evimg')].map(i => ({ alt: i.alt, ok: i.complete && i.naturalWidth > 0 })),
        imgInsidePre: document.querySelectorAll('#main pre.buglog img').length, xss: window.__xss || null,
        red: [...document.querySelectorAll('#main .evl .red')].map(x => x.textContent), extracted: document.querySelector('#main .bugprev dl')?.innerText.slice(0, 600),
        consent: document.querySelector('#main fieldset.consent')?.innerText, warnings: [...document.querySelectorAll('#main .warnl li')].map(l => l.textContent) };
    }, SENSITIVE);
    const s0 = await btnState(p, '[data-bug-submit="new"]');
    await click(p, '#dem-bug-cprod'); await sleep(200);
    const s1 = await btnState(p, '[data-bug-submit="new"]');
    await click(p, '#dem-bug-cpub'); await sleep(200);
    const s2 = await btnState(p, '[data-bug-submit="new"]');
    await shot(p, `previa-produto-${w}`);
    // clareza: a UI diz que a máscara é por padrão (pode deixar passar) e que a prévia precisa ser LIDA?
    const clarity = await p.evaluate(() => { const t = document.querySelector('#main').innerText;
      return { porPadrao: /por padr(ão|ões)|padrões conhecidos|automátic|pode (deixar )?passar|não (pega|detecta|reconhece)|chaves? desconhecid/i.test(t), leiaPrevia: /leia|revise|confira/i.test(t), revisei: /Revisei a prévia mascarada/.test(t),
        aviso: document.querySelector('#main [id$="-maskwarn"]')?.textContent || null }; });
    const dfile = (p._draft?.evidences || []).find(e => /order-service\.log$/.test(e.file))?.file;
    const draftLog = dfile ? await p.evaluate(async (d, f) => { const r = await fetch(`/api/bug/draft/${d}/${f}`); return r.ok ? r.text() : null; }, p._draft.draft, dfile) : null;
    const draftPreview = (p._draft?.evidences || []).find(e => e.file === dfile)?.preview;
    await click(p, '[data-bug-submit="new"]');
    await p.waitForFunction(() => /^#\/demandas\/[^/]+$/.test(location.hash) && location.hash !== '#/demandas/bug' && document.querySelector('#sec-bug'), { timeout: 15000, polling: 100 }).catch(() => null);
    await sleep(1500);
    const post = p._res.filter(r => r.u === '/api/demand');
    const page = await p.evaluate(() => ({ hash: location.hash, head: document.querySelector('#main .overline')?.innerText, bugtag: !!document.querySelector('#main .overline .bugtag'),
      sec: document.querySelector('#sec-bug')?.innerText.slice(0, 900), links: [...document.querySelectorAll('#sec-bug .evl a')].map(a => a.getAttribute('href')), toc: [...document.querySelectorAll('nav.toc a')].map(a => a.textContent) }));
    const id = page.links[0] ? decodeURIComponent(page.links[0].split('/')[3]) : null;
    const served = id ? await p.evaluate(async (id, links) => Promise.all(links.map(async u => { const r = await fetch(u); const buf = await r.arrayBuffer();
      return { u, s: r.status, ct: r.headers.get('content-type'), nosniff: r.headers.get('x-content-type-options'), csp: r.headers.get('content-security-policy'), n: buf.byteLength, txt: /text\/plain/.test(r.headers.get('content-type') || '') ? new TextDecoder().decode(buf) : null }; })), id, page.links) : [];
    let stored = null;
    if (id) { const dir = JSON.parse(fs.readFileSync(`${DATA}/docs/squad/produto/bugs/${id}/bug.json`, 'utf8')).dir; stored = fs.readFileSync(`${DATA}/${dir}/evidencias/${dfile}`, 'utf8'); }
    const logServed = served.find(x => /order-service\.log$/.test(x.u));
    created[w] = { id, code: page.hash.split('/')[2] };
    await shot(p, `pagina-bug-${w}`);
    R(`produto-${w}`, { ok: clarity.porPadrao && /padrões conhecidos/.test(clarity.aviso || '') && before.dis && s0.dis && s1.dis && !s2.dis && prev.masked && !prev.leaked.length && !prev.imgInsidePre && !prev.xss && prev.imgs.every(i => i.ok) && post[0]?.s === 201 && page.bugtag && served.every(x => x.s === 200 && x.nosniff === 'nosniff') && stored === draftLog && logServed?.txt === stored,
      before: before.why, s0: s0.why, s1: s1.why, s2: s2.why, prev: { ...prev, consent: prev.consent?.slice(0, 200) }, clarity, post, page, served: served.map(({ txt, ...x }) => x), files: (p._draft?.evidences || []).map(e => e.file), storedEqualsPreviewDraft: stored === draftLog, previewIsFileHead: draftPreview === (stored || '').split('\n').slice(0, 200).join('\n').replace(/\n$/, ''), servedEqualsStored: logServed?.txt === stored });
    await p.close();
  }

  // ========== 3) Bug de OPERAÇÃO: só arquivos (log + imagem), sem link → declaração humana
  {
    const p = await newPage(1440);
    await fill(p, { kind: 'operacao', title: 'Squad Control devolve 500 ao registrar demanda' });
    await upload(p, 'dem-bug-files', ['squad-control.log', 'tela-erro.png']);
    await click(p, '[data-bug-draft="new"].btn:not(.sm)'); await waitPreview(p, 'new'); await sleep(600);
    const pv = await p.evaluate(() => ({ pre: document.querySelector('#main pre.buglog')?.textContent, extracted: document.querySelector('#main .bugprev dl')?.innerText,
      red: document.querySelector('#main .evl .red')?.textContent, aviso: document.querySelector('#main [id$="-maskwarn"]')?.textContent || null }));
    await shot(p, 'previa-operacao-chave-desconhecida-1440');
    await click(p, '#dem-bug-cprod'); await click(p, '#dem-bug-cpub'); await sleep(200);
    await click(p, '[data-bug-submit="new"]');
    await p.waitForFunction(() => document.querySelector('#sec-bug'), { timeout: 15000, polling: 100 }).catch(() => null); await sleep(1200);
    const sec = await text(p, '#sec-bug');
    R('operacao', { ok: p._res.some(r => r.u === '/api/demand' && r.s === 201) && /declaração humana/.test(sec) && /produtivo/.test(sec) && !/abc123|xyz789/.test(pv.pre || '') && /padrões conhecidos/.test(pv.aviso || ''), pwdAuthEmClaro: /abc123|xyz789/.test(pv.pre || ''), red: pv.red, aviso: pv.aviso, pre: pv.pre, sec: sec.slice(0, 400), hash: await p.evaluate(() => location.hash) });
    created.op = { code: (await p.evaluate(() => location.hash)).split('/')[2] };
    await p.close();
  }

  // ========== 4) 422 segredo_no_texto e 409 tipo_divergente (exibição)
  for (const w of [1440, 390]) {
    const p = await newPage(w);
    await fill(p, { kind: 'produto', title: "falha password='hunter2' no job" });
    await upload(p, 'dem-bug-files', ['tela-erro.png']);
    await click(p, '[data-bug-draft="new"].btn:not(.sm)'); await waitPreview(p, 'new'); await sleep(500);
    await click(p, '#dem-bug-cprod'); await click(p, '#dem-bug-cpub'); await sleep(200);
    await click(p, '[data-bug-submit="new"]'); await sleep(1500);
    const m422 = await p.evaluate(() => ({ msg: [...document.querySelectorAll('#main .fail[role=status], #main p.fail')].map(x => x.textContent), hash: location.hash }));
    await p.evaluate(() => document.querySelector('#main .fail[role=status]')?.scrollIntoView({ block: 'center' }));
    await shot(p, `422-segredo-${w}`, false);
    R(`422-${w}`, { ok: p._res.some(r => r.u === '/api/demand' && r.s === 422) && m422.msg.some(t => /segredo/.test(t)) && m422.hash === '#/demandas/bug', ...m422 });
    // 409: o corpo sai com o tipo trocado (a UI normal marca a prévia como desatualizada; simula corrida/rascunho de outro tipo)
    await p.evaluate(() => { const t = document.getElementById('dem-bug-title'); t.value = ''; t.dispatchEvent(new Event('input', { bubbles: true })); });
    await p.type('#dem-bug-title', 'Pagamento lento no checkout');
    await sleep(300);
    await p.setRequestInterception(true);
    let swapped = null;
    p.on('request', r => { if (r.isInterceptResolutionHandled()) return;
      if (r.method() === 'POST' && new URL(r.url()).pathname === '/api/demand') { try { const b = JSON.parse(r.postData() || '{}'); swapped = b.kind; b.kind = b.kind === 'produto' ? 'operacao' : 'produto'; return r.continue({ postData: JSON.stringify(b) }); } catch (e) { swapped = String(e); } }
      r.continue(); });
    const st = await btnState(p, '[data-bug-submit="new"]');
    const wr = p.waitForResponse(r => new URL(r.url()).pathname === '/api/demand', { timeout: 10000 }).catch(() => null);
    await click(p, '[data-bug-submit="new"]'); await wr; await sleep(1200);
    const m409 = await p.evaluate(() => ({ msg: [...document.querySelectorAll('#main p.fail')].map(x => x.textContent), prev: !!document.querySelector('#dem-bug-prev'), hash: location.hash }));
    await p.evaluate(() => document.querySelector('#main .fail[role=status]')?.scrollIntoView({ block: 'center' }));
    await shot(p, `409-tipo-${w}`, false);
    R(`409-${w}`, { ok: p._res.some(r => r.u === '/api/demand' && r.s === 409) && m409.msg.some(t => /diverge/.test(t) && /prévia de novo/.test(t) && /registrar o bug/.test(t)) && !m409.msg.some(t => /acrescentar/i.test(t)), verboAcrescentar: m409.msg.some(t => /acrescentar/i.test(t)), btnAntes: st, swapped, res: p._res.slice(-2), ...m409 });
    await p.close();
  }

  // ========== 5) Selo BUG, filtro f=bugs e backlog/painel
  for (const w of [1440, 390]) {
    const p = await newPage(w);
    await go(p, '#/demandas?f=bugs'); await sleep(800);
    const f = await p.evaluate(() => ({ seg: [...document.querySelectorAll('nav.seg a')].map(a => a.textContent.trim()), rows: [...document.querySelectorAll('#main ul.rows > li, #main li')].filter(l => l.querySelector('.bugtag')).length,
      tags: [...document.querySelectorAll('#main .bugtag')].map(t => ({ t: t.textContent, title: t.title })).slice(0, 3), noBug: [...document.querySelectorAll('#main a.ttl')].filter(a => !a.querySelector('.bugtag')).length }));
    await shot(p, `filtro-bugs-${w}`);
    const contrast = await p.evaluate(() => { const t = document.querySelector('#main .bugtag'); if (!t) return null; const cs = getComputedStyle(t); return { color: cs.color, bg: cs.backgroundColor }; });
    R(`filtro-${w}`, { ok: f.tags.length > 0 && f.noBug === 0 && f.seg.some(s => /^Bugs/.test(s)), ...f, contrast });
    await p.close();
  }

  // ========== 6) Acrescentar evidência (bug de produto em andamento) e prévia de log longo (200 linhas)
  for (const w of [1440, 390]) {
    const c = created[w]; if (!c?.id) { R(`acrescentar-${w}`, { ok: false, erro: 'bug não criado' }); continue; }
    const n0 = JSON.parse(fs.readFileSync(`${DATA}/docs/squad/produto/bugs/${c.id}/bug.json`, 'utf8')).evidences;
    const p = await newPage(w);
    await go(p, `#/demandas/${c.code}`); await sleep(1200);
    await p.evaluate(id => { const d = document.getElementById(`bugadd-${id}`); d.open = true; d.scrollIntoView(); }, c.id); await sleep(400);
    await upload(p, `bugx-${c.id}-files`, ['longo.log']);
    await click(p, `[data-bug-draft="${c.id}"].btn:not(.sm)`); await waitPreview(p, c.id); await sleep(700);
    const lp = await p.evaluate(id => { const pre = document.querySelector(`#bugadd-${id} pre.buglog`)?.textContent || ''; const t = document.getElementById(`bugadd-${id}`).innerText;
      return { linhas: pre.split('\n').length, mostraLinha501: /SEGREDO_NA_LINHA_501/.test(pre), avisaTruncamento: /200 (primeiras )?linhas|primeiras 200|de 501|truncad|mostrando/i.test(t), abrirArquivo: !!document.querySelector(`#bugadd-${id} .evl a`),
        mostrando: document.querySelector(`#bugadd-${id} [data-bug-trunc]`)?.textContent || null, linkInteiro: [...document.querySelectorAll(`#bugadd-${id} .evl a`)].map(a => ({ t: a.textContent, href: a.getAttribute('href') })),
        verInteiro: document.querySelector(`#bugadd-${id} details[id$="-full"] summary`)?.textContent || null }; }, c.id);
    // recomendação ao Frontend: com a prévia truncada, o botão só deveria habilitar depois de abrir o arquivo inteiro.
    // Aqui só MEDIMOS: marca as 2 confirmações ANTES de abrir o arquivo inteiro e vê se o botão já habilita.
    await click(p, `#bugx-${c.id}-cprod`); await click(p, `#bugx-${c.id}-cpub`); await sleep(200);
    const semLer = await btnState(p, `[data-bug-append="${c.id}"]`);
    lp.exigeLeitura = semLer.dis ? { exige: 'sim', motivo: semLer.why } : { exige: 'não', obs: 'habilita com as 2 caixas sem abrir o arquivo inteiro' };
    // o arquivo inteiro (mascarado) chega à tela: abre o "Ver o arquivo inteiro" e lê a linha 501
    lp.inteiro = await p.evaluate(async id => { const d = document.querySelector(`#bugadd-${id} details[id$="-full"]`); if (!d) return null; d.open = true; d.dispatchEvent(new Event('toggle')); await new Promise(r => setTimeout(r, 900));
      const pre = d.querySelector('pre.buglog')?.textContent || ''; const u = d.getAttribute('data-bug-log'); const srv = u ? await (await fetch(u)).text() : null;
      return { linhas: pre.replace(/\n$/, '').split('\n').length, linha501: pre.split('\n').find(l => /SEGREDO_NA_LINHA_501/.test(l)) || null, segredoEmClaro: /nao-aparece-na-previa/.test(pre + (srv || '')), igualAoServidor: srv != null && pre === srv }; }, c.id);
    await shot(p, `acrescentar-previa-${w}`);
    await click(p, `[data-bug-append="${c.id}"]`); await sleep(2000);
    const after = await p.evaluate(id => ({ msg: document.querySelector(`#bugadd-${id} .ok-msg, #sec-bug .ok-msg`)?.textContent || [...document.querySelectorAll('#sec-bug [role=status]')].map(x => x.textContent).join(' | '),
      files: [...document.querySelectorAll('#sec-bug .evl .fn')].map(x => x.textContent) }), c.id);
    await shot(p, `acrescentar-feito-${w}`);
    const bj = JSON.parse(fs.readFileSync(`${DATA}/docs/squad/produto/bugs/${c.id}/bug.json`, 'utf8'));
    R(`acrescentar-${w}`, { ok: p._res.some(r => r.u === '/api/bug/evidence' && r.s === 201) && /Mostrando 200 de 501 linhas/.test(lp.mostrando || '') && /arquivo inteiro/i.test(lp.verInteiro || '') && lp.inteiro?.linhas === 501 && /\[MASCARADO:segredo\]/.test(lp.inteiro?.linha501 || '') && !lp.inteiro?.segredoEmClaro && lp.inteiro?.igualAoServidor && !lp.mostraLinha501 && bj.evidences.length === n0.length + 1 && JSON.stringify(bj.evidences.slice(0, n0.length)) === JSON.stringify(n0), previaLonga: lp, after, evidencesNoBugJson: bj.evidences.map(e => e.file) });
    await p.close();
  }
  // demanda comum: sem "Acrescentar evidência"; POST direto → 409 (CA-18)
  {
    const p = await newPage(1440);
    const r409 = await p.evaluate(async () => { const st = await (await fetch('/api/state')).json(); const t = st.log.find(e => e.type === 'task' && e.agent === 'humano' && !e.nature);
      const r = await fetch('/api/bug/evidence', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ demand: t.id, draft: '0'.repeat(32), consent: { production: true, public: true } }) });
      return { s: r.status, j: await r.json() }; });
    R('comum-409', { ok: r409.s === 409, ...r409 });
    await p.close();
  }

  // ========== 7) Produto › Jaeger/Grafana: "Abrir bug a partir deste trace/painel" (produtivo) e ausência nos links do teste
  for (const w of [1440, 390]) {
    const p = await newPage(w);
    const res = {};
    for (const tool of ['jaeger', 'grafana']) {
      await go(p, `#/produto/${tool}`); await sleep(1200);
      res[tool] = await p.evaluate(tool => ({ btn: document.getElementById(`bug-from-${tool}`)?.textContent, href: document.getElementById(`bug-from-${tool}`)?.getAttribute('href'),
        noTeste: [...document.querySelectorAll('#te-slot a')].filter(a => /bug/i.test(a.textContent)).length }), tool);
      if (tool === 'jaeger') await shot(p, `produto-jaeger-${w}`, false);
      await click(p, `#bug-from-${tool}`); await sleep(1000);
      res[tool].form = await p.evaluate(() => ({ hash: location.hash, kind: document.querySelector('input[name="dem-bug-kind"]:checked')?.value, notice: document.querySelector('#main .bugf .notice')?.textContent,
        focus: document.activeElement?.id }));
      if (tool === 'jaeger') await shot(p, `a-partir-do-trace-${w}`, false);
    }
    R(`produto-links-${w}`, { ok: ['jaeger', 'grafana'].every(t => res[t].btn && res[t].form.kind === 'produto' && res[t].noTeste === 0 && /Copie o link/.test(res[t].form.notice || '')), ...res });
    await p.close();
  }

  R('erros-js', out.errors);
  fs.writeFileSync('/shots/d16-bugs-result.json', JSON.stringify(out, null, 2));
  await b.close();
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
