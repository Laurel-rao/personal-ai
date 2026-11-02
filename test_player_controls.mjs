// Run: node test_player_controls.mjs. Dependency-free DOM smoke check.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const html = await readFile(new URL('video_player.html', import.meta.url), 'utf8');
const script = await readFile(new URL('video_player.js', import.meta.url), 'utf8');
const elements = new Map();
function element(id) {
  return { id, textContent: '', innerHTML: '', hidden: false, open: false, disabled: false, value: '0', style: {}, dataset: {}, attrs: {}, listeners: {},
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(name, value) { this.attrs[name] = value; }, getAttribute(name) { return this.attrs[name]; },
    removeAttribute() {}, addEventListener(name, callback) { this.listeners[name] = callback; },
    querySelectorAll() { return []; }, querySelector() { return { focus() {} }; },
    contains(target) { return target === this; }, closest() { return null; }, focus() {},
  };
}
for (const [, id] of html.matchAll(/id="([^"]+)"/g)) { assert.ok(!elements.has(id), `duplicate id ${id}`); elements.set(id, element(id)); }
const $ = id => { assert.ok(elements.has(id), `missing DOM id ${id}`); return elements.get(id); };
const menus = ['speedMenu', 'modeMenu', 'shortcutMenu'].map($);
$('videoControls').querySelectorAll = selector => selector === 'details' ? menus : [];
const tabs = ['all', 'mp4', 'mov', 'mkv', 'avi'].map(format => Object.assign(element(format), { dataset: { format } }));
const listeners = {};
const document = { getElementById: $, activeElement: null, hidden: false,
  addEventListener(name, callback) { listeners[name] = callback; },
  querySelectorAll(selector) { return selector === '.format-tab' ? tabs : []; },
};
const video = $('mainVideo'); Object.assign(video, { paused: true, ended: false, duration: NaN, currentTime: 0, error: null, currentSrc: '',
  buffered: { length: 0 }, load() {}, pause() { this.paused = true; }, play() { this.paused = false; return Promise.resolve(); }, });
const items = [{ id: 'demo', title: '<img src=x onerror=alert(1)>', filename: 'demo.mp4', extension: 'mp4', modified_at: '2026-10-01', size: 12345, url: '/demo.mp4', metadata: {} }];
const context = { document, window: { addEventListener() {} }, localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  location: { href: 'http://localhost/player', search: '' }, history: { replaceState() {} }, navigator: {},
  URL, URLSearchParams, setTimeout() { return 1; }, clearTimeout() {},
  fetch: async () => ({ ok: true, json: async () => ({ items }) }), console,
};
vm.runInNewContext(script, context);
await new Promise(resolve => setImmediate(resolve));
assert.match($('playlistList').innerHTML, /&lt;img src=x onerror=alert\(1\)&gt;/);
assert.match($('playlistList').innerHTML, /title="demo.mp4"/);
assert.equal($('videoTitle').textContent, items[0].title);
assert.equal($('filmDisclosure').hidden, false);
assert.equal($('filmDisclosure').open, false);
assert.equal($('playlistPanel').hidden, false);
$('playlistToggle').listeners.click();
assert.equal($('playlistPanel').hidden, true);
assert.equal($('playlistToggle').attrs['aria-expanded'], 'false');
assert.equal($('playlistToggle').textContent, '展开列表');
$('playlistToggle').listeners.click();
assert.equal($('playlistPanel').hidden, false);
assert.equal($('playlistToggle').attrs['aria-expanded'], 'true');
assert.match($('playButton').innerHTML, /<svg/);
assert.match($('muteButton').innerHTML, /<svg/);
assert.equal($('playButton').attrs['aria-label'], '播放');
$('fileMenu').open = true;
listeners.pointerdown({ target: $('videoTitle') });
assert.equal($('fileMenu').open, false);
$('fileMenu').open = true;
listeners.keydown({ key: 'Escape', target: $('fileMenu'), defaultPrevented: false, altKey: false, ctrlKey: false, metaKey: false, preventDefault() {} });
assert.equal($('fileMenu').open, false);
$('searchInput').value = 'no match'; $('searchInput').listeners.input({ target: $('searchInput') });
assert.match($('playlistList').innerHTML, /没有符合条件/);
$('searchInput').value = ''; $('searchInput').listeners.input({ target: $('searchInput') });
tabs[2].listeners.click();
assert.equal(tabs[2].attrs['aria-pressed'], 'true');
assert.equal(tabs[0].attrs['aria-pressed'], 'false');
assert.match($('playlistList').innerHTML, /没有符合条件/);
console.log('PASS: DOM bindings, safe playlist titles, disclosure, SVG states, outside-click/Escape menus and format/search filters.');
