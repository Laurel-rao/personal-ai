(() => {
  const state = { items: [], filtered: [], page: 1, pageSize: 36 };
  const $ = (id) => document.getElementById(id);
  const categoryNames = { sexy: '性感女性', closeup: '女生特写（上半身）' };

  function escape(value) { return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char])); }
  function selectedCategories() { return new Set([...document.querySelectorAll('[data-library-category]:checked')].map((input) => input.dataset.libraryCategory)); }
  function dateValue(id, endOfDay = false) { const value = $(id).value; return value ? new Date(`${value}T${endOfDay ? '23:59:59' : '00:00:00'}`).getTime() : null; }
  function formatDate(value) { if (!value) return '未知时间'; const date = new Date(value); return Number.isNaN(date.getTime()) ? '未知时间' : date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }); }
  function applyFilters() {
    const categories = selectedCategories();
    const label = $('libraryLabel').value;
    const search = $('librarySearch').value.trim().toLowerCase();
    const from = dateValue('libraryFrom');
    const to = dateValue('libraryTo', true);
    state.filtered = state.items.filter((item) => {
      if (!categories.has(item.category || 'sexy')) return false;
      if (label === 'unlabeled' ? item.label : label !== 'all' && item.label !== label) return false;
      if (search && !(item.prompt || '').toLowerCase().includes(search)) return false;
      const timestamp = new Date(item.created_at || 0).getTime();
      if (from !== null && (Number.isNaN(timestamp) || timestamp < from)) return false;
      if (to !== null && (Number.isNaN(timestamp) || timestamp > to)) return false;
      return true;
    }).sort((a, b) => {
      const direction = $('librarySort').value === 'oldest' ? 1 : -1;
      return direction * (new Date(a.created_at || 0).getTime() - new Date(b.created_at || 0).getTime());
    });
    state.page = 1;
    render();
  }
  function render() {
    const total = state.filtered.length;
    const pages = Math.max(1, Math.ceil(total / state.pageSize));
    state.page = Math.min(state.page, pages);
    const start = (state.page - 1) * state.pageSize;
    const pageItems = state.filtered.slice(start, start + state.pageSize);
    $('libraryTotal').textContent = `${state.items.length} 张图片`;
    $('libraryResultCount').textContent = `筛选结果 ${total} 张`;
    $('libraryPageInfo').textContent = total ? `${start + 1}-${Math.min(start + state.pageSize, total)} / ${total}` : '无匹配结果';
    $('libraryPager').hidden = pages <= 1;
    $('libraryPagerText').textContent = `${state.page} / ${pages}`;
    $('libraryPrev').disabled = state.page <= 1;
    $('libraryNext').disabled = state.page >= pages;
    if (!pageItems.length) { $('libraryGrid').innerHTML = '<div class="library-empty">没有符合条件的图片</div>'; return; }
    $('libraryGrid').innerHTML = pageItems.map((item) => {
      const category = item.category || 'sexy';
      const label = item.label || 'unlabeled';
      return `<article class="library-card"><div class="library-card-media" data-preview-url="${escape(item.url)}" data-preview-prompt="${escape(item.prompt || '')}"><img loading="lazy" src="${escape(item.thumb_url || item.url)}" alt="${escape(categoryNames[category] || '图片')}"/><span class="library-card-badge">${escape(categoryNames[category] || '其他类别')}</span></div><div class="library-card-body"><div class="library-card-meta"><span class="library-card-label ${label}">${label === 'like' ? 'LIKE' : label === 'unlike' ? 'UNLIKE' : '未标注'}</span><span class="library-card-number" title="${escape(item.filename || item.id)}">编号 ${escape(item.filename || item.id)}</span><time>${escape(formatDate(item.created_at))}</time></div><p class="library-card-prompt" title="${escape(item.prompt)}">${escape(item.prompt || '未附带提示词')}</p><div class="library-card-actions"><button class="library-label-button like${label === 'like' ? ' active' : ''}" data-label="like" data-image-id="${escape(item.id)}"><i data-lucide="thumbs-up"></i>Like</button><button class="library-label-button unlike${label === 'unlike' ? ' active' : ''}" data-label="unlike" data-image-id="${escape(item.id)}"><i data-lucide="thumbs-down"></i>Unlike</button><button class="library-label-button" data-copy-prompt data-prompt="${escape(item.prompt || '')}"><i data-lucide="copy"></i>复制</button><button class="library-label-button" data-preview-url="${escape(item.url)}" data-preview-prompt="${escape(item.prompt || '')}"><i data-lucide="maximize-2"></i>放大</button><a class="library-label-button" href="${escape(item.url)}" download="${escape(item.filename || 'image.png')}"><i data-lucide="download"></i>下载</a></div></div></article>`;
    }).join('');
    $('libraryGrid').querySelectorAll('.library-label-button').forEach((button) => {
      button.title = button.textContent.trim();
      button.setAttribute('aria-label', button.title);
      if (button.dataset.label) button.setAttribute('aria-pressed', String(button.classList.contains('active')));
    });
    window.personalAI?.renderIcons();
  }
  async function load() {
    try {
      const response = await fetch('api/review/items');
      if (!response.ok) throw new Error(`图片读取失败（HTTP ${response.status}）`);
      const result = await response.json(); state.items = result.items || []; applyFilters();
    } catch (error) { $('libraryGrid').innerHTML = `<div class="library-empty">${escape(error.message || '图片读取失败')}</div>`; }
  }
  async function setLabel(button) {
    const item = state.items.find((entry) => entry.id === button.dataset.imageId); if (!item) return;
    const value = item.label === button.dataset.label ? null : button.dataset.label;
    button.disabled = true;
    try {
      const response = await fetch('api/review/label', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image_id: item.id, value }) });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || '标注失败');
      item.label = value; applyFilters();
    } catch (error) { button.title = error.message || '标注失败'; } finally { button.disabled = false; }
  }
  async function copyPrompt(button) {
    const text = button.dataset.prompt || '';
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      const helper = document.createElement('textarea'); helper.value = text; helper.style.position = 'fixed'; helper.style.opacity = '0'; document.body.appendChild(helper); helper.select(); document.execCommand('copy'); helper.remove();
    }
    const original = button.innerHTML; button.innerHTML = '<i data-lucide="check"></i>已复制'; button.classList.add('copied'); button.title = '已复制提示词'; button.setAttribute('aria-label', button.title); window.personalAI?.renderIcons();
    window.setTimeout(() => { button.innerHTML = original; button.classList.remove('copied'); button.title = '复制'; button.setAttribute('aria-label', button.title); window.personalAI?.renderIcons(); }, 1200);
  }
  function openPreview(element) {
    window.personalAI.previewImage({ url: element.dataset.previewUrl, prompt: element.dataset.previewPrompt });
  }
  document.querySelectorAll('[data-library-category], #libraryLabel, #libraryFrom, #libraryTo, #librarySort').forEach((input) => input.addEventListener('change', applyFilters));
  $('librarySearch').addEventListener('input', applyFilters);
  $('libraryReset').addEventListener('click', () => { document.querySelectorAll('[data-library-category]').forEach((input) => { input.checked = true; }); $('librarySearch').value = ''; $('libraryLabel').value = 'all'; $('libraryFrom').value = ''; $('libraryTo').value = ''; $('librarySort').value = 'newest'; applyFilters(); });
  $('libraryAllCategories').addEventListener('click', () => { document.querySelectorAll('[data-library-category]').forEach((input) => { input.checked = true; }); applyFilters(); });
  $('libraryPrev').addEventListener('click', () => { state.page -= 1; render(); });
  $('libraryNext').addEventListener('click', () => { state.page += 1; render(); });
  $('libraryGrid').addEventListener('click', (event) => {
    const labelButton = event.target.closest('[data-label]'); if (labelButton) return setLabel(labelButton);
    const copyButton = event.target.closest('[data-copy-prompt]'); if (copyButton) return copyPrompt(copyButton);
    const preview = event.target.closest('[data-preview-url]'); if (preview) openPreview(preview);
  });
  load();
})();
