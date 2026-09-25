// D19 (402e76f187f9) — delegação pela conversa: roteiro de navegador do QA (CA-26, §11). Checklist:
// tests/ui/checklist-delegacao-d19.md.
// Servidor REAL deste worktree com dados TEMPORÁRIOS montados pelo e2e (nunca o :7070 nem o log real) e runner
// SIMULADO (tests/squad/delegacao_fake_runner.py). O e2e roda o CA-1 inteiro na D1 (delegação concluída) e deixa a
// D2 com o B6 aberto:
//   S=<scratchpad>/qa-d19
//   python3 tests/squad/e2e_delegacao_d19.py --base $S/ui --serve-ui 7493 &       # espera "UI PRONTA"
//   docker run --rm --add-host=host.docker.internal:host-gateway -e NODE_PATH=/usr/src/app/node_modules -e PORT=7493 \
//     -v "$PWD/tests/ui:/shots" zenika/alpine-chrome:with-puppeteer node /shots/d19-delegacao.js
//   kill %1
// As rotas /api/conversas* exigem Host local: repasse TCP DENTRO do container (127.0.0.1:PORT → host.docker.internal).
// Saída: tests/ui/d19-delegacao-result.json + capturas tests/ui/d19-*.png. Código ≠ 0 se alguma verificação falhar.
const puppeteer = require('puppeteer');
const net = require('net');
const fs = require('fs');
const PORT = Number(process.env.PORT || 7493), BASE = `http://127.0.0.1:${PORT}/`, SHOTS = '/shots';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = { results: {}, checks: [], errors: [] };
const R = (k, v) => { out.results[k] = v; console.error(`[${k}] ${JSON.stringify(v).slice(0, 500)}`); };
const C = (name, ok, info) => { out.checks.push({ name, ok: !!ok, info }); console.error(`${ok ? 'ok ' : 'FALHOU'} ${name}`); };
const relay = port => new Promise(res => net.createServer(c => { const u = net.connect(port, 'host.docker.internal'); c.pipe(u).pipe(c); u.on('error', () => c.destroy()); c.on('error', () => u.destroy()); }).listen(port, '127.0.0.1', res));

(async () => {
  await relay(PORT);
  const b = await puppeteer.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'], executablePath: process.env.PUPPETEER_EXECUTABLE_PATH });
  const page = async (w, theme = 'light', hash = '#/painel') => {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: w > 500 ? 900 : 844, deviceScaleFactor: 1 });
    p.on('pageerror', e => out.errors.push(String(e).slice(0, 300)));
    p.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|EventSource|net::ERR/.test(m.text())) out.errors.push(m.text().slice(0, 300)); });
    await p.evaluateOnNewDocument(t => { try { localStorage.setItem('sc-theme', t); } catch (e) { /* */ } }, theme);
    await p.goto(BASE + hash, { waitUntil: 'domcontentloaded' });
    await p.waitForFunction(() => typeof state !== 'undefined' && state, { timeout: 60000 }); await sleep(800);
    return p;
  };
  const waitIdle = (p, ms = 25000) => p.waitForFunction(() => document.getElementById('chat-stop').hidden && !document.getElementById('chat-send').disabled && document.querySelectorAll('#chat-msgs > li.c-msg').length > 0, { timeout: ms });
  const hscroll = p => p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  const theme = p => p.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const acts = p => p.$$eval('[data-alert]', ls => ls.map(l => [l.dataset.alert, [...l.querySelectorAll('.act a, .act span')].map(a => a.textContent.trim()).filter(Boolean)]));

  // ---------------------------------------------------------------- 1440 claro: B6 → pedido (teclado) → cartão → confirmar
  let p = await page(1440, 'light');
  const a0 = await acts(p); R('painel_acoes', a0);
  const b6 = a0.find(([id]) => id.startsWith('pr-conflict:'));
  C('B6 no Painel com "Delegar correção"', b6 && b6[1].some(t => /Delegar correção/.test(t)), b6);
  C('B6 da D1 (resolvido) não aparece', a0.filter(([id]) => id.startsWith('pr-conflict:')).length === 1, a0.map(x => x[0]));
  await p.screenshot({ path: `${SHOTS}/d19-1440-claro-painel.png` });
  // teclado: Tab até o botão "Delegar correção" e Enter
  let reached = false;
  for (let i = 0; i < 120 && !reached; i++) { await p.keyboard.press('Tab'); reached = await p.evaluate(() => !!document.activeElement?.matches?.('[data-deleg-ask^="pr-conflict"]')); }
  C('teclado alcança "Delegar correção" com Tab', reached);
  await p.keyboard.press('Enter'); await sleep(1800);
  const ped = await p.evaluate(() => ({ hash: location.hash, open: !document.getElementById('chat').hidden, value: document.getElementById('chat-text').value, msgs: document.querySelectorAll('#chat-msgs > li.c-msg').length, focus: document.activeElement.id }));
  R('pedido', ped);
  C('pedido preenche o campo e NÃO envia', ped.open && /PR #172/.test(ped.value) && ped.msgs === 0, ped);
  C('foco no campo da conversa', ped.focus === 'chat-text', ped.focus);
  await p.screenshot({ path: `${SHOTS}/d19-1440-claro-pedido-preenchido.png` });
  await p.keyboard.press('Enter'); await waitIdle(p);
  const card = await p.evaluate(() => { const c = document.querySelector('.c-prop.deleg'); return c && { role: c.getAttribute('role'), txt: c.innerText.replace(/\s+/g, ' ').slice(0, 800), bloco: /```delegar|"tipo":/.test(document.getElementById('chat-msgs').textContent), count: c.querySelector('.dg-count')?.textContent, hasTextarea: !!c.querySelector('textarea') }; });
  R('cartao', card);
  C('cartão role=group com tarefa editável e contador n/2000', card && card.role === 'group' && card.hasTextarea && /\/2000/.test(card.count || ''), card);
  C('cartão mostra agente, risco (texto), tentativa 1/2 e efeito "o merge continua seu"', card && /Orquestrador/i.test(card.txt) && /moderado/i.test(card.txt) && /1\/2/.test(card.txt) && /merge continua seu/i.test(card.txt), card && card.txt);
  C('bloco ```delegar fora do texto exibido', card && !card.bloco);
  await p.screenshot({ path: `${SHOTS}/d19-1440-claro-cartao.png` });
  const ta = await p.$('.c-prop.deleg textarea'); await ta.focus(); await p.keyboard.press('End'); await p.keyboard.type(' Rodar a suíte do order-service.');
  const cnt = await p.$eval('.c-prop.deleg .dg-count', e => e.textContent); R('contador', cnt);
  // confirma pelo teclado: Tab até o botão Confirmar delegação
  reached = false;
  for (let i = 0; i < 10 && !reached; i++) { await p.keyboard.press('Tab'); reached = await p.evaluate(() => !!document.activeElement?.matches?.('[data-deleg-confirm]')); }
  C('teclado alcança "Confirmar delegação" a partir da tarefa', reached);
  await p.keyboard.press('Enter'); await sleep(1800);
  const conf = await p.evaluate(() => ({ txt: document.querySelector('.c-prop.deleg')?.innerText.replace(/\s+/g, ' ').slice(-300), live: document.getElementById('sr-live')?.textContent }));
  R('confirmado', conf);
  C('cartão confirmado mostra estado (aguardando o plantão)', /confirmad|aguardando|plantão/i.test(conf.txt || ''), conf);
  await p.screenshot({ path: `${SHOTS}/d19-1440-claro-confirmado.png` });
  // painel: B6 da D2 agora "Delegado — em execução"
  await p.goto(BASE + '#/painel', { waitUntil: 'domcontentloaded' }); await sleep(3500);
  const a1 = await acts(p); R('painel_depois', a1);
  const b6b = a1.find(([id]) => id.startsWith('pr-conflict:'));
  C('B6 com delegação ativa mostra "Delegado" sem botão', b6b && b6b[1].some(t => /Delegado/.test(t)) && !b6b[1].some(t => /^Delegar correção$/.test(t)), b6b);

  // ---------------------------------------------------------------- XSS: texto do modelo nunca vira HTML
  await p.goto(BASE + '#/painel?conversa=nova', { waitUntil: 'domcontentloaded' }); await sleep(1200);
  await p.type('#chat-text', 'DELEGAR:{"demanda":"D1","tipo":"ajuste-pontual","tarefa":"<img src=x onerror=window.__xss=1> <b>negrito</b>"}');
  await p.keyboard.press('Enter'); await waitIdle(p);
  const xss = await p.evaluate(() => ({ flag: window.__xss || null, imgs: document.querySelectorAll('#chat-msgs img').length, bolds: document.querySelectorAll('.c-prop.deleg b').length, ta: document.querySelector('.c-prop.deleg textarea')?.value }));
  R('xss', xss);
  C('tarefa do modelo exibida como texto (sem <img>/<b> interpretados)', !xss.flag && xss.imgs === 0 && xss.bolds === 0 && /<img/.test(xss.ta || ''), xss);
  await p.close();

  // ---------------------------------------------------------------- tela da demanda (D1 concluída, D2 pedida) 1440/390 claro/escuro
  for (const [w, th] of [[1440, 'light'], [1440, 'dark'], [390, 'light'], [390, 'dark']]) {
    const tag = `${w}-${th === 'light' ? 'claro' : 'escuro'}`;
    p = await page(w, th, '#/demandas/D1');
    await sleep(2500);
    const d1 = await p.evaluate(() => ({ sec: document.querySelector('#sec-delegacoes')?.innerText.replace(/\s+/g, ' ').slice(0, 900), marks: document.querySelectorAll('#sec-registro .tag.dg').length, links: [...document.querySelectorAll('#sec-delegacoes a')].map(a => a.textContent.trim()).slice(0, 10), badge: document.querySelector('.page-head .tag.dg')?.textContent || null }));
    R(`d1_${tag}`, d1);
    C(`[${tag}] D1: seção Delegações com quem pediu, tipo, agente, tarefa, risco, estado e resultado`,
      d1.sec && /Você, pela conversa/i.test(d1.sec) && /conflito/i.test(d1.sec) && /Orquestrador/i.test(d1.sec) && /order-service/.test(d1.sec) && /moderado/i.test(d1.sec) && /conclu/i.test(d1.sec), d1.sec);
    C(`[${tag}] D1: eventos com delegation marcados na linha do tempo`, d1.marks >= 3, d1.marks);
    C(`[${tag}] D1 concluída sem badge "em andamento"`, !d1.badge || !/andamento/i.test(d1.badge), d1.badge);
    C(`[${tag}] sem rolagem horizontal`, !(await hscroll(p)));
    await p.evaluate(() => document.querySelector('#sec-delegacoes')?.scrollIntoView());
    await p.screenshot({ path: `${SHOTS}/d19-${tag}-demanda-d1.png` });
    await p.goto(BASE + '#/demandas/D2', { waitUntil: 'domcontentloaded' }); await sleep(2500);
    const d2 = await p.evaluate(() => ({ badge: document.querySelector('.page-head .tag.dg')?.textContent || null, sec: document.querySelector('#sec-delegacoes')?.innerText.replace(/\s+/g, ' ').slice(0, 400), bg: getComputedStyle(document.body).backgroundColor }));
    R(`d2_${tag}`, d2);
    C(`[${tag}] D2: badge "Delegação em andamento" e estado pedida/aguardando`, d2.badge && /Delega/i.test(d2.badge) && /pedida|aguardando/i.test(d2.sec || ''), d2);
    C(`[${tag}] tema aplicado`, th === 'dark' ? /rgb\((\d{1,2}), (\d{1,2}), (\d{1,2})\)/.test(d2.bg) : !/rgb\((\d{1,2}), (\d{1,2}), (\d{1,2})\)/.test(d2.bg), d2.bg);
    await p.screenshot({ path: `${SHOTS}/d19-${tag}-demanda-d2.png` });
    if (w === 390) {
      await p.goto(BASE + '#/painel?conversa=nova', { waitUntil: 'domcontentloaded' }); await sleep(1200);
      await p.type('#chat-text', 'DELEGAR:{"demanda":"D1","tipo":"ajuste-pontual","tarefa":"Ajustar o texto do cupom"}');
      await p.keyboard.press('Enter'); await waitIdle(p);
      const small = await p.evaluate(() => [...document.querySelectorAll('.c-prop.deleg button, .c-prop.deleg textarea')].filter(e => e.offsetParent && e.getBoundingClientRect().height < 40).map(e => e.textContent || e.tagName));
      C(`[${tag}] cartão: alvos de toque ≥ 40 px e sem rolagem horizontal`, small.length === 0 && !(await hscroll(p)), small);
      await p.evaluate(() => document.querySelector('.c-prop.deleg')?.scrollIntoView());
      await p.screenshot({ path: `${SHOTS}/d19-${tag}-cartao.png` });
    }
    await p.close();
  }
  R('pageErrors', out.errors);
  C('sem erros de página', out.errors.length === 0, out.errors);
  fs.writeFileSync(`${SHOTS}/d19-delegacao-result.json`, JSON.stringify(out, null, 1));
  await b.close();
  const failed = out.checks.filter(c => !c.ok);
  console.error(`\n${out.checks.length - failed.length}/${out.checks.length} verificações ok`);
  process.exit(failed.length ? 1 : 0);
})().catch(e => { console.error('FALHOU', e); process.exit(2); });
