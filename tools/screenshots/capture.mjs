// README 스크린샷을 다시 찍는다 — 헤드리스 Chrome을 DevTools 프로토콜로 움직인다(Node 22+, 추가 패키지 없음).
//
// 준비: 1) python tools/screenshots/make_history.py exports/demo
//       2) 데모 앱 두 개를 띄운다 (영어 7861, 한국어 7862):
//          LYRICS_HISTORY_DIR=exports/demo/history-en LYRICS_CACHE=exports/demo/cache-en.db GRADIO_SERVER_PORT=7861 python app.py
//          LYRICS_HISTORY_DIR=exports/demo/history-ko LYRICS_CACHE=exports/demo/cache-ko.db GRADIO_SERVER_PORT=7862 python app.py
// 실행: node tools/screenshots/capture.mjs [en|ko ...] [--only=viewer,edit,...] [--out=docs/images]
// 듣기 화면(listen)은 edge-tts로 데모 가사를 Microsoft 음성 서버에 보낸다.

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const args = process.argv.slice(2);
const langs = args.filter(a => !a.startsWith('--'));
const opt = Object.fromEntries(args.filter(a => a.startsWith('--')).map(a => a.slice(2).split('=')));
const OUT = resolve(opt.out || 'docs/images');
const ONLY = opt.only ? new Set(opt.only.split(',')) : null;
const PORTS = { en: 7861, ko: 7862 };
const TEXT = {
  en: { ui: 'English', source: 'Source order (chunks)', both: 'Both', listen: 'Listen to all', all: 'Select all', many: 'Export selected', mp3: 'Make MP3' },
  ko: { ui: '한국어', source: '원문 어순 (끊어읽기)', both: '둘 다', listen: '전체 듣기', all: '모두 고르기', many: '선택한 곡 내보내기', mp3: 'MP3 만들기' },
};
const SONG = '夜明けの駅で君を待ってた';
const CHROME = [
  process.env.CHROME,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].find(p => p && existsSync(p));
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

class Page {
  static async open(port) {
    const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();
    const p = new Page(new WebSocket(t.webSocketDebuggerUrl));
    await new Promise((ok, bad) => { p.ws.onopen = ok; p.ws.onerror = bad; });
    await p.send('Page.enable');
    await p.send('Runtime.enable');
    return p;
  }
  constructor(ws) {
    this.ws = ws; this.id = 0; this.wait = new Map(); this.events = [];
    ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.id && this.wait.has(d.id)) {
        const [ok, bad] = this.wait.get(d.id); this.wait.delete(d.id);
        d.error ? bad(new Error(`${d.error.message}`)) : ok(d.result);
      } else if (d.method) this.events.push(d.method);
    };
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((ok, bad) => this.wait.set(id, [ok, bad]));
  }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(`${expr.slice(0, 80)}: ${r.exceptionDetails.exception?.description}`);
    return r.result.value;
  }
  async until(expr, ms = 20000, what = expr) {
    const end = Date.now() + ms;
    while (Date.now() < end) { if (await this.eval(expr)) return; await sleep(150); }
    throw new Error(`timeout: ${what}`);
  }
  async size(width, height, mobile = false) {
    await this.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 2, mobile });
    await this.send('Emulation.setTouchEmulationEnabled', { enabled: mobile });
    await this.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });
  }
  async go(url) {
    this.events = [];
    await this.send('Page.navigate', { url });
    await this.until('document.readyState === "complete"', 30000, `load ${url}`);
  }
  // CSS 선택자 + 글자로 요소를 찾아 그 가운데를 진짜 마우스로 누른다 (Gradio가 합성 click을 무시하는 곳이 있다)
  async click(sel, text = '', exact = false) {
    // 글자가 맞는 요소 중 가장 안쪽(마지막)을 고른다 — Gradio 표는 칸 안쪽 요소에서 클릭을 받는다
    const find = `[...document.querySelectorAll(${JSON.stringify(sel)})].findLast(e => e.getClientRects().length && ` +
      (exact ? `e.textContent.trim() === ${JSON.stringify(text)})` : `e.textContent.includes(${JSON.stringify(text)}))`);
    await this.until(`!!(${find})`, 20000, `${sel} "${text}"`);
    const r = await this.eval(`(() => { const e = ${find}; e.scrollIntoView({block: 'center'});
      const b = e.getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; })()`);
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: r.x, y: r.y });
    for (const type of ['mousePressed', 'mouseReleased']) {
      await this.send('Input.dispatchMouseEvent', { type, x: r.x, y: r.y, button: 'left', clickCount: 1 });
    }
    await sleep(250);
  }
  async shot(name, clip) {
    const params = { format: 'png', captureBeyondViewport: !!clip };
    if (clip) params.clip = { ...clip, scale: 1 };
    const r = await this.send('Page.captureScreenshot', params);
    writeFileSync(join(OUT, name), Buffer.from(r.data, 'base64'));
    console.log('  saved', name);
  }
  async rect(sel) {
    return this.eval(`(() => { const b = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect();
      return { x: b.x + scrollX, y: b.y + scrollY, width: Math.ceil(b.width), height: Math.ceil(b.height) }; })()`);
  }
}

// 앱을 열고 화면 언어를 고른 뒤 데모 첫 곡을 연다. mode: 'both'면 '둘 다'로
async function openSong(p, lang, both) {
  await p.go(`http://127.0.0.1:${PORTS[lang]}/?__theme=dark`);
  await p.until('!!document.querySelector("#jk-history-table [role=gridcell]")', 30000, 'history table');
  await p.click('#jk-header label', TEXT[lang].ui);
  await sleep(2500);  // 언어를 바꾸면 히스토리 표를 다시 그린다
  await p.click('#jk-history-table [role=gridcell]', SONG);
  await p.until('!!document.querySelector("#jk-viewer .jk-chunk")', 20000, 'viewer');
  // 보기 방식은 브라우저에 기억되므로 매번 고른다
  await p.click('#jk-toolbar label', TEXT[lang][both ? 'both' : 'source'], true);
  await p.until(`${both ? '' : '!'}document.querySelector("#jk-viewer .jk-tr")`, 10000, 'view mode');
  await p.eval('document.activeElement?.blur(); scrollTo(0, 0)');
  await sleep(600);
}

const toToolbar = 'scrollTo(0, document.querySelector("#jk-toolbar").getBoundingClientRect().top + scrollY - 8)';

const SHOTS = {
  async viewer(p, lang) {
    await p.size(960, 675);
    await openSong(p, lang, true);
    await p.shot(`viewer-${lang}.png`);
  },
  async edit(p, lang) {
    await p.size(960, 675);
    await openSong(p, lang, true);
    await p.click('#jk-viewer .jk-no', '3', true);
    await p.until('[...document.querySelectorAll("textarea")].some(t => t.value.includes("言えなかった"))', 15000, 'editor');
    await p.eval('document.activeElement?.blur(); scrollTo(0, 0)');
    await sleep(800);
    await p.shot(`edit-${lang}.png`);
  },
  async listen(p, lang) {
    await p.size(765, 519);
    await openSong(p, lang, false);
    await p.click('#jk-toolbar button', TEXT[lang].listen);
    await p.until('!!document.querySelector("#jk-viewer .jk-play[data-line=\'4\']")?.closest(".jk-line.jk-reading")',
                  90000, 'line 4 being read');
    await p.eval(`document.querySelector('#jk-audio audio').pause(); ${toToolbar}`);
    await sleep(500);
    await p.shot(`listen-${lang}.png`);
  },
  async mobile(p, lang) {
    await p.size(390, 844, true);
    await openSong(p, lang, true);
    await p.eval(toToolbar);
    await sleep(500);
    await p.shot(`mobile-${lang}.png`);
  },
  async panel(p, lang) {
    await p.size(960, 2600);
    await openSong(p, lang, false);
    await p.eval('document.querySelector(".sidebar-parent .toggle-button, button.toggle-button")?.click()');
    await sleep(800);
    await p.click('button', TEXT[lang].mp3);
    await p.until('document.querySelectorAll(".sidebar a[download], .sidebar .file-preview tr").length >= 7', 60000,
                  'mp3 files');
    await p.click('button', TEXT[lang].all, true);
    await sleep(400);
    await p.click('button', TEXT[lang].many, true);
    await p.until('document.querySelectorAll(".sidebar a[download], .sidebar .file-preview tr").length >= 8', 30000,
                  'bundle file');
    await sleep(800);
    const r = await p.eval(`(() => { const a = [...document.querySelectorAll('.sidebar button.label-wrap, .sidebar .label-wrap')]
        .find(e => e.closest('.block') && e.closest('.block').textContent.includes(${JSON.stringify(TEXT[lang].mp3)}));
      const b = (a.closest('.block') || a).getBoundingClientRect();
      return { x: b.x + scrollX, y: b.y + scrollY, width: Math.ceil(b.width), height: Math.ceil(b.height) }; })()`);
    await p.shot(`export-panel-${lang}.png`, r);
  },
  async 'export-mobile'(p, lang) {
    await p.size(390, 844, true);
    await p.go(pathToFileURL(resolve(`exports/demo/files/book-${lang}.html`)).href);
    await sleep(600);
    const h = await p.eval('Math.ceil(document.documentElement.scrollHeight)');
    await p.shot(`export-mobile-${lang}.png`, { x: 0, y: 0, width: 390, height: Math.max(844, h) });
  },
  async 'export-drawer'(p, lang) {
    await p.size(390, 844, true);
    await p.go(pathToFileURL(resolve(`exports/demo/files/book-${lang}.html`)).href);
    await sleep(400);
    await p.click('[data-act="menu"]');
    await sleep(500);
    await p.shot(`export-drawer-${lang}.png`);
  },
  async 'export-image'(p, lang) {
    await p.size(430, 900);
    await p.go(pathToFileURL(resolve(`exports/demo/files/image-${lang}.html`)).href);
    await sleep(500);
    await p.shot(`export-image-${lang}.png`, await p.rect('.jk-img'));
  },
};

async function run(lang) {
  const dir = mkdtempSync(join(tmpdir(), 'jk-shots-'));
  const port = 9300 + Math.floor(Math.random() * 500);
  const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${dir}`,
    '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--autoplay-policy=no-user-gesture-required',
    `--lang=${lang === 'ko' ? 'ko-KR' : 'en-US'}`, 'about:blank'], { stdio: 'ignore' });
  try {
    for (let i = 0; i < 50; i++) {
      try { await fetch(`http://127.0.0.1:${port}/json/version`); break; } catch { await sleep(200); }
    }
    for (const [name, fn] of Object.entries(SHOTS)) {
      if (ONLY && !ONLY.has(name)) continue;
      console.log(`${lang} ${name}`);
      const p = await Page.open(port);
      try { await fn(p, lang); } catch (e) {
        console.error(`  FAILED ${name}: ${e.message}`); process.exitCode = 1;
        await p.shot(`failed-${name}-${lang}.png`).catch(() => {});  // 어디서 멈췄는지 보려고
      }
      finally { p.ws.close(); }
    }
  } finally {
    chrome.kill();
    await sleep(500);
    try { rmSync(dir, { recursive: true, force: true }); } catch {}
  }
}

if (!CHROME) throw new Error('Chrome/Edge not found — set CHROME=<path>');
for (const lang of langs.length ? langs : ['en', 'ko']) await run(lang);
