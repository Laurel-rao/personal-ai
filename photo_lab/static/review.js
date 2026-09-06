const reviewState = { items: [], order: [], index: 0, mode: 'sequential', scope: 'pending', categories: new Set(['sexy', 'closeup']), retained: new Set(), playing: false, timer: null, touchStart: null };
const byId = (id) => document.getElementById(id);

function reviewEscape(value) { return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char])); }
function currentItem() { return reviewState.items.find((item) => item.id === reviewState.order[reviewState.index]); }
function shuffle(items) { const copy = [...items]; for (let i = copy.length - 1; i > 0; i -= 1) { const j = Math.floor(Math.random() * (i + 1)); [copy[i], copy[j]] = [copy[j], copy[i]]; } return copy; }
function categoryItems() { return reviewState.items.filter((item) => reviewState.categories.has(item.category || 'sexy')); }
function visibleItems() {
  const items = categoryItems();
  return reviewState.scope === 'pending' ? items.filter((item) => !item.label || reviewState.retained.has(item.id)) : items;
}

function setOrder(keepId) {
  const ids = visibleItems().map((item) => item.id);
  reviewState.order = reviewState.mode === 'random' ? shuffle(ids) : ids;
  const foundIndex = reviewState.order.indexOf(keepId);
  reviewState.index = foundIndex >= 0 ? foundIndex : 0;
}

function renderReview() {
  const item = currentItem();
  const filtered = categoryItems();
  const summary = { total: filtered.length, liked: filtered.filter((entry) => entry.label === 'like').length, unliked: filtered.filter((entry) => entry.label === 'unlike').length, unlabeled: filtered.filter((entry) => !entry.label).length, queue_count: reviewState.summary?.queue_count || 0 };
  byId('reviewQueueCount').textContent = `生成队列 ${summary.queue_count || 0}`;
  byId('reviewSummary').textContent = `剩余标注 ${summary.unlabeled} / ${summary.total} · Like ${summary.liked} · Unlike ${summary.unliked}`;
  if (!item) {
    byId('reviewImageWrap').innerHTML = '<div class="review-empty">还没有可标注的图片<br><small>完成生成后会自动显示在这里</small></div>';
    byId('reviewPrompt').textContent = '等待图片进入图库'; byId('reviewPosition').textContent = '0 / 0'; byId('reviewImageNumber').textContent = '编号'; byId('reviewCopyPrompt').disabled = true; byId('reviewDownloadImage').hidden = true; return;
  }
  byId('reviewImageWrap').innerHTML = `<img class="review-image" src="${item.url}" alt="待标注生成图片">`;
  const categoryLabel = item.category === 'closeup' ? '女生特写' : '性感女性';
  byId('reviewSource').textContent = `${categoryLabel} · ${item.source} · ${item.label ? item.label.toUpperCase() : 'UNLABELED'}`;
  byId('reviewImageNumber').textContent = `编号 ${item.filename || item.id}`;
  byId('reviewPrompt').textContent = item.prompt || '未附带提示词';
  byId('reviewCopyPrompt').disabled = !item.prompt;
  byId('reviewCopyPrompt').classList.remove('copied');
  byId('reviewCopyPrompt').querySelector('span').textContent = '复制提示词';
  byId('reviewDownloadImage').href = item.url;
  byId('reviewDownloadImage').download = item.filename || 'image.png';
  byId('reviewDownloadImage').hidden = false;
  byId('reviewPosition').textContent = `${reviewState.index + 1} / ${reviewState.order.length}`;
}

async function loadReview(keepId = currentItem()?.id) {
  const result = await fetch('api/review/items').then((response) => response.json());
  reviewState.items = result.items || []; reviewState.summary = result.summary;
  setOrder(keepId); renderReview();
}

function renderCategoryFilter() {
  const all = reviewState.categories.size === 2;
  document.querySelectorAll('[data-category-filter]').forEach((input) => { input.checked = reviewState.categories.has(input.dataset.categoryFilter); });
  byId('categoryAll').classList.toggle('active', all);
  byId('categoryAll').setAttribute('aria-pressed', String(all));
  document.querySelector('.category-filter').classList.toggle('is-empty', reviewState.categories.size === 0);
}

function move(delta) { if (!reviewState.order.length) return; reviewState.index = Math.min(reviewState.order.length - 1, Math.max(0, reviewState.index + delta)); renderReview(); }
function browseHistory(delta) { move(delta); }

async function label(value) {
  const item = currentItem(); if (!item) return;
  await fetch('api/review/label', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image_id: item.id, value }) });
  if (reviewState.scope === 'pending') reviewState.retained.add(item.id);
  flashIndicator(value); move(1); await loadReview(currentItem()?.id);
}

function flashIndicator(value) { const element = byId(value === 'like' ? 'likeIndicator' : 'unlikeIndicator'); element.classList.add('show'); setTimeout(() => element.classList.remove('show'), 220); }
function togglePlay() { reviewState.playing = !reviewState.playing; byId('playButton').textContent = reviewState.playing ? '暂停自动浏览' : '开始自动浏览'; if (reviewState.timer) clearInterval(reviewState.timer); reviewState.timer = reviewState.playing ? setInterval(() => move(1), 2600) : null; }
async function copyReviewPrompt() {
  const item = currentItem(); if (!item?.prompt) return;
  const button = byId('reviewCopyPrompt');
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(item.prompt);
    else {
      const textarea = document.createElement('textarea'); textarea.value = item.prompt; textarea.style.position = 'fixed'; textarea.style.opacity = '0';
      document.body.appendChild(textarea); textarea.select(); document.execCommand('copy'); textarea.remove();
    }
    button.classList.add('copied'); button.querySelector('span').textContent = '已复制';
    setTimeout(() => { button.classList.remove('copied'); button.querySelector('span').textContent = '复制提示词'; }, 1600);
  } catch (error) { button.querySelector('span').textContent = '复制失败'; setTimeout(() => { button.querySelector('span').textContent = '复制提示词'; }, 1600); }
}

byId('likeButton').addEventListener('click', () => label('like'));
byId('unlikeButton').addEventListener('click', () => label('unlike'));
byId('previousButton').addEventListener('click', () => browseHistory(-1));
byId('nextButton').addEventListener('click', () => browseHistory(1));
byId('playButton').addEventListener('click', togglePlay);
byId('reviewCopyPrompt').addEventListener('click', copyReviewPrompt);
document.querySelectorAll('.mode-button').forEach((button) => button.addEventListener('click', () => { reviewState.mode = button.dataset.mode; document.querySelectorAll('.mode-button').forEach((item) => item.classList.toggle('active', item === button)); setOrder(currentItem()?.id); renderReview(); }));
document.querySelectorAll('.scope-button').forEach((button) => button.addEventListener('click', () => { reviewState.scope = button.dataset.scope; document.querySelectorAll('.scope-button').forEach((item) => item.classList.toggle('active', item === button)); setOrder(currentItem()?.id); renderReview(); }));
document.querySelectorAll('[data-category-filter]').forEach((input) => input.addEventListener('change', () => { reviewState.categories = new Set([...document.querySelectorAll('[data-category-filter]:checked')].map((item) => item.dataset.categoryFilter)); renderCategoryFilter(); setOrder(currentItem()?.id); renderReview(); }));
byId('categoryAll').addEventListener('click', () => { reviewState.categories = new Set(['sexy', 'closeup']); renderCategoryFilter(); setOrder(currentItem()?.id); renderReview(); });
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
renderCategoryFilter(); loadReview(); setInterval(() => loadReview(currentItem()?.id), 5000);
