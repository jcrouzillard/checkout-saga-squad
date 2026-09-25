// D20 (41bdb8b49835) — pós-integração D18+D19: convivência no cabeçalho do selo de ambiente/versão (#inst-c),
// do botão da conversa (#chat-btn) e do indicador "ao vivo" (#live-ind) em 1440, 1100, 900, 700, 610 e 390 px,
// e o painel do chat v2 aberto com o selo (claro/escuro). Mesmo servidor/isolamento de d20-conversa-visual.js:
//   docker run --rm --user root --add-host=host.docker.internal:host-gateway -e TZ=America/Sao_Paulo -e PORT=<livre> \
//     -e NODE_PATH=/usr/src/app/node_modules -v "<cópia de tests/ui>:/shots" --entrypoint node \
//     zenika/alpine-chrome:with-puppeteer /shots/d20-cabecalho-selo.js > <scratch>/d20-cabecalho.json
// Saída: JSON {results:{<largura>-<estado>:{ok,...}}}; capturas /shots/d20-cab-*.png; código 1 se algum falhar.
const puppeteer = require('puppeteer');
const net = require('net');
const PORT = Number(process.env.PORT || 7381);
const BASE = `http://127.0.0.1:${PORT}/`;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = { results: {}, errors: [] };
const R = (k, v) => { out.results[k] = v; console.error(`[${k}] ${v.ok ? 'PASS' : 'FAIL'} ${JSON.stringify(v).slice(0, 500)}`); };
const relay = port => new Promise(res => net.createServer(c => {
  const u = net.connect(port, 'host.docker.internal');
  c.pipe(u).pipe(c); u.on('error', () => c.destroy()); c.on('error', () => u.destroy());
}).listen(port, '127.0.0.1', res));

function measure() {
  const box = el => { if (!el) return null; const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    const shown = cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0;
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height), r: Math.round(r.right), b: Math.round(r.bottom), shown }; };
  // O selo mora no cabeçalho (#inst-c) de 610 a ~1000 px, na lateral (#inst-side) em telas largas (D18 CA15) e
  // fixo no rodapé em 390 (D18 CA16): mede o que estiver visível.
  const on = e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
  const seloEl = [document.querySelector('#hdr #inst-c'), document.querySelector('#inst-side')].find(on) || document.querySelector('#hdr #inst-c');
  const els = { selo: seloEl, chat: document.querySelector('#chat-btn'), live: document.querySelector('#live-ind'), bell: document.querySelector('#bell') };
  const b = Object.fromEntries(Object.entries(els).map(([k, e]) => [k, box(e)]));
  const vis = Object.entries(b).filter(([, v]) => v && v.shown);
  const over = [];
  for (let i = 0; i < vis.length; i++) for (let j = i + 1; j < vis.length; j++) {
    const [ka, a] = vis[i], [kb, c] = vis[j];
    const ix = Math.min(a.r, c.r) - Math.max(a.x, c.x), iy = Math.min(a.b, c.b) - Math.max(a.y, c.y);
    if (ix > 0.5 && iy > 0.5) over.push(`${ka}×${kb}`);
  }
  const fora = vis.filter(([, v]) => v.x < 0 || v.r > innerWidth + 0.5).map(([k]) => k);
  const hdr = document.querySelector('#hdr').getBoundingClientRect();
  return { ...b, sobreposicoes: over, foraDaTela: fora, hscroll: document.documentElement.scrollWidth > innerWidth,
    scrollW: document.documentElement.scrollWidth, hdrH: Math.round(hdr.height), liveText: els.live?.textContent.trim(),
    seloText: els.selo?.textContent.trim().replace(/\s+/g, ' '), seloOnde: els.selo?.id === 'inst-side' ? 'lateral' : 'cabecalho' };
}

(async () => {
  await relay(PORT);
  const b = await puppeteer.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'], executablePath: process.env.PUPPETEER_EXECUTABLE_PATH });
  for (const w of [1440, 1100, 900, 700, 610, 390]) {
    for (const theme of ['light', 'dark']) {
      const p = await b.newPage();
      p.on('pageerror', e => out.errors.push(String(e).slice(0, 300)));
      await p.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: theme }]);
      await p.setViewport({ width: w, height: w > 500 ? 900 : 844, deviceScaleFactor: 1 });
      await p.evaluateOnNewDocument(t => { try { localStorage.setItem('sc-theme', t); } catch (e) {} }, theme);
      await p.goto(BASE + '#/painel', { waitUntil: 'domcontentloaded' });
      await p.waitForFunction(() => { const s = document.querySelector('#inst-c'); const l = document.querySelector('#live-ind');
        return s && s.dataset.env && s.dataset.env !== 'carregando' && l && !/Conectando/.test(l.textContent); }, { timeout: 15000, polling: 200 }).catch(() => null);
      await sleep(600);
      const fechado = await p.evaluate(measure);
      const okF = fechado.selo?.shown && fechado.chat?.shown && fechado.live?.shown && !fechado.sobreposicoes.length && !fechado.foraDaTela.length && !fechado.hscroll;
      R(`${w}-${theme}-fechado`, { ok: !!okF, ...fechado });
      if (theme === 'light' || w === 1440 || w === 390) await p.screenshot({ path: `/shots/d20-cab-${w}-${theme}.png` });
      // painel do chat v2 aberto com o selo
      await p.click('#chat-btn'); await sleep(700);
      const aberto = await p.evaluate(() => {
        const chat = document.querySelector('#chat'); const r = chat.getBoundingClientRect(); const cs = getComputedStyle(chat);
        const on = e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
        const selo = [document.querySelector('#hdr #inst-c'), document.querySelector('#inst-side')].find(on); const sr = selo && selo.getBoundingClientRect();
        const cobreSelo = !!(sr && sr.width && Math.min(r.right, sr.right) - Math.max(r.left, sr.left) > 0.5 && Math.min(r.bottom, sr.bottom) - Math.max(r.top, sr.top) > 0.5);
        const topo = document.elementFromPoint(Math.max(1, Math.min(innerWidth - 1, (sr?.left || 0) + 4)), (sr?.top || 0) + (sr?.height || 0) / 2);
        return { seloVisivel: !!selo, seloOnde: selo ? selo.id : null, aberto: !chat.hidden && cs.display !== 'none', painel: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
          cobreSelo, seloClicavel: !!(selo && topo && (selo === topo || selo.contains(topo))), modal: chat.getAttribute('aria-modal'),
          chatBtnExp: document.querySelector('#chat-btn').getAttribute('aria-expanded'), hscroll: document.documentElement.scrollWidth > innerWidth,
          foco: document.activeElement?.id || document.activeElement?.tagName };
      });
      const m2 = await p.evaluate(measure);
      // Painel aberto: só exige que abra, sem rolagem horizontal e sem sobreposição entre os itens do cabeçalho.
      // Se o painel cobre o selo em telas estreitas (sobreposição do diálogo), fica registrado como informação.
      R(`${w}-${theme}-chat-aberto`, { ok: aberto.aberto && !aberto.hscroll && aberto.chatBtnExp === 'true' && !m2.sobreposicoes.length, ...aberto, cabecalho: { sobreposicoes: m2.sobreposicoes, foraDaTela: m2.foraDaTela } });
      if (theme === 'light' || w === 1440 || w === 390) await p.screenshot({ path: `/shots/d20-cab-${w}-${theme}-chat.png` });
      await p.close();
    }
  }
  await b.close();
  out.ok = Object.values(out.results).every(r => r.ok) && !out.errors.length;
  console.log(JSON.stringify(out, null, 2));
  process.exit(out.ok ? 0 : 1);
})().catch(e => { console.log(JSON.stringify({ fatal: String(e && e.stack || e), ...out }, null, 2)); process.exit(2); });
