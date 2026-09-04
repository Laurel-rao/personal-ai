const reviewState = { items: [], order: [], index: 0, mode: 'sequential', scope: 'pending', playing: false, timer: null, touchStart: null };
const byId = (id) => document.getElementById(id);

function reviewEscape(value) { return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char])); }
function currentItem() { return reviewState.items.find((item) => item.id === reviewState.order[reviewState.index]); }
function shuffle(items) { const copy = [...items]; for (let i = copy.length - 1; i > 0; i -= 1) { const j = Math.floor(Math.random() * (i + 1)); [copy[i], copy[j]] = [copy[j], copy[i]]; } return copy; }

function setOrder(keepId) {
  const visibleItems = reviewState.scope === 'pending' ? reviewState.items.filter((item) => !item.label) : reviewState.items;
  const ids = visibleItems.map((item) => item.id);
  reviewState.order = reviewState.mode === 'random' ? shuffle(ids) : ids;
  const foundIndex = reviewState.order.indexOf(keepId);
  reviewState.index = foundIndex >= 0 ? foundIndex : 0;
}

function renderReview() {
  const item = currentItem();
  const summary = reviewState.summary || { total: 0, liked: 0, unliked: 0, unlabeled: 0, queue_count: 0 };
  byId('reviewQueueCount').textContent = `生成队列 ${summary.queue_count || 0}`;
  byId('reviewSummary').textContent = `剩余标注 ${summary.unlabeled} / ${summary.total} · Like ${summary.liked} · Unlike ${summary.unliked}`;
  if (!item) {
    byId('reviewImageWrap').innerHTML = '<div class="review-empty">还没有可标注的图片<br><small>完成生成后会自动显示在这里</small></div>';
    byId('reviewPrompt').textContent = '等待图片进入图库'; byId('reviewPosition').textContent = '0 / 0'; return;
  }
  byId('reviewImageWrap').innerHTML = `<img class="review-image" src="${item.url}" alt="待标注生成图片">`;
  byId('reviewSource').textContent = `${item.source} · ${item.label ? item.label.toUpperCase() : 'UNLABELED'}`;
  byId('reviewPrompt').textContent = item.prompt || '未附带提示词';
  byId('reviewPosition').textContent = `${reviewState.index + 1} / ${reviewState.order.length}`;
}

async function loadReview(keepId = currentItem()?.id) {
  const result = await fetch('api/review/items').then((response) => response.json());
  reviewState.items = result.items || []; reviewState.summary = result.summary;
  setOrder(keepId); renderReview();
}

function move(delta) { if (!reviewState.order.length) return; reviewState.index = Math.min(reviewState.order.length - 1, Math.max(0, reviewState.index + delta)); renderReview(); }
function browseHistory(delta) { if (reviewState.scope !== 'all') { reviewState.scope = 'all'; document.querySelectorAll('.scope-button').forEach((button) => button.classList.toggle('active', button.dataset.scope === 'all')); setOrder(currentItem()?.id); } move(delta); }

async function label(value) {
  const item = currentItem(); if (!item) return;
  await fetch('api/review/label', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image_id: item.id, value }) });
  flashIndicator(value); move(1); await loadReview(currentItem()?.id);
}

function flashIndicator(value) { const element = byId(value === 'like' ? 'likeIndicator' : 'unlikeIndicator'); element.classList.add('show'); setTimeout(() => element.classList.remove('show'), 220); }
function togglePlay() { reviewState.playing = !reviewState.playing; byId('playButton').textContent = reviewState.playing ? '暂停自动浏览' : '开始自动浏览'; if (reviewState.timer) clearInterval(reviewState.timer); reviewState.timer = reviewState.playing ? setInterval(() => move(1), 2600) : null; }

byId('likeButton').addEventListener('click', () => label('like'));
byId('unlikeButton').addEventListener('click', () => label('unlike'));
byId('previousButton').addEventListener('click', () => browseHistory(-1));
byId('nextButton').addEventListener('click', () => browseHistory(1));
byId('playButton').addEventListener('click', togglePlay);
document.querySelectorAll('.mode-button').forEach((button) => button.addEventListener('click', () => { reviewState.mode = button.dataset.mode; document.querySelectorAll('.mode-button').forEach((item) => item.classList.toggle('active', item === button)); setOrder(currentItem()?.id); renderReview(); }));
document.querySelectorAll('.scope-button').forEach((button) => button.addEventListener('click', () => { reviewState.scope = button.dataset.scope; document.querySelectorAll('.scope-button').forEach((item) => item.classList.toggle('active', item === button)); setOrder(currentItem()?.id); renderReview(); }));
function isEditableTarget(target) {
  return target instanceof Element && Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

function handleReviewKeydown(event) {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || event.repeat || isEditableTarget(event.target)) return;
  const actions = {
    ArrowLeft: () => label('unlike'),
    ArrowRight: () => label('like'),
    ArrowUp: () => browseHistory(-1),
    ArrowDown: () => browseHistory(1),
    Space: togglePlay,
  };
  const action = actions[event.key] || actions[event.code];
  if (!action) return;
  event.preventDefault();
  action();
}

window.addEventListener('keydown', handleReviewKeydown, { capture: true });
byId('reviewStage').addEventListener('touchstart', (event) => { const touch = event.changedTouches[0]; reviewState.touchStart = { x: touch.clientX, y: touch.clientY }; }, { passive: true });
byId('reviewStage').addEventListener('touchend', (event) => { if (!reviewState.touchStart) return; const touch = event.changedTouches[0]; const dx = touch.clientX - reviewState.touchStart.x; const dy = touch.clientY - reviewState.touchStart.y; reviewState.touchStart = null; if (Math.max(Math.abs(dx), Math.abs(dy)) < 48) return; if (Math.abs(dx) > Math.abs(dy)) label(dx > 0 ? 'like' : 'unlike'); else browseHistory(dy < 0 ? 1 : -1); }, { passive: true });
loadReview(); setInterval(() => loadReview(currentItem()?.id), 5000);
