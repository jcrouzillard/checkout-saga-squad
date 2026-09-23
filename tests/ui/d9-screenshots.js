const puppeteer = require('puppeteer');
const BASE = 'http://host.docker.internal:7093/';
(async () => {
  const b = await puppeteer.launch({ args: ['--no-sandbox'] });
  const out = {};
  for (const w of [1440, 390]) {
    const p = await b.newPage();
    const errs = [];
    p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
    p.on('pageerror', e => errs.push('pageerror: ' + e.message));
    await p.setViewport({ width: w, height: w === 390 ? 844 : 1000 });
    await p.goto(BASE, { waitUntil: 'networkidle2' });
    await new Promise(r => setTimeout(r, 2500));
    const clickView = async v => { await p.evaluate(v => { const el = document.querySelector(`nav a[data-view="${v}"]`) || document.querySelector(`[data-tab="${v}"]`); el && el.click(); }, v); await new Promise(r => setTimeout(r, 800)); };
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
    // rolar ate o card da D9
    await p.evaluate(() => { const b = [...document.querySelectorAll('#main b')].find(x => /modelo exato|modelo usado/i.test(x.textContent)); if (b) b.scrollIntoView({ block: 'start' }); });
    await new Promise(r => setTimeout(r, 300)); await shot('demandas', false);
    const d9 = await p.evaluate(() => { const b = [...document.querySelectorAll('#main b')].find(x => /modelo exato|modelo usado/i.test(x.textContent)); if (!b) return null; const card = b.closest('div[style*="padding:12px 0"]'); const row = card && [...card.querySelectorAll('.mrow')].find(r => r.textContent.startsWith('Modelos:')); return { title: b.textContent, modelos: row ? row.textContent : null }; });
    res.push({ name: 'd9card', d9 });
    await clickView('decisoes'); 
    const dec = await p.evaluate(() => { const rows = [...document.querySelectorAll('#main table tbody tr, #main table tr')].filter(r => r.querySelector('td'));
      let hum = 0, humChip = 0, non = 0, nonChip = 0; for (const r of rows) { const ag = r.children[1]?.textContent || ''; const has = !!r.children[1]?.querySelector('.mchip'); if (/^Humano|^Você|humano/i.test(ag)) { hum++; if (has) humChip++; } else { non++; if (has) nonChip++; } }
      return { rows: rows.length, hum, humChip, non, nonChip, agentsSample: [...new Set(rows.map(r => (r.children[1]?.childNodes[0]?.textContent || '')))].slice(0, 15) }; });
    res.push(Object.assign(await measure('decisoes'), { dec })); await shot('decisoes', false);
    // gaveta do auditor (cartões de execução)
    await clickView('execucoes'); await p.evaluate(() => { const el = document.querySelector('[data-agent="auditor"]'); el && el.click(); }); await new Promise(r => setTimeout(r, 800));
    const drawer = await p.evaluate(() => { const d = document.querySelector('#drawer'); return { hidden: d.hidden, chips: [...new Set([...d.querySelectorAll('.mchip')].map(c => c.textContent))], sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, dsw: d.scrollWidth, dcw: d.clientWidth, undef: /\bundefined\b/.test(d.innerText) }; });
    res.push({ name: 'drawer-auditor', drawer }); await shot('gaveta-auditor', false);
    out[w] = { res, errs };
    await p.close();
  }
  console.log(JSON.stringify(out, null, 1));
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
