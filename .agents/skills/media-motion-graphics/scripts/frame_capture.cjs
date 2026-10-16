// Deterministic frame-by-frame capture of a web page or app for video.
//
// Every moving thing is set per frame (cursor, clicks on schedule, eased scrolling, eased app-state tweens),
// then the frame is screenshotted, so motion is smooth at full resolution regardless of how slow the page is.
// Unchanged frames are copied instead of re-shot. Use this instead of a screen recording or the CDP screencast:
// in headless Chrome the screencast returned a cropped 1920x993 viewport at 1x, which stretched when encoded.
//
// usage:  NODE_PATH=<dir containing playwright> node frame_capture.cjs scenario.json OUT_DIR [--encode out.mp4]
//
// scenario.json (all times in seconds of the output clip):
// {
//   "url": "http://localhost:3000/",
//   "viewport": [1920, 1080], "deviceScaleFactor": 2, "fps": 30, "duration": 8,
//   "colorScheme": "dark",
//   "chromeArgs": ["--enable-unsafe-webgpu", "--enable-gpu", "--ignore-gpu-blocklist"],   // WebGPU pages
//   "waitAfterLoad": 3000,
//   "setup": ["window.app.openPanel('history')"],          // JS run once after load (app APIs, state)
//   "css": ".toast { display: none }",                      // injected into the document
//   "shadowCss": "svg text { display: none }",              // injected into every open shadow root
//   "cursor": true, "cursorStart": [960, 540],
//   "events": [
//     { "at": 0.5, "do": "move", "selector": "tr:has-text('Run 12')", "dur": 0.9 },   // or "to": [x, y]
//     { "at": 1.5, "do": "click" },                                                    // at the cursor
//     { "at": 2.4, "do": "scroll", "selector": ".drawer .body", "dy": 430, "dur": 1.2 },
//     { "at": 4.0, "do": "eval", "js": "window.app.highlight('row-12')" }
//   ],
//   "tweens": [                                               // app-state camera moves, applied every frame
//     { "start": 1.0, "end": 6.0, "from": { "x": 40, "y": 3, "scale": 0.12 }, "to": { "x": 26, "y": 6, "scale": 0.035 },
//       "log": ["scale"], "apply": "v => window.app.setViewport(v)" }
//   ],
//   "settleMs": 400                                           // render time allowed after a click or eval
// }
//
// Selectors use Playwright syntax. Moves, scrolls and tweens use cubic in-out easing ("log" fields interpolate
// geometrically, which suits zoom). --encode writes an H.264 30 fps MP4 at the device-pixel size; crop or scale
// it later for other formats (a 9:16 crop of a 2x capture stays sharp).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ease = (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
const CURSOR = `(() => { const c = document.createElement('div'); c.id = '__cap_cursor';
  c.innerHTML = '<svg width="26" height="30" viewBox="0 0 26 30"><path d="M2 2 L2 24 L8 18 L12 28 L16 26 L12 16 L21 16 Z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  Object.assign(c.style, { position: 'fixed', left: '0', top: '0', zIndex: 2147483647, pointerEvents: 'none', filter: 'drop-shadow(0 2px 3px rgba(0,0,0,.5))' });
  document.documentElement.appendChild(c);
  addEventListener('mousemove', (e) => { c.style.transform = 'translate(' + (e.clientX - 2) + 'px,' + (e.clientY - 2) + 'px)'; }, true); })()`;

(async () => {
  const [, , scenarioPath, outDir, flag, encodeOut] = process.argv;
  if (!scenarioPath || !outDir) { console.error('usage: node frame_capture.cjs scenario.json OUT_DIR [--encode out.mp4]'); process.exit(2); }
  const S = JSON.parse(fs.readFileSync(scenarioPath, 'utf8'));
  const [W, H] = S.viewport || [1920, 1080];
  const fps = S.fps || 30, N = Math.round((S.duration || 5) * fps), settle = S.settleMs ?? 400;
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ channel: S.channel || 'chrome', headless: true, args: S.chromeArgs || [] });
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: S.deviceScaleFactor || 2, colorScheme: S.colorScheme || 'light' });
  await page.goto(S.url);
  await page.waitForTimeout(S.waitAfterLoad ?? 2000);
  for (const js of S.setup || []) { await page.evaluate(js); await page.waitForTimeout(settle); }
  if (S.css) await page.addStyleTag({ content: S.css });
  if (S.shadowCss) await page.evaluate((css) => document.querySelectorAll('*').forEach((e) => { if (e.shadowRoot) { const s = document.createElement('style'); s.textContent = css; e.shadowRoot.appendChild(s); } }), S.shadowCss);
  let cur = S.cursorStart || [W / 2, H / 2];
  if (S.cursor) await page.evaluate(CURSOR);
  await page.mouse.move(cur[0], cur[1]);

  const target = async (ev) => {
    if (ev.to) return ev.to;
    const b = await page.locator(ev.selector).first().boundingBox();
    if (!b) throw new Error(`selector not visible: ${ev.selector}`);
    return [b.x + b.width * (ev.offset?.[0] ?? 0.5), b.y + b.height * (ev.offset?.[1] ?? 0.5)];
  };
  const events = (S.events || []).map((e) => ({ ...e, state: null }));
  const tweens = S.tweens || [];
  let last = null;
  for (let f = 0; f < N; f++) {
    const t = f / fps; let changed = f === 0;
    for (const ev of events) {
      if (t < ev.at || ev.state === 'done') continue;
      if (ev.do === 'move') {
        if (!ev.state) ev.state = { from: [...cur], to: await target(ev) };
        const u = Math.min(1, (t - ev.at) / (ev.dur || 0.6)), e = ease(u);
        cur = [ev.state.from[0] + (ev.state.to[0] - ev.state.from[0]) * e, ev.state.from[1] + (ev.state.to[1] - ev.state.from[1]) * e];
        await page.mouse.move(cur[0], cur[1]); changed = true;
        if (u >= 1) ev.state = 'done';
      } else if (ev.do === 'scroll') {
        if (!ev.state) ev.state = { done: 0 };
        const u = Math.min(1, (t - ev.at) / (ev.dur || 1)), want = Math.round(ev.dy * ease(u));
        await page.locator(ev.selector).first().evaluate((el, d) => { el.scrollTop += d; }, want - ev.state.done);
        ev.state.done = want; changed = true;
        if (u >= 1) ev.state = 'done';
      } else if (ev.do === 'click') {
        await page.mouse.click(cur[0], cur[1]); await page.waitForTimeout(settle); ev.state = 'done'; changed = true;
      } else if (ev.do === 'eval') {
        await page.evaluate(ev.js); await page.waitForTimeout(settle); ev.state = 'done'; changed = true;
      }
    }
    for (const tw of tweens) {
      if (t < tw.start || (tw.done && t > tw.end)) continue;
      const u = Math.min(1, (t - tw.start) / (tw.end - tw.start)), e = ease(u), v = {};
      for (const k of Object.keys(tw.from)) {
        const a = tw.from[k], b = tw.to[k];
        v[k] = (tw.log || []).includes(k) ? Math.exp(Math.log(a) + (Math.log(b) - Math.log(a)) * e) : a + (b - a) * e;
      }
      await page.evaluate(({ fn, v }) => { (0, eval)(fn)(v); }, { fn: tw.apply, v });
      changed = true; if (u >= 1) tw.done = true;
    }
    const name = path.join(outDir, `f${String(f).padStart(5, '0')}.jpg`);
    if (changed || last === null || f % 15 === 0) {
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      await page.screenshot({ path: name, type: 'jpeg', quality: 93 }); last = name;
    } else fs.copyFileSync(last, name);
  }
  await browser.close();
  console.log(`frames ${N} -> ${outDir}`);
  if (flag === '--encode' && encodeOut) {
    execFileSync('ffmpeg', ['-nostdin', '-loglevel', 'error', '-y', '-framerate', String(fps), '-i', path.join(outDir, 'f%05d.jpg'),
      '-vf', 'format=yuv420p', '-c:v', 'libx264', '-crf', '14', '-preset', 'slow', '-movflags', '+faststart', encodeOut]);
    console.log('encoded', encodeOut);
  }
})().catch((e) => { console.error(e); process.exit(1); });
