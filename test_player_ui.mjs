// Run: node test_player_ui.mjs (Chrome; override executable with CHROME_BIN).
// Local synthetic fixture only: never loads the user's video library.
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';

const items = Array.from({ length: 18 }, (_, i) => ({
  id: `sample-${i}`, title: i ? `演示视频 ${i} · 长标题布局检查 `.repeat(4) : '演示视频 <安全文本>',
  filename: `sample-${i}.mp4`, extension: 'mp4', size: 123456789,
  modified_at: '2026-10-01T00:00:00Z', url: '/fixture.mp4', metadata: { code: `DEMO-${i}` },
}));
const files = new Set(['video_player.html', 'video_player.css', 'video_player.js', 'ui-framework.css', 'ui-framework.js', 'admin.css', 'workspace-pages.css']);
const server = createServer(async (req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  if (path === '/api/player/videos') {
    res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ items })); return;
  }
  const file = path === '/player' ? 'video_player.html' : path.slice(1);
  if (!files.has(file)) { res.writeHead(404); res.end(); return; }
  let content = await readFile(new URL(file, import.meta.url), 'utf8');
  if (file.endsWith('.html')) {
    const context = { user: { id: 1, name: '演示用户', roles: [] }, menus: [{ key: 'player', title: '本地视频', url: '/player' }], csrf: '' };
    content = content.replace('</head>', `<script id="workspace-context" type="application/json">${JSON.stringify(context)}</script><script src="/ui-framework.js"></script><link rel="stylesheet" href="/admin.css"><link rel="stylesheet" href="/workspace-pages.css"></head>`);
    content = content.replace(/<link[^>]+https:\/\/fonts[^>]+>/g, '');
  }
  res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html');
  res.end(content);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const profile = await mkdtemp(join(tmpdir(), 'player-ui-check-'));
const chrome = spawn(process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless=new', '--disable-gpu', '--disable-extensions', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });
let socket;
try {
  const endpoint = await new Promise((resolve, reject) => {
    let text = '';
    const timer = setTimeout(() => reject(new Error('Chrome startup timed out')), 15000);
    chrome.on('error', error => { clearTimeout(timer); reject(error); });
    chrome.once('exit', code => { clearTimeout(timer); reject(new Error(`Chrome exited ${code}: ${text}`)); });
    chrome.stderr.on('data', chunk => {
      text += chunk;
      const match = text.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
  });
  const base = new URL(endpoint); const targets = await (await fetch(`http://${base.host}/json`)).json();
  socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
  await once(socket, 'open');
  let sequence = 0; const pending = new Map(); const errors = [];
  socket.addEventListener('message', event => {
    const data = JSON.parse(event.data);
    if (data.method === 'Runtime.exceptionThrown') errors.push(data.params.exceptionDetails.text);
    if (pending.has(data.id)) {
      const { resolve, reject, timer } = pending.get(data.id); clearTimeout(timer); pending.delete(data.id);
      if (data.error) reject(new Error(data.error.message)); else resolve(data.result);
    }
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, { resolve, reject, timer }); socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const result = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails)); return result.result.value;
  };
  await call('Runtime.enable'); await call('Page.enable');
  await call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await call('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/player` });
  await evaluate(`new Promise((resolve, reject) => { const start = Date.now(); const check = () => { if (document.querySelectorAll('.playlist-item').length === 18) resolve(); else if(Date.now()-start > 8000) reject(Error('Fixture failed to load')); else requestAnimationFrame(check); }; check(); })`);
  assert.equal(await evaluate(`document.querySelector('.workspace-header h1').textContent`), '本地视频');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.player-topbar')).display`), 'none');
  assert.equal(await evaluate(`document.querySelector('#filmDisclosure').open`), false);
  assert.equal(await evaluate(`document.querySelectorAll('#playButton svg, #muteButton svg').length`), 2);
  assert.equal(await evaluate(`document.querySelector('.playlist-item-title').textContent`), items[0].title);
  for (const [width, height] of [[1440, 900], [1024, 768], [390, 844]]) {
    await call('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 500 });
    await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    const layout = await evaluate(`(() => { const stage = document.querySelector('#videoStage').getBoundingClientRect(); const seek = getComputedStyle(document.querySelector('#seekPlayed')); return { overflow: document.documentElement.scrollWidth > innerWidth, stageWidth: stage.width, track: seek.height, search: getComputedStyle(document.querySelector('#searchInput')).backgroundColor }; })()`);
    assert.equal(layout.overflow, false, `horizontal overflow at ${width}`);
    assert.ok(layout.stageWidth > 250, `stage too narrow at ${width}`);
    assert.equal(layout.track, '2px');
    assert.notEqual(layout.search, 'rgb(255, 255, 255)');
  }
  await evaluate(`document.querySelector('#fileMenu').open = true; document.querySelector('#fileMenu summary').dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true}));`);
  assert.equal(await evaluate(`document.querySelector('#fileMenu').open`), false);
  await evaluate(`const search = document.querySelector('#searchInput'); search.value = 'not-found-xyz'; search.dispatchEvent(new Event('input'));`);
  assert.equal(await evaluate(`document.querySelectorAll('.playlist-item').length`), 0);
  assert.ok(await evaluate(`document.querySelector('.playlist-empty').textContent.includes('没有')`));
  await evaluate(`document.querySelector('#searchInput').value = ''; document.querySelector('#searchInput').dispatchEvent(new Event('input')); document.querySelector('[data-format="mov"]').click();`);
  assert.equal(await evaluate(`document.querySelector('[data-format="mov"]').getAttribute('aria-pressed')`), 'true');
  assert.equal(await evaluate(`document.querySelectorAll('.playlist-item').length`), 0);
  assert.deepEqual(errors, []);
  console.log('PASS: responsive layout, 2px progress, dark search, page identity, SVG controls, safe long titles, collapsed details, Escape menu, filtering.');
} catch (error) {
  console.error(error);
  throw error;
} finally {
  socket?.close();
  if (chrome.exitCode === null && chrome.signalCode === null && chrome.pid) {
    const exited = once(chrome, 'exit'); chrome.kill(); await exited;
  }
  await new Promise(resolve => server.close(resolve));
  // mkdtemp created this exact absolute profile path; delete only that owned directory.
  assert.equal(profile.startsWith(join(tmpdir(), 'player-ui-check-')), true);
  await rm(profile, { recursive: true, force: true });
}
