const $ = (id) => document.getElementById(id);
const state = { items: [], history: { items: [], page: 1, total_pages: 1, total: 0 }, historyPage: 1, historyVisible: false, generationMode: 'single', queueExpanded: false };

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
}

async function copyText(text) {
  const value = String(text || '').trim();
  if (!value) throw new Error('没有可复制的提示词');
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch (_) {
      // Embedded pages can be denied clipboard permission, so use the browser fallback below.
    }
  }
  const helper = document.createElement('textarea');
  helper.value = value;
  helper.setAttribute('readonly', '');
  helper.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none';
  document.body.append(helper);
  helper.select();
  const copied = document.execCommand('copy');
  helper.remove();
  if (!copied) throw new Error('浏览器未允许访问剪贴板');
}

function statusLabel(status) {
  return ({ queued: 'QUEUED', running: 'RUNNING', success: 'DONE', error: 'ERROR' }[status] || status).toUpperCase();
}

function taskIdFromImage(image) {
  const match = String(image?.url || '').match(/\/api\/tasks\/([^/]+)\/image(?:\?|$)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function renderActive() {
  const active = state.items.filter((item) => ['queued', 'running'].includes(item.status));
  $('queueCount').textContent = `生成队列 ${active.length}`;
  if (!active.length) {
    $('activeTasks').className = 'task-list empty-state';
    $('activeTasks').innerHTML = '<div class="empty-icon">◌</div><strong>还没有进行中的任务</strong><span>提交一条提示词，进度会显示在这里</span>';
    return;
  }
  $('activeTasks').className = 'task-list';
  const visible = state.queueExpanded ? active : active.slice(0, 5);
  const hiddenCount = active.length - visible.length;
  const queueToggle = active.length > 5 ? `<button type="button" class="queue-toggle" data-queue-toggle="${state.queueExpanded ? 'collapse' : 'expand'}">${state.queueExpanded ? '收起队列' : `展开其余 ${hiddenCount} 条`}</button>` : '';
  $('activeTasks').innerHTML = visible.map((item) => `<div class="task-card"><div class="task-top"><div class="task-name">${escapeHtml(item.prompt)}</div><span class="status">${statusLabel(item.status)}</span></div><div class="progress-track"><div class="progress-bar" style="width:${item.progress || 0}%"></div></div><div class="task-meta"><span>${escapeHtml(item.message || '等待中')}</span><span>${item.progress || 0}% <button class="cancel-button" data-task-id="${item.id}">取消</button></span></div></div>`).join('') + queueToggle;
}

function renderHistory() {
  const finished = state.history.items;
  const pager = $('historyPager');
  if (!finished.length) { $('history').innerHTML = '<div class="history-empty">完成的生成会保存在这里</div>'; return; }
  $('history').innerHTML = finished.map((item, index) => {
    const image = item.outputs?.[0];
    const replayLabel = item.seed === null || item.seed === undefined ? '复刻参数（未记录种子）' : `复刻参数（种子 ${item.seed}）`;
    const taskId = taskIdFromImage(image);
    const deleteButton = taskId ? `<button class="history-action-button" type="button" data-history-action="delete" data-history-index="${index}" title="删除这张历史图片" aria-label="删除这张历史图片"><i data-lucide="trash-2"></i></button>` : '';
    const actions = image ? `<div class="history-card-actions"><button class="history-action-button" type="button" data-history-action="replay" data-history-index="${index}" title="${escapeHtml(replayLabel)}" aria-label="${escapeHtml(replayLabel)}"><i data-lucide="play"></i></button><button class="history-action-button" type="button" data-history-action="preview" data-history-index="${index}" title="放大图片" aria-label="放大图片"><i data-lucide="maximize-2"></i></button><button class="history-action-button" type="button" data-history-action="copy" data-history-index="${index}" title="复制提示词" aria-label="复制提示词"><i data-lucide="copy"></i></button><a class="history-action-button" href="${escapeHtml(image.url)}" download="${escapeHtml(image.filename || 'generated-image.png')}" title="下载图片" aria-label="下载图片"><i data-lucide="download"></i></a>${deleteButton}</div>` : '';
    return `<article class="history-card"><div class="history-image ${image ? '' : 'loading-shimmer'}">${image ? `<img src="${escapeHtml(image.thumb_url || image.url)}" data-full-src="${escapeHtml(image.url)}" alt="生成结果" loading="lazy" decoding="async">` : (item.status === 'error' ? '生成失败' : '无预览')}</div><div class="history-copy"><p>${escapeHtml(item.prompt)}</p><div class="history-meta"><time>${new Date(item.created_at).toLocaleString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' })} · ${statusLabel(item.status)}</time>${actions}</div></div></article>`;
  }).join('');
  window.lucide?.createIcons();
  pager.hidden = state.history.total_pages <= 1;
  $('historyPageInfo').textContent = `${state.history.page} / ${state.history.total_pages} · ${state.history.total} 条`;
  pager.querySelector('[data-history-page="previous"]').disabled = state.history.page <= 1;
  pager.querySelector('[data-history-page="next"]').disabled = state.history.page >= state.history.total_pages;
}

async function refresh() {
  const historyQuery = state.historyVisible ? `?include_history=1&history_page=${state.historyPage}&history_page_size=10` : '';
  const [tasks, health] = await Promise.all([fetch(`api/tasks${historyQuery}`).then((r) => r.json()), fetch('api/health').then((r) => r.json()).catch(() => ({ ok: false }))]);
  state.items = tasks.active_items || tasks.items || [];
  if (state.historyVisible) {
    state.history = tasks.history || { items: [], page: 1, total_pages: 1, total: 0 };
    state.historyPage = state.history.page;
    renderHistory();
  }
  renderActive();
  $('healthDot').className = `health-dot ${health.ok ? 'online' : 'offline'}`;
  $('healthText').textContent = health.ok ? `${health.version || 'ComfyUI'} · ${String(health.device || 'GPU').split(' : ')[0]}` : '生成引擎不可达';
}

async function poll() {
  await refresh();
  if (state.items.some((item) => ['queued', 'running'].includes(item.status))) setTimeout(poll, 1200);
}

async function refreshRewrite() {
  const result = await fetch('api/rewrite/status').then((r) => r.json()).catch(() => null);
  if (!result) return;
  const labels = { idle: '空闲', running: '运行中', done: '已完成', error: '失败' };
  $('rewriteStatus').textContent = labels[result.status] || result.status;
  $('rewriteStart').disabled = result.status === 'running';
  $('rewriteStop').disabled = result.status !== 'running';
  $('rewriteLogs').textContent = result.logs?.length ? result.logs.join('\n') : '暂无日志';
  $('rewriteLogs').scrollTop = $('rewriteLogs').scrollHeight;
  if (result.status === 'running') setTimeout(refreshRewrite, 1200);
}

$('rewriteStart').addEventListener('click', async () => {
  const response = await fetch('api/rewrite/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ctx: Number($('rewriteCtx').value) }) });
  if (!response.ok) { const result = await response.json(); $('rewriteLogs').textContent = result.error || '启动失败'; return; }
  refreshRewrite();
});
$('rewriteStop').addEventListener('click', async () => { await fetch('api/rewrite/stop', { method: 'POST' }); refreshRewrite(); });

function batchPrompts() {
  return $('batchPrompts').value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function renderGenerationMode() {
  const batch = state.generationMode === 'batch';
  $('singlePromptField').hidden = batch;
  $('batchPromptField').hidden = !batch;
  $('prompt').required = !batch;
  $('batchPrompts').required = batch;
  document.querySelectorAll('.mode-tab').forEach((button) => button.classList.toggle('active', button.dataset.mode === state.generationMode));
  $('submitButton').querySelector('span').textContent = batch ? `加入 ${batchPrompts().length || 0} 条生成队列` : '加入生成队列';
}

function renderBatchCount() {
  const count = batchPrompts().length;
  $('batchPromptCount').textContent = `${count} 条待生成`;
  if (state.generationMode === 'batch') $('submitButton').querySelector('span').textContent = `加入 ${count} 条生成队列`;
}

function renderSizePresets() {
  const width = Number($('width').value);
  const height = Number($('height').value);
  document.querySelectorAll('.size-preset').forEach((button) => button.classList.toggle('active', Number(button.dataset.width) === width && Number(button.dataset.height) === height));
}

$('generateForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const width = Number($('width').value);
  const height = Number($('height').value);
  const batch_size = Number($('batchSize').value);
  const button = $('submitButton');
  button.disabled = true; button.querySelector('span').textContent = '正在加入队列…'; $('formMessage').textContent = '';
  try {
    const batch = state.generationMode === 'batch';
    const response = await fetch(batch ? 'api/generate/batch' : 'api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(batch ? { prompts: batchPrompts(), negative_prompt: $('negativePrompt').value, width, height, batch_size, seed: $('seed').value || null } : { prompt: $('prompt').value, negative_prompt: $('negativePrompt').value, width, height, batch_size, seed: $('seed').value || null }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '提交失败');
    $('formMessage').textContent = batch ? `已创建 ${result.created} 条任务` : `任务已创建 · ${result.id.slice(0, 8)}`;
    poll();
  } catch (error) { $('formMessage').textContent = error.message; } finally { button.disabled = false; renderGenerationMode(); }
});

$('batchPrompts').addEventListener('input', renderBatchCount);
document.querySelectorAll('.mode-tab').forEach((button) => button.addEventListener('click', () => { state.generationMode = button.dataset.mode; renderGenerationMode(); renderBatchCount(); }));
document.querySelectorAll('.size-preset').forEach((button) => button.addEventListener('click', () => { $('width').value = button.dataset.width; $('height').value = button.dataset.height; renderSizePresets(); }));
$('width').addEventListener('input', renderSizePresets);
$('height').addEventListener('input', renderSizePresets);
$('refreshBtn').addEventListener('click', poll);
refreshRewrite();
$('toggleHistory').addEventListener('click', async () => {
  state.historyVisible = !state.historyVisible;
  $('historyContent').hidden = !state.historyVisible;
  $('clearHistory').hidden = !state.historyVisible;
  $('toggleHistory').textContent = state.historyVisible ? '收起' : '展示';
  $('toggleHistory').setAttribute('aria-expanded', String(state.historyVisible));
  if (!state.historyVisible) return;
  state.historyPage = 1;
  $('history').innerHTML = '<div class="history-empty">正在查询历史记录…</div>';
  await refresh();
});
$('historyPager').addEventListener('click', (event) => { const button = event.target.closest('[data-history-page]'); if (!button || button.disabled || !state.historyVisible) return; state.historyPage += button.dataset.historyPage === 'next' ? 1 : -1; refresh(); });
$('history').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-history-action]');
  if (!button) return;
  const item = state.history.items[Number(button.dataset.historyIndex)];
  const image = item?.outputs?.[0];
  if (!item || !image) return;
  if (button.dataset.historyAction === 'delete') {
    const taskId = taskIdFromImage(image);
    if (!taskId || !window.confirm('删除这张历史图片？此操作不可恢复。')) return;
    button.disabled = true;
    try {
      const response = await fetch(`api/tasks/${taskId}/images/${encodeURIComponent(image.filename)}`, { method: 'DELETE' });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '删除失败');
      $('formMessage').textContent = '已删除历史图片。';
      await refresh();
    } catch (error) {
      button.disabled = false;
      $('formMessage').textContent = error.message;
    }
    return;
  }
  if (button.dataset.historyAction === 'replay') {
    state.generationMode = 'single';
    $('prompt').value = item.prompt || '';
    $('negativePrompt').value = item.negative_prompt || '';
    $('width').value = item.width || 1024;
    $('height').value = item.height || 1024;
    $('batchSize').value = item.batch_size || 1;
    $('seed').value = item.seed ?? '';
    renderGenerationMode();
    renderSizePresets();
    $('formMessage').textContent = item.seed === null || item.seed === undefined
      ? '已回填可用参数；该历史任务未记录种子。'
      : '已复刻全部参数，可调整后加入队列。';
    document.querySelector('.composer')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  if (button.dataset.historyAction === 'preview') {
    $('previewImage').src = image.url;
    $('previewPrompt').textContent = item.prompt || '未记录提示词';
    if (!$('imagePreviewDialog').open) $('imagePreviewDialog').showModal();
    return;
  }
  if (button.dataset.historyAction !== 'copy') return;
  try {
    await copyText(item.prompt);
    button.classList.add('copied');
    button.title = '已复制';
    button.setAttribute('aria-label', '提示词已复制');
    setTimeout(() => { button.classList.remove('copied'); button.title = '复制提示词'; button.setAttribute('aria-label', '复制提示词'); }, 1200);
  } catch (_) {
    button.title = '复制失败';
  }
});
$('closeImagePreview').addEventListener('click', () => $('imagePreviewDialog').close());
$('imagePreviewDialog').addEventListener('click', (event) => { if (event.target === $('imagePreviewDialog')) $('imagePreviewDialog').close(); });
 $('activeTasks').addEventListener('click', async (event) => { const toggle = event.target.closest('[data-queue-toggle]'); if (toggle) { state.queueExpanded = toggle.dataset.queueToggle === 'expand'; renderActive(); return; } const button = event.target.closest('.cancel-button'); if (!button) return; button.disabled = true; await fetch(`api/tasks/${button.dataset.taskId}/cancel`, { method: 'POST' }); poll(); });
$('clearHistory').addEventListener('click', async () => { await fetch('api/tasks/history', { method: 'DELETE' }); state.history = { items: [], page: 1, total_pages: 1, total: 0 }; if (state.historyVisible) await refresh(); });
renderGenerationMode();
renderSizePresets();
poll();
