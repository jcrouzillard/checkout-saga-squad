// D9 — selos de modelo por agente. D13 (efe387a35d71): migrado para a navegação por rotas de hash (menu único, sem .tabs):
//   Execuções -> #execucoes (alias da última demanda ativa), Decisões -> #/auditoria/eventos, card da D10 -> página #/demandas/D10,
//   gaveta -> ?agente=auditor. Executar: docker run ... -v "$PWD/tests/ui:/shots" ghcr.io/puppeteer/puppeteer:latest node /shots/d9-screenshots.js
const puppeteer = require('puppeteer');
const BASE = process.env.BASE || 'http://host.docker.internal:7112/';
const ROUTE = { execucoes: '#execucoes', demandas: '#/demandas?f=todas', decisoes: '#/auditoria/eventos', d10: '#/demandas/D10', gaveta: '#/demandas?f=todas&agente=auditor' };
(async () => {
  const b = await puppeteer.launch({ args: ['--no-sandbox'] });
  const out = {};
  for (const w of [1440, 390]) {
    const p = await b.newPage();
    const errs = [];
    p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
    p.on('pageerror', e => errs.push('pageerror: ' + e.message));
    await p.setViewport({ width: w, height: w === 390 ? 844 : 1000 });
    await p.setRequestInterception(true); p.on('request', r => r.method() === 'POST' ? r.abort() : r.continue());   // somente leitura
    await p.goto(BASE, { waitUntil: 'networkidle2' });
    await new Promise(r => setTimeout(r, 2500));
    const clickView = async v => { await p.evaluate(h => { location.hash = h; }, ROUTE[v]); await new Promise(r => setTimeout(r, 900)); };
    const measure = async name => p.evaluate(name => {
      const de = document.documentElement, main = document.querySelector('#main') || document.body;
      const txt = main.innerText;
      const wide = [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect(); return r.right > de.clientWidth + 1 && getComputedStyle(e).position !== 'fixed' && !e.closest('[style*="overflow"],.tbl-wrap,pre,table'); }).slice(0,5).map(e => e.tagName + '.' + e.className + ' r=' + Math.round(e.getBoundingClientRect().right));
      return { name, scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, bodyScroll: document.body.scrollWidth,
        chips: document.querySelectorAll('#main .mchip').length, chipsNone: document.querySelectorAll('#main .mchip.none').length,
        chipSamples: [...new Set([...document.querySelectorAll('#main .mchip')].map(c => c.textContent + ' |' + c.title))].slice(0, 8),
        modelosRows: [...document.querySelectorAll('#main .mrow')].filter(r => r.textContent.startsWith('Modelos:')).slice(0,4).map(r => r.textContent.slice(0, 400)),
        undefinedLit: /\bundefined\b/.test(txt), nullLit: /(^|\s)null(\s|$)/.test(txt), NaN: /\bNaN\b/.test(txt), wide };
    }, name);
    const shot = async (name, full) => p.screenshot({ path: `/shots/d9-${name}-${w}.png`, fullPage: !!full });
    const res = [];
    await clickView('execucoes'); res.push(await measure('execucoes')); await shot('execucoes', true);
    await clickView('demandas'); res.push(await measure('demandas'));
    await shot('demandas', false);
    // D13: o antigo card da demanda "Modelo usado na demanda" (D10) virou a página da demanda
    await clickView('d10');
    const d9 = await p.evaluate(() => { const h = document.querySelector('#main h1'); const row = [...document.querySelectorAll('#main .mrow')].find(r => r.textContent.startsWith('Modelos:')); return h ? { title: h.textContent, modelos: row ? row.textContent : null } : null; });
    res.push({ name: 'd9card', d9 });
    await clickView('decisoes'); 
    const dec = await p.evaluate(() => { const rows = [...document.querySelectorAll('#main table tbody tr, #main table tr')].filter(r => r.querySelector('td'));
      let hum = 0, humChip = 0, non = 0, nonChip = 0; for (const r of rows) { const ag = r.children[1]?.textContent || ''; const has = !!r.children[1]?.querySelector('.mchip'); if (/^Humano|^Você|humano/i.test(ag)) { hum++; if (has) humChip++; } else { non++; if (has) nonChip++; } }
      return { rows: rows.length, hum, humChip, non, nonChip, agentsSample: [...new Set(rows.map(r => (r.children[1]?.childNodes[0]?.textContent || '')))].slice(0, 15) }; });
    res.push(Object.assign(await measure('decisoes'), { dec })); await shot('decisoes', false);
    // gaveta do auditor (cartões de execução)
    await clickView('gaveta'); await new Promise(r => setTimeout(r, 800));
    const drawer = await p.evaluate(() => { const d = document.querySelector('#drawer'); return { hidden: d.hidden, chips: [...new Set([...d.querySelectorAll('.mchip')].map(c => c.textContent))], sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, dsw: d.scrollWidth, dcw: d.clientWidth, undef: /\bundefined\b/.test(d.innerText) }; });
    res.push({ name: 'drawer-auditor', drawer }); await shot('gaveta-auditor', false);
    out[w] = { res, errs };
    await p.close();
  }
  console.log(JSON.stringify(out, null, 1));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
