// D21 (71b7d9bc3313) — imagens na conversa: roteiro de navegador do QA (contrato docs/contracts/imagens-na-conversa.md
// §8 e §10: CA-I1…CA-I8, CA-I12, CA-I21 + retry de rede). Base: roteiro do Frontend (117ffb6), mais o CA-I21 por
// teclado (Tab/Shift+Tab passando pelo clipe, anexar/remover/enviar só com teclado, visualizador). Checklist e resultado
// por CA: tests/ui/checklist-imagens-d21.md.
//
// Isolamento: servidor do WORKTREE com dados TEMPORÁRIOS (nunca o :7070 nem o log real) e runner SIMULADO
// (tests/squad/conversa_fake_runner.py, que lê o stdin stream-json e grava .sessao/fake_last_stdin.json):
//   S=<scratch>/qa-d21; python3 -c "import sys,pathlib; sys.path.insert(0,'tests/squad'); import test_conversa_anexos_d21 as h; \
//     h.make_data(pathlib.Path('$S/ui-data')); h.prepare_fixtures(pathlib.Path('$S/fx'))"; mkdir -p $S/ui-data/.squad/conversas
//   SQUAD_ROOT_DATA=$S/ui-data SQUAD_LOG=$S/ui-data/docs/squad/memory/decisions.jsonl SQUAD_TRANSCRIPTS=$S/trans \
//     SQUAD_TESTENV_PROBE=0 SQUAD_TESTENV_SPAWN=0 SQUAD_CHAT_RUNNER=fake SQUAD_CHAT_FAKE=$PWD/tests/squad/conversa_fake_runner.py \
//     SQUAD_CHAT_TIMEOUT_S=20 SQUAD_GH=/usr/bin/false SQUAD_GIT=/usr/bin/false python3 tools/squad/server.py --port <livre> &
//   docker run --rm --add-host=host.docker.internal:host-gateway -e TZ=America/Sao_Paulo -e PORT=<livre> \
//     -e NODE_PATH=/usr/src/app/node_modules -v "$PWD/tests/ui:/shots" -v "$S/fx:/fx:ro" \
//     -v "$S/ui-data/.squad/conversas:/conv" zenika/alpine-chrome:with-puppeteer node /shots/d21-imagens.js
// As rotas /api/conversas* exigem Host local: repasse TCP DENTRO do container (127.0.0.1:PORT → host.docker.internal).
// Saída: tests/ui/d21-imagens-result.json + capturas tests/ui/d21-*.png. Código ≠ 0 se alguma verificação falhar.
const puppeteer = require('puppeteer');
const net = require('net');
const fs = require('fs');
const PORT = Number(process.env.PORT || 7391);
const BASE = `http://127.0.0.1:${PORT}/`;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = { results: {}, errors: [], console: [] };
const R = (k, v) => { out.results[k] = v; console.error(`[${k}] ${v.ok ? 'PASS' : 'FAIL'} ${JSON.stringify(v).slice(0, 900)}`); };
const relay = port => new Promise(res => net.createServer(c => {
  const u = net.connect(port, 'host.docker.internal');
  c.pipe(u).pipe(c); u.on('error', () => c.destroy()); c.on('error', () => u.destroy());
}).listen(port, '127.0.0.1', res));
const FX = n => [fs.readFileSync(`/fx/${n}`).toString('base64'), n];
const TYPE = { png: 'image/png', jpg: 'image/jpeg', webp: 'image/webp', gif: 'image/gif', pdf: 'application/pdf', heic: 'image/heic' };
const F = (n, name = n) => { const [b] = FX(n); return [b, name, TYPE[n.split('.').pop()] || '']; };

(async () => {
  await relay(PORT);
  const b = await puppeteer.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'], executablePath: process.env.PUPPETEER_EXECUTABLE_PATH });
  const uploads = [], removes = [];
  const page = async (w, { theme = 'light', hash = '#/painel?conversa=nova', reduce = false } = {}) => {
    const p = await b.newPage();
    await p.setViewport({ width: w, height: w > 500 ? 900 : 844, deviceScaleFactor: 1 });
    await p.emulateTimezone('America/Sao_Paulo');
    if (reduce) await p.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'reduce' }]);
    p.on('pageerror', e => out.errors.push(String(e).slice(0, 300)));
    p.on('console', m => { if (m.type() === 'error') out.console.push(m.text().slice(0, 200)); });
    p.on('request', r => { if (r.method() === 'POST' && /\/anexos$/.test(r.url())) uploads.push(r.url()); if (/\/remover$/.test(r.url())) removes.push(r.url()); });
    await p.evaluateOnNewDocument(t => {
      try { localStorage.setItem('sc-theme', t); } catch (e) { /* */ }
      window.__live = []; window.__alert = []; window.__prog = []; window.__posts = [];
      window.__mkFile = (b64, name, type) => new File([Uint8Array.from(atob(b64), c => c.charCodeAt(0))], name, { type });
      const f = window.fetch; window.fetch = (u, o) => { if (o && o.method === 'POST' && /\/mensagens$/.test(String(u))) window.__posts.push(o.body); return f(u, o); };
      document.addEventListener('DOMContentLoaded', () => {
        for (const [id, arr] of [['sr-live', '__live'], ['sr-alert', '__alert']]) { const el = document.getElementById(id); if (el) new MutationObserver(() => { const t = el.textContent.trim(); if (t) window[arr].push(t); }).observe(el, { childList: true, characterData: true, subtree: true }); }
        const tl = document.getElementById('chat-tray-list');
        if (tl) new MutationObserver(() => { for (const li of tl.children) { const v = li.querySelector('.c-att-veil'); window.__prog.push({ t: performance.now(), k: li.dataset.k, cls: li.className, role: v.getAttribute('role'), now: v.getAttribute('aria-valuenow'), label: v.getAttribute('aria-label'), rm: li.querySelector('.c-att-rm').textContent }); } })
          .observe(tl, { subtree: true, attributes: true, childList: true, characterData: true });
      });
    }, theme);
    await p.goto(BASE + hash, { waitUntil: 'domcontentloaded' });
    await p.waitForFunction(() => typeof state !== 'undefined' && state, { timeout: 60000 }); await sleep(600);
    return p;
  };
  const paste = (p, files, text, sel = '#chat-text') => p.evaluate((files, text, sel) => {
    const dt = new DataTransfer(); for (const [b, n, t] of files) dt.items.add(__mkFile(b, n, t)); if (text) dt.setData('text/plain', text);
    const el = document.querySelector(sel); el.focus(); const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
    el.dispatchEvent(ev); return ev.defaultPrevented;
  }, files, text, sel);
  const drag = (p, type, files, sel = '#chat-msgs', text) => p.evaluate((type, files, sel, text) => {
    const dt = new DataTransfer(); for (const [b, n, t] of files) dt.items.add(__mkFile(b, n, t)); if (text) dt.setData('text/plain', text);
    const ev = new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true }); document.querySelector(sel).dispatchEvent(ev);
    return { prevented: ev.defaultPrevented, overlay: !document.getElementById('chat-drop').hidden, overlayText: document.getElementById('chat-drop').textContent.trim() };
  }, type, files, sel, text);
  const tray = p => p.evaluate(() => ({ cards: [...document.querySelectorAll('#chat-tray-list > li')].map(li => ({ cls: li.className, alt: li.querySelector('img').alt, x: li.querySelector('.c-att-x').getAttribute('aria-label') })),
    msg: document.getElementById('chat-tray-msg').hidden ? '' : document.getElementById('chat-tray-msg').textContent.trim(), note: !document.getElementById('chat-tray-note').hidden && document.getElementById('chat-tray-note').textContent.trim(),
    send: document.getElementById('chat-send').disabled, hint: document.getElementById('chat-hint').textContent.trim(), text: document.getElementById('chat-text').value }));
  const waitReady = (p, n, ms = 8000) => p.waitForFunction(n => { const l = [...document.querySelectorAll('#chat-tray-list > li')]; return l.length === n && l.every(li => /ready|err/.test(li.className)); }, { timeout: ms }, n);
  const waitIdle = (p, ms = 20000) => p.waitForFunction(() => document.getElementById('chat-stop').hidden && !document.getElementById('chat-send').disabled && document.querySelectorAll('#chat-msgs > li.c-msg--orq').length > 0, { timeout: ms });
  const shot = (p, n) => p.screenshot({ path: `/shots/d21-${n}.png` });
  const cid = p => p.evaluate(() => chat.id);

  // ===== 1440 claro: colar
  const p = await page(1440);
  let u0 = uploads.length;
  const pv = await paste(p, [F('print.png')], '', '#chat-text');
  await p.waitForSelector('#chat-tray-list > li [role=progressbar]', { timeout: 3000 }).catch(() => null);
  await shot(p, '1440-claro-enviando');
  await waitReady(p, 1);
  let t1 = await tray(p);
  R('CA-I1-colar-no-campo', { ok: pv && t1.cards.length === 1 && /ready/.test(t1.cards[0].cls) && uploads.length - u0 === 1 && t1.text === '' && /Imagens vão ao fornecedor de IA/.test(t1.note || ''), pv, t1, up: uploads.length - u0 });
  const prog1 = await p.evaluate(() => window.__prog);
  const first = prog1.find(x => x.role === 'progressbar'), last = prog1.find(x => /ready/.test(x.cls));
  R('CA-I5-minimo-400ms', { ok: !!first && !!last && last.t - first.t >= 380 && prog1.some(x => /proc/.test(x.cls)), ms: first && last ? Math.round(last.t - first.t) : null, labels: [...new Set(prog1.map(x => x.label).filter(Boolean))].slice(0, 6) });
  await sleep(1100); await shot(p, '1440-claro-bandeja');
  // colar com foco na lista
  u0 = uploads.length;
  await p.evaluate(() => { const l = document.getElementById('chat-msgs'); l.tabIndex = -1; });
  const pv2 = await paste(p, [F('segundo.png')], '', '#chat-msgs');
  await waitReady(p, 2);
  R('CA-I1-colar-na-lista', { ok: pv2 && uploads.length - u0 === 1, pv2 });
  // colar texto → nada; texto + imagem → só texto
  u0 = uploads.length;
  const pt = await paste(p, [], 'só texto'); const pti = await paste(p, [F('print.png')], 'célula do Excel'); await sleep(600);
  R('CA-I2-colar-texto', { ok: !pt && !pti && uploads.length === u0 && (await tray(p)).cards.length === 2, pt, pti });
  // remover cartão pronto
  const rm0 = removes.length;
  await p.click('#chat-tray-list > li:nth-child(2) .c-att-x'); await sleep(500);
  const t2 = await tray(p), fAfter = await p.evaluate(() => document.activeElement?.getAttribute('aria-label') || document.activeElement?.id);
  R('CA-I6-remover', { ok: t2.cards.length === 1 && removes.length - rm0 === 1 && (await p.evaluate(() => window.__live)).includes('Imagem removida'), t2, foco: fAfter });
  // enviar texto + 1 imagem
  await p.type('#chat-text', 'O que é isto? IMGECO'); await p.keyboard.press('Enter');
  await waitIdle(p);
  const hist1 = await p.evaluate(() => { const li = [...document.querySelectorAll('#chat-msgs > li.c-msg--hum')].at(-1); const im = li?.querySelectorAll('.c-imgs img'); const orq = [...document.querySelectorAll('#chat-msgs > li.c-msg--orq')].at(-1);
    return { imgs: im ? [...im].map(i => ({ alt: i.alt, w: i.width, h: i.height, ok: i.complete && i.naturalWidth > 0 })) : [], bubble: li?.querySelector('.c-bubble')?.textContent, orq: orq?.textContent.slice(0, 300), posts: window.__posts.slice(-1) }; });
  const t3 = await tray(p);
  R('CA-I7-envio-1', { ok: hist1.imgs.length === 1 && /enviada por você: print\.png/.test(hist1.imgs[0].alt) && hist1.imgs[0].w === 240 && hist1.imgs[0].h === 150 && t3.cards.length === 0 && t3.note === false && JSON.parse(fs.readFileSync('/conv/.sessao/fake_last_stdin.json', 'utf8')).images.length === 1, hist1, t3, stdin: JSON.parse(fs.readFileSync('/conv/.sessao/fake_last_stdin.json', 'utf8')).images });

  // ===== arrastar e soltar + botão
  const CID = await cid(p);
  const de = await drag(p, 'dragenter', [F('print.png')]);
  const dtext = await p.evaluate(() => { const d = document.getElementById('chat-drop'); d.hidden = true; return 1; });
  const deText = await drag(p, 'dragenter', [], '#chat-msgs', 'texto arrastado');
  await drag(p, 'dragenter', [F('print.png')]); await shot(p, '1440-claro-soltar');
  u0 = uploads.length;
  const dr = await drag(p, 'drop', [F('print.png'), F('tela.webp')]);
  await waitReady(p, 2);
  const url0 = await p.url();
  const outside = await p.evaluate(() => { document.getElementById('chat-drop').hidden = true; const dt = new DataTransfer(); dt.items.add(__mkFile('AAAA', 'x.png', 'image/png')); const ev = new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }); document.getElementById('main').dispatchEvent(ev); const ov = new DragEvent('dragover', { dataTransfer: dt, bubbles: true, cancelable: true }); document.getElementById('main').dispatchEvent(ov); return { drop: ev.defaultPrevented, over: ov.defaultPrevented }; });
  R('CA-I3-arrastar', { ok: de.prevented && de.overlay && /Solte para anexar — PNG, JPEG ou WEBP, até 5 MB/.test(de.overlayText) && !deText.overlay && !dr.overlay && uploads.length - u0 === 2 && outside.drop && outside.over && (await p.url()) === url0, de, deText, outside });
  const btnInfo = await p.evaluate(() => { const bt = document.getElementById('chat-attach'), r = bt.getBoundingClientRect(), f = document.getElementById('chat-file'); return { label: bt.getAttribute('aria-label'), title: bt.title, accept: f.accept, multiple: f.multiple, w: r.width, h: r.height }; });
  const [fc] = await Promise.all([p.waitForFileChooser(), p.click('#chat-attach')]); await fc.accept(['/fx/foto.jpg']);
  await waitReady(p, 3);
  R('CA-I4-botao', { ok: btnInfo.label === 'Anexar imagem' && btnInfo.accept === 'image/png,image/jpeg,image/webp' && btnInfo.multiple && (await tray(p)).cards.every(c => /ready/.test(c.cls)), btnInfo });
  await p.type('#chat-text', 'Três imagens IMGECO'); await p.click('#chat-send');
  await p.waitForFunction(() => document.querySelectorAll('#chat-msgs > li.c-msg--hum').length >= 2 && document.getElementById('chat-stop').hidden, { timeout: 20000 }); await sleep(800);
  const hist3 = await p.evaluate(() => { const li = [...document.querySelectorAll('#chat-msgs > li.c-msg--hum')].at(-1); return [...li.querySelectorAll('.c-imgs img')].map(i => ({ alt: i.alt, w: i.width })); });
  R('CA-I7-envio-3', { ok: hist3.length === 3 && hist3.every(h => h.w === 120) && /Imagem 1 de 3 enviada por você: print\.png/.test(hist3[0].alt) && /tela\.webp/.test(hist3[1].alt) && /foto\.jpg/.test(hist3[2].alt), hist3 });
  await shot(p, '1440-claro-historico');

  // ===== 4 de uma vez → 3 + aviso; só imagem sem texto
  await paste(p, [F('print.png', 'a.png'), F('segundo.png', 'b.png'), F('tela.webp', 'c.webp'), F('foto.jpg', 'd.jpg')], '');
  await waitReady(p, 3);
  const t4 = await tray(p), al4 = await p.evaluate(() => window.__alert.slice(-2));
  R('CA-I7-quatro', { ok: t4.cards.length === 3 && t4.msg.includes('No máximo 3 imagens por mensagem — 1 não foi anexada.'), t4, al4 });
  // remove 2, envia só imagem
  await p.click('#chat-tray-list > li:nth-child(3) .c-att-x'); await p.click('#chat-tray-list > li:nth-child(2) .c-att-x'); await sleep(300);
  await p.$eval('#chat-text', e => { e.value = ''; }); await p.click('#chat-send');
  await p.waitForFunction(() => document.querySelectorAll('#chat-msgs > li.c-msg--hum').length >= 3 && document.getElementById('chat-stop').hidden, { timeout: 20000 }); await sleep(800);
  const onlyImg = await p.evaluate(() => { const li = [...document.querySelectorAll('#chat-msgs > li.c-msg--hum')].at(-1); return { imgs: li.querySelectorAll('.c-imgs img').length, bubble: !!li.querySelector('.c-bubble'), post: window.__posts.at(-1) }; });
  R('CA-I7-so-imagem', { ok: onlyImg.imgs === 1 && !onlyImg.bubble && /"text":""/.test(onlyImg.post), onlyImg });

  // ===== recusas no navegador (sem requisição) e no servidor
  u0 = uploads.length;
  const [fc2] = await Promise.all([p.waitForFileChooser(), p.click('#chat-attach')]);
  await fc2.accept(['/fx/doc.pdf', '/fx/anim.gif', '/fx/falso.png', '/fx/grande.png', '/fx/gigante.png', '/fx/foto.heic']); await sleep(1200);
  const t5 = await tray(p), al5 = await p.evaluate(() => window.__alert.at(-1));
  const exp5 = ['doc.pdf: formato não aceito. Envie PNG, JPEG ou WEBP.', 'anim.gif: formato não aceito.', 'falso.png: formato não aceito.', 'grande.png: imagem acima de 5 MB (6,3 MB).', 'gigante.png: imagem acima de 8000 px de largura ou altura.', 'foto.heic: HEIC não é aceito. Exporte como JPEG ou PNG.'];
  R('CA-I8-recusa-navegador', { ok: uploads.length === u0 && t5.cards.length === 0 && exp5.every(e => t5.msg.includes(e)) && exp5.every(e => (al5 || '').includes(e.split(':')[0])), msg: t5.msg, alerta: al5 });
  await shot(p, '1440-claro-erro');
  const [fc3] = await Promise.all([p.waitForFileChooser(), p.click('#chat-attach')]); await fc3.accept(['/fx/truncado.png']);
  await waitReady(p, 1);
  const t6 = await tray(p);
  R('CA-I8-recusa-servidor', { ok: t6.cards.length === 1 && /err/.test(t6.cards[0].cls) && t6.msg.includes('truncado.png: a imagem está corrompida ou incompleta.') && t6.send === true && /Remova ou reenvie/.test(t6.hint), t6 });
  await shot(p, '1440-claro-erro-servidor');
  await p.click('#chat-tray-list > li .c-att-x'); await sleep(300);

  // ===== CA-I5: progresso com rede lenta (throttle de upload)
  const cdp = await p.target().createCDPSession();
  await cdp.send('Network.enable'); await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 50, downloadThroughput: 5e6, uploadThroughput: 250 * 1024 });
  await p.evaluate(() => { window.__prog = []; });
  const [fc4] = await Promise.all([p.waitForFileChooser(), p.click('#chat-attach')]); await fc4.accept(['/fx/quase5mb.png']);
  await sleep(1200); await shot(p, '1440-claro-enviando-lento');
  await waitReady(p, 1, 60000);
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  const prog = await p.evaluate(() => window.__prog);
  const vals = [...new Set(prog.map(x => x.now).filter(v => v != null).map(Number))];
  const procAfter = prog.findIndex(x => /proc/.test(x.cls)) > prog.findIndex(x => x.now === '100' || Number(x.now) > 90);
  R('CA-I5-progresso', { ok: vals.length >= 3 && prog.some(x => /Processando imagem 1/.test(x.label || '')) && procAfter, valores: vals.slice(0, 12), n: vals.length });
  await p.click('#chat-tray-list > li .c-att-x'); await sleep(300);

  // ===== reduced motion
  const pr = await page(1440, { hash: `#/painel?conversa=${CID}`, reduce: true });
  await pr.evaluate(() => { window.__prog = []; });
  await paste(pr, [F('print.png', 'rm.png')], '');
  await pr.waitForSelector('#chat-tray-list > li', { timeout: 3000 });
  const rm = await pr.evaluate(() => { const li = document.querySelector('#chat-tray-list > li'); const ring = li.querySelector('.c-att-ring'), t = li.querySelector('.c-att-rm'); const cs = getComputedStyle(ring);
    return { ring: cs.display, anim: cs.animationName, rmVis: getComputedStyle(t).display, txt: t.textContent }; });
  await waitReady(pr, 1);
  const rmProg = await pr.evaluate(() => window.__prog.map(x => x.rm).filter(Boolean));
  R('CA-I5-reduced-motion', { ok: rm.ring === 'none' && rm.rmVis === 'block' && rmProg.some(t => /^Enviando \d+%$|^Processando…$/.test(t)), rm, textos: [...new Set(rmProg)] });
  await pr.click('#chat-tray-list > li .c-att-x'); await sleep(200); await pr.close();

  // ===== F5 → histórico, visualizador, teclado
  await p.reload({ waitUntil: 'domcontentloaded' }); await p.waitForFunction(() => typeof state !== 'undefined' && state, { timeout: 60000 }); await sleep(1500);
  const h5 = await p.evaluate(() => [...document.querySelectorAll('#chat-msgs > li.c-msg--hum')].map(li => [...li.querySelectorAll('.c-imgs img')].map(i => ({ alt: i.alt, ok: i.complete && i.naturalWidth > 0 }))));
  R('CA-I12-historico-f5', { ok: h5.length === 3 && h5[0].length === 1 && h5[1].length === 3 && h5[2].length === 1 && /Imagem 1 de 1 enviada por você: print\.png/.test(h5[0][0].alt), h5 });
  const thumb = '#chat-msgs > li.c-msg--hum:nth-of-type(n) .c-imgs.multi .c-img';
  await p.evaluate(() => { document.querySelectorAll('#chat-msgs .c-imgs.multi .c-img')[0].scrollIntoView(); });
  await p.focus('#chat-msgs .c-imgs.multi .c-img'); await p.keyboard.press('Enter'); await sleep(400);
  const v1 = await p.evaluate(() => ({ open: document.getElementById('chat-viewer').open, focus: document.activeElement.id, h: document.getElementById('chat-viewer-h').textContent, sub: document.getElementById('chat-viewer-sub').textContent, href: document.getElementById('chat-viewer-open').getAttribute('href'), target: document.getElementById('chat-viewer-open').target, rel: document.getElementById('chat-viewer-open').rel }));
  await shot(p, '1440-claro-visualizador');
  await p.keyboard.press('ArrowRight'); await sleep(200);
  const v2 = await p.evaluate(() => document.getElementById('chat-viewer-h').textContent);
  await p.keyboard.press('ArrowLeft'); await sleep(200);
  await p.keyboard.press('Escape'); await sleep(400);
  const v3 = await p.evaluate(() => ({ open: document.getElementById('chat-viewer').open, panel: !document.getElementById('chat').hidden, focus: document.activeElement.dataset?.chatImg || document.activeElement.id }));
  R('CA-I12-visualizador', { ok: v1.open && v1.focus === 'chat-viewer-close' && v1.h === 'print.png' && /1440×900 px · 1 de 3/.test(v1.sub) && /\/anexos\/[0-9a-f]{64}$/.test(v1.href) && v1.target === '_blank' && /noopener/.test(v1.rel) && v2 === 'tela.webp' && !v3.open && v3.panel && /:0$/.test(v3.focus), v1, v2, v3 });


  // ===== CA-I21: só teclado — Tab/Shift+Tab passando pelo clipe e pelo remover; anexar, remover e enviar por teclado
  {
    await paste(p, [F('segundo.png', 'tecl.png')], ''); await waitReady(p, 1); await sleep(1100);
    const desc = () => p.evaluate(() => { const e = document.activeElement; if (!e || e === document.body) return 'body'; return e.id ? '#' + e.id : (e.getAttribute('aria-label') || e.className || e.tagName); });
    await p.focus('#chat-text');
    const fwd = ['#chat-text']; for (let i = 0; i < 3; i++) { await p.keyboard.press('Tab'); fwd.push(await desc()); }
    await p.focus('#chat-send');
    const back = ['#chat-send']; for (let i = 0; i < 5; i++) { await p.keyboard.down('Shift'); await p.keyboard.press('Tab'); await p.keyboard.up('Shift'); back.push(await desc()); }
    await p.focus('#chat-attach');
    const live0 = (await p.evaluate(() => window.__live)).filter(t => t === 'Imagem anexada').length;
    const fcK = await Promise.all([p.waitForFileChooser({ timeout: 3000 }), p.keyboard.press('Enter')]).then(([fc]) => fc).catch(() => null);
    if (fcK) { await fcK.accept(['/fx/foto.jpg']); await waitReady(p, 2); await sleep(300); }
    const live1 = (await p.evaluate(() => window.__live)).filter(t => t === 'Imagem anexada').length;
    const nBefore = (await tray(p)).cards.length;
    await p.focus('#chat-tray-list > li:last-child .c-att-x'); await p.keyboard.press('Enter'); await sleep(500);
    const nAfter = (await tray(p)).cards.length, focoAposRemover = await desc();
    const hum0 = await p.evaluate(() => document.querySelectorAll('#chat-msgs > li.c-msg--hum').length);
    await p.focus('#chat-text'); await p.keyboard.type('teclado IMGECO'); await p.keyboard.press('Enter');
    await p.waitForFunction(n => document.querySelectorAll('#chat-msgs > li.c-msg--hum').length > n && document.getElementById('chat-stop').hidden, { timeout: 20000 }, hum0).catch(() => null);
    await sleep(600);
    const enviado = await p.evaluate(() => { const li = [...document.querySelectorAll('#chat-msgs > li.c-msg--hum')].at(-1); return { imgs: li.querySelectorAll('.c-imgs img').length, txt: li.querySelector('.c-bubble')?.textContent.trim() }; });
    const iA = fwd.indexOf('#chat-attach'), iS = fwd.indexOf('#chat-send');
    R('CA-I21-teclado', { ok: iA > 0 && iS > iA && back.includes('#chat-attach') && back.some(x => /^Remover imagem 1: tecl\.png$/.test(x)) && !!fcK && live1 - live0 === 1 && nAfter === nBefore - 1 && enviado.imgs === 1 && /teclado IMGECO/.test(enviado.txt || ''),
      ordemTab: fwd, ordemShiftTab: back, anexarPorEnter: !!fcK, anuncioImagemAnexada: live1 - live0, removerPorEnter: [nBefore, nAfter], focoAposRemover, enviado });
  }

  // ===== arquivo apagado → "Imagem indisponível"
  const aid = await p.evaluate(() => { const li = [...document.querySelectorAll('#chat-msgs > li.c-msg--hum')].at(-1); return li.querySelector('.c-img').dataset.url.split('/').pop(); });
  const files = fs.readdirSync(`/conv/${CID}/anexos`).filter(f => f.startsWith(aid)); files.forEach(f => fs.renameSync(`/conv/${CID}/anexos/${f}`, `/conv/${CID}/anexos/${f}.bak`));
  const errs0 = out.errors.length;
  await p.reload({ waitUntil: 'domcontentloaded' }); await p.waitForFunction(() => typeof state !== 'undefined' && state, { timeout: 60000 }); await sleep(1500);
  const na = await p.evaluate(() => { const li = [...document.querySelectorAll('#chat-msgs > li.c-msg--hum')].at(-1); return { na: li.querySelector('.c-img-na')?.textContent.trim(), label: li.querySelector('.c-img-na')?.getAttribute('aria-label') }; });
  files.forEach(f => fs.renameSync(`/conv/${CID}/anexos/${f}.bak`, `/conv/${CID}/anexos/${f}`));
  R('CA-I12-indisponivel', { ok: /Imagem indisponível/.test(na.na || '') && out.errors.length === errs0, na });
  await p.close();

  // ===== rede caiu no upload → "Tentar de novo" no cartão
  {
    const pn = await page(1440, { hash: `#/painel?conversa=${CID}` });
    await pn.setRequestInterception(true); let block = true;
    pn.on('request', r => { if (block && r.method() === 'POST' && /\/anexos$/.test(r.url())) r.abort('failed'); else r.continue(); });
    await paste(pn, [F('segundo.png', 'rede.png')], ''); await waitReady(pn, 1);
    const e1 = await tray(pn), rt = await pn.$eval('.c-att-retry', b => ({ t: b.textContent, l: b.getAttribute('aria-label') })).catch(() => null);
    block = false; await pn.click('.c-att-retry'); await waitReady(pn, 1); await sleep(200);
    const e2 = await tray(pn);
    R('CA-I-retry-rede', { ok: /err/.test(e1.cards[0].cls) && e1.msg.includes('rede.png: falha ao enviar. Tente de novo.') && !!rt && /ready/.test(e2.cards[0].cls) && !e2.msg, e1: e1.msg, rt, e2: e2.cards });
    await pn.click('.c-att-x'); await sleep(200); await pn.close();
  }
  // ===== 390 / escuro / capturas / alvos
  for (const [w, theme, nome] of [[1440, 'dark', 'escuro'], [390, 'light', 'claro'], [390, 'dark', 'escuro']]) {
    const q = await page(w, { theme, hash: `#/painel?conversa=${CID}` }); await sleep(1200);
    await q.evaluate(() => { const l = document.getElementById('chat-msgs'); l.scrollTop = l.scrollHeight; });
    await shot(q, `${w}-${nome}-historico`);
    await paste(q, [F('print.png', 'a.png'), F('tela.webp', 'b.webp'), F('foto.jpg', 'c.jpg')], '');
    await sleep(150); await shot(q, `${w}-${nome}-enviando`);
    await waitReady(q, 3); await sleep(1100); await shot(q, `${w}-${nome}-bandeja`);
    const [fx] = await Promise.all([q.waitForFileChooser(), q.click('#chat-attach')]); await fx.accept(['/fx/doc.pdf']); await sleep(600);
    await shot(q, `${w}-${nome}-erro`);
    const m = await q.evaluate(() => { const sz = el => { const r = el.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; };
      return { hscroll: document.documentElement.scrollWidth > innerWidth, trayW: document.getElementById('chat-tray-list').scrollWidth <= document.getElementById('chat-tray-list').clientWidth + 1,
        attach: sz(document.getElementById('chat-attach')), x: [...document.querySelectorAll('.c-att-x')].map(sz), send: sz(document.getElementById('chat-send')) }; });
    R(`CA-I21-${w}-${nome}`, { ok: !m.hscroll && m.trayW && m.attach[0] >= 44 && m.attach[1] >= 44 && (w > 500 || m.x.every(([a, b2]) => a >= 44 && b2 >= 44)), m });
    for (let i = 0; i < 3; i++) { await q.click('#chat-tray-list > li .c-att-x'); await sleep(150); }
    await q.close();
  }
  out.uploads = uploads.length; out.removes = removes.length;
  await b.close();
  const fails = Object.entries(out.results).filter(([, v]) => !v.ok).map(([k]) => k);
  out.fails = fails;
  fs.writeFileSync('/shots/d21-imagens-result.json', JSON.stringify(out, null, 1));
  console.log(JSON.stringify(out, null, 1));
  process.exit(fails.length || out.errors.length ? 1 : 0);
})().catch(e => { console.error(e); console.log(JSON.stringify(out, null, 1)); process.exit(2); });
