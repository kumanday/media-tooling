// Render an HTML file to a PNG at an exact size (thumbnails, end cards, social stills).
// usage: NODE_PATH=<dir with playwright> node html_still.cjs page.html out.png 1080 1920
// Fonts load from paths relative to the HTML file; the script waits for document.fonts.ready.
const { chromium } = require('playwright');
(async () => {
  const [,, html, out, w, h] = process.argv;
  const path = require('path');
  const b = await chromium.launch({ channel: 'chrome', headless: true });
  const p = await b.newPage({ viewport: { width: Number(w), height: Number(h) }, deviceScaleFactor: 1 });
  await p.goto('file://' + path.resolve(html));
  await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(300);
  await p.screenshot({ path: out });
  await b.close();
  console.log('wrote', out);
})();
