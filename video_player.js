(() => {
  const $ = (id) => document.getElementById(id);
  const video = $('mainVideo');
  const stage = $('videoStage');
  const controls = $('videoControls');
  const menus = [...controls.querySelectorAll('details')];
  const rates = [0.5, 0.75, 1, 1.25, 1.5, 2];
  const modeNames = { sequence: '顺序播放', single: '单集循环', list: '列表循环' };
  const settings = { volume: 0.8, muted: false, rate: 1, fit: 'contain', mode: 'sequence' };
  const storage = {
    read(key, fallback) {
      try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (_) { return fallback; }
    },
    write(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
    },
    remove(key) {
      try { localStorage.removeItem(key); } catch (_) {}
    },
  };
  const savedSettings = storage.read('player-settings', {});
  if (savedSettings && typeof savedSettings === 'object') {
    if (Number.isFinite(savedSettings.volume) && savedSettings.volume >= 0 && savedSettings.volume <= 1) settings.volume = savedSettings.volume;
    if (typeof savedSettings.muted === 'boolean') settings.muted = savedSettings.muted;
    if (rates.includes(savedSettings.rate)) settings.rate = savedSettings.rate;
    if (['contain', 'cover'].includes(savedSettings.fit)) settings.fit = savedSettings.fit;
    if (Object.hasOwn(modeNames, savedSettings.mode)) settings.mode = savedSettings.mode;
  }
  const savedFavorites = storage.read('player-favorites', []);
  const state = {
    items: [], filtered: [], activeItem: null, format: 'all', query: '',
    favorites: new Set(Array.isArray(savedFavorites) ? savedFavorites.filter((item) => typeof item === 'string') : []),
    generation: 0, refreshGeneration: 0, metadataReady: false, resumeAt: 0,
    lastSavedAt: 0, dragging: false, scrubPaused: true, keyboard: false,
    hideTimer: null, toastTimer: null, clickTimer: null, wakeOnly: false,
  };
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
  const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
  const activeIndex = () => state.filtered.findIndex((item) => item.id === state.activeItem?.id);
  const playable = () => state.metadataReady && Number.isFinite(video.duration) && video.duration > 0 && !video.error;
  const matchesSource = () => state.activeItem && video.currentSrc === new URL(state.activeItem.url, location.href).href;

  function formatTime(seconds) {
    const total = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
    const hours = Math.floor(total / 3600);
    const minutes = String(Math.floor(total / 60) % 60).padStart(2, '0');
    const remainder = String(total % 60).padStart(2, '0');
    return hours ? `${String(hours).padStart(2, '0')}:${minutes}:${remainder}` : `${minutes}:${remainder}`;
  }

  function formatSize(bytes) {
    if (!bytes) return '--';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = bytes;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
    return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
  }

  function notify(message) {
    clearTimeout(state.toastTimer);
    $('operationToast').textContent = message;
    $('operationToast').hidden = false;
    state.toastTimer = setTimeout(() => { $('operationToast').hidden = true; }, 1500);
  }

  function controlsLocked() {
    return video.paused || video.ended || video.error || state.dragging || menus.some((menu) => menu.open)
      || (state.keyboard && controls.contains(document.activeElement));
  }

  function showControls() {
    clearTimeout(state.hideTimer);
    stage.classList.remove('controls-hidden');
    controls.inert = false;
    controls.removeAttribute('aria-hidden');
    if (!controlsLocked()) {
      state.hideTimer = setTimeout(() => {
        if (controlsLocked()) return;
        stage.classList.add('controls-hidden');
        controls.inert = true;
        controls.setAttribute('aria-hidden', 'true');
      }, 5000);
    }
  }

  function syncSettings() {
    video.style.objectFit = settings.fit;
    $('stageFit').textContent = settings.fit === 'contain' ? '切换为裁剪填充' : '切换为完整画面';
    $('stageFit').setAttribute('aria-label', settings.fit === 'contain' ? '切换为裁剪填充' : '切换为完整画面');
    $('stageFit').title = settings.fit === 'contain' ? '完整画面 · 点击裁剪填充' : '裁剪填充 · 点击显示完整画面';
    $('speedLabel').textContent = `${Number.isInteger(settings.rate) ? settings.rate.toFixed(1) : settings.rate}x`;
    $('modeLabel').textContent = modeNames[settings.mode];
    controls.querySelectorAll('[data-rate]').forEach((button) => button.setAttribute('aria-pressed', String(Number(button.dataset.rate) === settings.rate)));
    controls.querySelectorAll('[data-mode]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.mode === settings.mode)));
    $('volumeBar').value = String(video.volume);
    const silent = video.muted || video.volume === 0;
    $('muteButton').textContent = silent ? '🔇' : '🔊';
    $('muteButton').setAttribute('aria-label', silent ? '取消静音' : '静音');
    $('muteButton').setAttribute('aria-pressed', String(silent));
    storage.write('player-settings', settings);
  }

  function neighbor(direction) {
    const index = activeIndex();
    if (index < 0) return null;
    const target = index + direction;
    if (settings.mode === 'list') return state.filtered[(target + state.filtered.length) % state.filtered.length];
    return state.filtered[target] || null;
  }

  function renderNavigation() {
    const index = activeIndex();
    const next = neighbor(1);
    $('currentIndex').textContent = !state.activeItem ? '0 / 0' : index < 0 ? '当前视频不在筛选结果中' : `${index + 1} / ${state.filtered.length}`;
    $('prevButton').disabled = !neighbor(-1);
    $('nextButton').disabled = !next;
    $('nextStripButton').disabled = !next;
    $('nextTitle').textContent = next?.title || (state.activeItem ? index < 0 ? '当前视频不在筛选结果中，已暂停自动切集' : '已是当前筛选的最后一集' : '选择视频后显示下一集');
  }

  function renderList() {
    $('playlistCount').textContent = state.filtered.length;
    $('playlistFooterText').textContent = `${state.filtered.length} 部视频`;
    $('playlistList').innerHTML = state.filtered.length ? state.filtered.map((item, index) => {
      const metadata = item.metadata || {};
      const details = [metadata.code, ...(metadata.actors || [])].filter(Boolean).join(' · ');
      const cover = metadata.cover_url ? `<img src="${escape(metadata.cover_url)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : '';
      return `<button class="playlist-item${item.id === state.activeItem?.id ? ' active' : ''}" type="button" data-index="${index}" aria-current="${item.id === state.activeItem?.id}" aria-label="播放 ${escape(item.title)}"><span class="playlist-thumb">${cover}<span>${escape(metadata.code || '▶')}</span></span><span class="playlist-item-body"><strong class="playlist-item-title">${escape(item.title)}</strong>${details ? `<span class="playlist-catalog-line">${escape(details)}</span>` : ''}<span class="playlist-item-meta"><span>${escape(item.extension.toUpperCase())}</span><span>${escape(formatSize(item.size))}</span></span></span></button>`;
    }).join('') : '<div class="playlist-empty">没有符合条件的视频</div>';
    renderNavigation();
  }

  function applyFilter() {
    const query = state.query.trim().toLowerCase();
    state.filtered = state.items.filter((item) => (state.format === 'all' || item.extension === state.format)
      && (!query || [item.title, item.filename, item.metadata?.code, item.metadata?.full_title, ...(item.metadata?.actors || []), item.metadata?.publisher, ...(item.metadata?.genres || [])].join(' ').toLowerCase().includes(query)));
    renderList();
  }

  function renderItem() {
    const item = state.activeItem;
    $('stageEmpty').hidden = Boolean(item);
    $('videoTitle').textContent = item?.title || '未选择视频';
    $('videoMeta').textContent = item ? `${item.filename} · 最近修改 ${new Date(item.modified_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}` : '从右侧片库选择视频，播放器会记住上次播放位置。';
    $('videoTypeTag').textContent = item?.extension.toUpperCase() || 'LOCAL FILE';
    $('videoSizeTag').textContent = item ? formatSize(item.size) : '--';
    $('downloadButton').href = item?.url || '#';
    $('downloadButton').download = item?.filename || 'video';
    $('downloadButton').setAttribute('aria-disabled', String(!item));
    $('downloadButton').tabIndex = item ? 0 : -1;
    $('copyPathButton').disabled = !item || !navigator.clipboard?.writeText;
    $('copyPathButton').title = navigator.clipboard?.writeText ? '复制片库相对路径' : '当前浏览器不支持复制，请使用安全连接';
    $('favoriteButton').disabled = !item;
    const favorite = Boolean(item && state.favorites.has(item.id));
    $('favoriteButton').textContent = favorite ? '♥ 已收藏' : '♡ 收藏';
    $('favoriteButton').setAttribute('aria-pressed', String(favorite));
    renderMetadata(item);
    renderNavigation();
    renderPlayback();
  }

  function renderMetadata(item) {
    $('filmDetails').hidden = !item;
    if (!item) return;
    const metadata = item.metadata || {};
    const labels = { verified: '已核实', partial: '第三方资料 · 待核实', not_found: '已检索 · 资料不足', pending: '尚未检索', unidentified: '未识别编号' };
    $('metadataStatus').textContent = labels[metadata.status] || '尚未检索';
    $('metadataStatus').dataset.status = metadata.status || 'pending';
    $('filmFullTitle').textContent = metadata.full_title || '待补充';
    $('filmActors').textContent = metadata.actors?.join('、') || '待补充';
    $('filmPublisher').textContent = metadata.publisher || '待补充';
    $('filmGenres').textContent = metadata.genres?.join(' / ') || '待补充';
    $('filmReleaseDate').textContent = metadata.release_date || '待补充';
    const technical = metadata.technical || {};
    $('filmTechnical').textContent = technical.duration ? [formatTime(technical.duration), technical.width && technical.height ? `${technical.width} × ${technical.height}` : '', technical.video_codec?.toUpperCase(), technical.audio_codec?.toUpperCase()].filter(Boolean).join(' · ') : technical.error || '尚未采集，或文件已变更';
    $('metadataNote').textContent = metadata.note || '缺失资料保留为空，不根据文件名推测演员、发行商或类型。';
    $('metadataSource').textContent = [metadata.sources?.map((source) => source.name).filter(Boolean).join('；'), metadata.checked_at ? `检索日期 ${metadata.checked_at}` : '未进行网络检索'].filter(Boolean).join(' · ');
    $('filmCover').replaceChildren();
    const placeholder = document.createElement('div');
    placeholder.className = 'film-cover-placeholder';
    const code = document.createElement('strong');
    code.textContent = metadata.code || item.extension.toUpperCase();
    const caption = document.createElement('span');
    caption.textContent = '暂无已审核封面';
    placeholder.append(code, caption);
    $('filmCover').append(placeholder);
    if (metadata.cover_url) {
      const image = document.createElement('img');
      image.alt = `${metadata.code || item.title} 封面`;
      image.referrerPolicy = 'no-referrer';
      image.addEventListener('error', () => image.remove(), { once: true });
      image.src = metadata.cover_url;
      $('filmCover').append(image);
    }
  }

  function renderPlayback() {
    const available = Boolean(state.activeItem && !video.error);
    $('playButton').disabled = !available;
    $('centerPlay').hidden = !available || !video.paused || !$('stageError').hidden;
    const label = video.paused ? '播放' : '暂停';
    $('playButton').textContent = video.paused ? '▶' : '❚❚';
    $('playButton').setAttribute('aria-label', label);
    $('centerPlay').setAttribute('aria-label', label);
    ['seekBar', 'rewindButton', 'forwardButton'].forEach((id) => { $(id).disabled = !playable(); });
    const pipSupported = Boolean(document.pictureInPictureEnabled && video.requestPictureInPicture);
    $('pipButton').disabled = !pipSupported || !playable();
    $('pipButton').title = pipSupported ? '画中画' : '当前浏览器不支持画中画';
    const fullscreenSupported = Boolean((document.fullscreenEnabled && stage.requestFullscreen) || video.webkitEnterFullscreen);
    $('fullscreenButton').disabled = !fullscreenSupported || !state.activeItem;
    $('fullscreenButton').title = fullscreenSupported ? '全屏（F）' : '当前浏览器不支持全屏';
  }

  function saveProgress(force = false) {
    if (!playable() || !state.activeItem || !Number.isFinite(video.currentTime)) return;
    if (video.ended) { storage.remove(`player-time:${state.activeItem.id}`); return; }
    if (!force && Date.now() - state.lastSavedAt < 2000) return;
    storage.write(`player-time:${state.activeItem.id}`, video.currentTime);
    state.lastSavedAt = Date.now();
  }

  async function play() {
    if (!state.activeItem) return;
    const generation = state.generation;
    try { await video.play(); } catch (error) {
      if (generation !== state.generation || error.name === 'AbortError') return;
      if (error.name === 'NotAllowedError') notify('浏览器阻止了播放，请点击播放按钮');
      else if (video.error) showError();
      else notify('播放失败，请重试');
      showControls();
    }
  }

  function loadItem(item, autoplay = false, resumeAt = null) {
    if (!item) return;
    saveProgress(true);
    state.metadataReady = false;
    state.generation += 1;
    clearTimeout(state.clickTimer);
    state.dragging = false;
    state.lastSavedAt = 0;
    video.pause();
    state.activeItem = item;
    const saved = resumeAt ?? storage.read(`player-time:${item.id}`, 0);
    state.resumeAt = Number.isFinite(saved) && saved > 0 ? saved : 0;
    $('stageError').hidden = true;
    $('resumeNotice').hidden = true;
    $('seekPreview').hidden = true;
    $('videoResolutionTag').textContent = '正在读取';
    $('stageLoading').textContent = '正在加载…';
    $('stageLoading').hidden = false;
    menus.forEach((menu) => { menu.open = false; });
    video.src = item.url;
    video.load();
    video.playbackRate = settings.rate;
    renderItem();
    renderList();
    renderProgress();
    showControls();
    history.replaceState(null, '', `/player?video=${encodeURIComponent(item.id)}`);
    if (autoplay) play();
  }

  function renderProgress() {
    const duration = playable() ? video.duration : 0;
    const time = state.dragging ? Number($('seekBar').value) / 1000 * duration : video.currentTime || 0;
    if (!state.dragging) $('seekBar').value = duration ? Math.round(time / duration * 1000) : 0;
    $('currentTime').textContent = formatTime(time);
    $('duration').textContent = formatTime(duration);
    $('seekBar').setAttribute('aria-valuetext', `${formatTime(time)} / ${formatTime(duration)}`);
    $('seekPlayed').style.width = `${duration ? clamp(time / duration * 100, 0, 100) : 0}%`;
    const segments = [];
    if (duration) {
      for (let index = 0; index < video.buffered.length; index += 1) {
        const start = clamp(video.buffered.start(index) / duration * 100, 0, 100);
        const end = clamp(video.buffered.end(index) / duration * 100, 0, 100);
        segments.push(`<span style="left:${start}%;width:${end - start}%"></span>`);
      }
    }
    $('seekBuffer').innerHTML = segments.join('');
  }

  function seekTo(seconds, announce = true) {
    if (!playable() || !Number.isFinite(seconds)) return;
    video.currentTime = clamp(seconds, 0, video.duration);
    $('resumeNotice').hidden = true;
    renderProgress();
    if (announce) notify(`跳转至 ${formatTime(video.currentTime)}`);
    showControls();
  }

  function togglePlay() {
    if (!state.activeItem || video.error) return;
    if (video.paused) play();
    else video.pause();
    showControls();
  }

  function switchItem(direction) {
    const item = neighbor(direction);
    if (item) loadItem(item, true, item.id === state.activeItem?.id ? 0 : null);
  }

  function showError() {
    if (!matchesSource() || !video.error) return;
    const messages = {
      1: ['播放已中断', '点击重新加载继续播放'],
      2: ['视频读取失败', '请检查文件是否仍存在，然后重试'],
      3: ['视频解码失败', '当前文件可能损坏，或浏览器无法解码此格式'],
      4: ['无法播放此文件', '文件可能不可访问，或浏览器不支持此格式'],
    };
    const [title, message] = messages[video.error.code] || ['播放失败', '请重试或下载原文件'];
    $('errorTitle').textContent = title;
    $('errorMessage').textContent = message;
    $('stageError').hidden = false;
    $('stageLoading').hidden = true;
    $('videoResolutionTag').textContent = '播放失败';
    $('stageErrorDownload').href = state.activeItem.url;
    $('stageErrorDownload').download = state.activeItem.filename;
    renderPlayback();
    showControls();
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (document.fullscreenEnabled && stage.requestFullscreen) await stage.requestFullscreen();
      else if (video.webkitDisplayingFullscreen && video.webkitExitFullscreen) video.webkitExitFullscreen();
      else if (video.webkitEnterFullscreen && playable()) video.webkitEnterFullscreen();
      else notify('当前浏览器不支持全屏');
    } catch (_) { notify('无法切换全屏，请重试'); }
    showControls();
  }

  async function togglePip() {
    try {
      if (document.pictureInPictureElement) await document.exitPictureInPicture();
      else if (document.pictureInPictureEnabled && video.requestPictureInPicture && playable()) await video.requestPictureInPicture();
      else notify('当前浏览器不支持画中画');
    } catch (_) { notify('无法开启画中画，请重试'); }
  }

  async function refresh() {
    const generation = ++state.refreshGeneration;
    $('playerStatus').textContent = '读取本地片库';
    try {
      const response = await fetch('/api/player/videos');
      if (!response.ok) throw new Error('片库请求失败');
      const data = await response.json();
      if (!Array.isArray(data.items)) throw new Error('片库格式无效');
      if (generation !== state.refreshGeneration) return;
      state.items = data.items;
      $('playerStatus').textContent = `${state.items.length} 部本地视频`;
      const catalog = data.catalog;
      $('catalogProgress').textContent = data.catalog_warning || (catalog ? `已检索 ${catalog.checked}/${catalog.total} · 本地参数 ${catalog.technical}/${catalog.total} · 封面 ${catalog.covers}/${catalog.total}` : '资料服务尚未启用');
      if (state.activeItem) {
        const updated = state.items.find((item) => item.id === state.activeItem.id);
        if (updated) { state.activeItem = updated; renderItem(); }
      }
      applyFilter();
      if (!state.activeItem && state.items.length) {
        const target = new URLSearchParams(location.search).get('video');
        loadItem(state.items.find((item) => item.id === target) || state.filtered.find((item) => item.extension === 'mp4') || state.filtered[0]);
      }
    } catch (_) {
      if (generation !== state.refreshGeneration) return;
      $('playerStatus').textContent = '片库读取失败，请刷新重试';
      if (!state.items.length) $('playlistList').innerHTML = '<div class="playlist-empty">无法读取 Movies 目录，请点击刷新重试</div>';
      notify('片库读取失败，已保留当前播放');
    }
  }

  $('playlistList').addEventListener('click', (event) => {
    const button = event.target.closest('[data-index]');
    if (button) loadItem(state.filtered[Number(button.dataset.index)], true);
  });
  $('playlistList').addEventListener('error', (event) => {
    if (event.target instanceof HTMLImageElement) event.target.remove();
  }, true);
  $('searchInput').addEventListener('input', (event) => { state.query = event.target.value; applyFilter(); });
  document.querySelectorAll('.format-tab').forEach((tab) => tab.addEventListener('click', () => {
    state.format = tab.dataset.format;
    document.querySelectorAll('.format-tab').forEach((item) => {
      item.classList.toggle('active', item === tab);
      item.setAttribute('aria-selected', String(item === tab));
    });
    applyFilter();
  }));
  $('refreshButton').addEventListener('click', refresh);
  $('playButton').addEventListener('click', togglePlay);
  $('prevButton').addEventListener('click', () => switchItem(-1));
  $('nextButton').addEventListener('click', () => switchItem(1));
  $('nextStripButton').addEventListener('click', () => switchItem(1));
  $('rewindButton').addEventListener('click', () => seekTo(video.currentTime - 10));
  $('forwardButton').addEventListener('click', () => seekTo(video.currentTime + 10));
  $('pipButton').addEventListener('click', togglePip);
  $('fullscreenButton').addEventListener('click', toggleFullscreen);
  $('retryButton').addEventListener('click', () => loadItem(state.activeItem, true, video.currentTime || state.resumeAt));
  $('restartButton').addEventListener('click', () => { seekTo(0); saveProgress(true); });
  $('dismissResume').addEventListener('click', () => { $('resumeNotice').hidden = true; });
  $('stageFit').addEventListener('click', () => {
    settings.fit = settings.fit === 'contain' ? 'cover' : 'contain';
    syncSettings();
    notify(settings.fit === 'contain' ? '完整画面' : '裁剪填充');
  });
  $('downloadButton').addEventListener('click', (event) => { if (!state.activeItem) event.preventDefault(); });
  $('favoriteButton').addEventListener('click', () => {
    const item = state.activeItem;
    if (!item) return;
    if (state.favorites.has(item.id)) state.favorites.delete(item.id);
    else state.favorites.add(item.id);
    storage.write('player-favorites', [...state.favorites]);
    renderItem();
  });
  $('copyPathButton').addEventListener('click', async () => {
    if (!state.activeItem) return;
    try { await navigator.clipboard.writeText(state.activeItem.id); notify('已复制片库相对路径'); }
    catch (_) { notify('复制失败，请检查浏览器权限'); }
  });

  menus.forEach((menu) => menu.addEventListener('toggle', showControls));
  controls.addEventListener('click', (event) => {
    const button = event.target.closest('[data-rate], [data-mode]');
    if (!button) return;
    if (button.dataset.rate) { settings.rate = Number(button.dataset.rate); video.playbackRate = settings.rate; }
    if (button.dataset.mode) settings.mode = button.dataset.mode;
    const menu = button.closest('details');
    if (state.keyboard) menu.querySelector('summary').focus();
    menu.open = false;
    syncSettings();
    renderNavigation();
    showControls();
  });
  $('volumeBar').addEventListener('input', (event) => {
    video.volume = Number(event.target.value);
    video.muted = video.volume === 0;
    showControls();
  });
  $('muteButton').addEventListener('click', () => {
    if (video.muted || video.volume === 0) { video.muted = false; if (!video.volume) video.volume = 0.5; }
    else video.muted = true;
    showControls();
  });
  video.addEventListener('volumechange', () => { settings.volume = video.volume; settings.muted = video.muted; syncSettings(); });
  video.addEventListener('ratechange', () => {
    if (!state.metadataReady) return;
    if (rates.includes(video.playbackRate)) settings.rate = video.playbackRate;
    syncSettings();
  });

  video.addEventListener('loadedmetadata', () => {
    if (!matchesSource() || video.readyState < 1) return;
    state.metadataReady = true;
    video.playbackRate = settings.rate;
    if (state.resumeAt > 0 && state.resumeAt < video.duration - 3) {
      video.currentTime = state.resumeAt;
      $('resumeText').textContent = `已恢复至 ${formatTime(state.resumeAt)}`;
      $('resumeNotice').hidden = false;
    }
    state.resumeAt = 0;
    $('videoResolutionTag').textContent = `${video.videoWidth} × ${video.videoHeight}`;
    renderProgress();
    renderPlayback();
  });
  ['loadeddata', 'canplay', 'playing'].forEach((name) => video.addEventListener(name, () => {
    if (!matchesSource() || video.error) return;
    $('stageLoading').hidden = true;
    $('stageError').hidden = true;
    renderPlayback();
  }));
  ['waiting', 'seeking'].forEach((name) => video.addEventListener(name, () => {
    if (!state.activeItem || video.error) return;
    $('stageLoading').textContent = '正在缓冲…';
    $('stageLoading').hidden = false;
  }));
  video.addEventListener('seeked', () => { $('stageLoading').hidden = true; saveProgress(true); });
  video.addEventListener('play', () => { renderPlayback(); showControls(); });
  video.addEventListener('pause', () => { saveProgress(true); renderPlayback(); showControls(); });
  video.addEventListener('timeupdate', () => { renderProgress(); saveProgress(); });
  video.addEventListener('progress', renderProgress);
  video.addEventListener('durationchange', renderProgress);
  video.addEventListener('error', showError);
  video.addEventListener('ended', () => {
    if (!matchesSource() || !state.metadataReady) return;
    storage.remove(`player-time:${state.activeItem.id}`);
    if (settings.mode === 'single') { seekTo(0, false); play(); }
    else if (neighbor(1)) loadItem(neighbor(1), true, 0);
    else { renderPlayback(); showControls(); }
  });
  ['enterpictureinpicture', 'leavepictureinpicture'].forEach((name) => video.addEventListener(name, () => {
    $('pipButton').setAttribute('aria-label', document.pictureInPictureElement ? '退出画中画' : '画中画');
  }));
  document.addEventListener('fullscreenchange', () => {
    $('fullscreenButton').setAttribute('aria-label', document.fullscreenElement ? '退出全屏' : '全屏');
    showControls();
  });

  function previewSeek(ratio) {
    if (!playable()) return;
    const fraction = clamp(ratio, 0, 1);
    $('seekPreview').textContent = formatTime(fraction * video.duration);
    $('seekPreview').style.left = `${clamp(fraction * 100, 5, 95)}%`;
    $('seekPreview').hidden = false;
  }
  $('seekBar').addEventListener('pointerdown', (event) => {
    if (!playable()) return;
    state.dragging = true;
    state.scrubPaused = video.paused;
    video.pause();
    $('seekBar').setPointerCapture(event.pointerId);
    showControls();
  });
  $('seekBar').addEventListener('input', () => {
    const fraction = Number($('seekBar').value) / 1000;
    if (!state.dragging) seekTo(fraction * video.duration, false);
    renderProgress();
    previewSeek(fraction);
  });
  function finishScrub(cancel = false) {
    if (!state.dragging) return;
    const target = Number($('seekBar').value) / 1000 * video.duration;
    state.dragging = false;
    if (!cancel) seekTo(target);
    else renderProgress();
    $('seekPreview').hidden = true;
    if (!state.scrubPaused) play();
    showControls();
  }
  $('seekBar').addEventListener('pointerup', () => finishScrub());
  $('seekBar').addEventListener('pointercancel', () => finishScrub(true));
  $('seekBar').addEventListener('lostpointercapture', () => finishScrub());
  $('seekBar').addEventListener('pointermove', (event) => {
    const rect = $('seekBar').getBoundingClientRect();
    previewSeek(state.dragging ? Number($('seekBar').value) / 1000 : (event.clientX - rect.left) / rect.width);
  });
  $('seekBar').addEventListener('pointerleave', () => { if (!state.dragging) $('seekPreview').hidden = true; });
  $('seekBar').addEventListener('blur', () => { $('seekPreview').hidden = true; });

  document.addEventListener('pointerdown', (event) => {
    state.keyboard = false;
    state.wakeOnly = event.pointerType === 'touch' && stage.contains(event.target) && stage.classList.contains('controls-hidden');
    menus.forEach((menu) => { if (!menu.contains(event.target)) menu.open = false; });
    showControls();
  }, true);
  stage.addEventListener('pointerdown', showControls, true);
  stage.addEventListener('pointermove', showControls);
  stage.addEventListener('pointerup', showControls);
  controls.addEventListener('focusin', showControls);
  controls.addEventListener('focusout', () => queueMicrotask(showControls));
  [video, $('centerPlay')].forEach((surface) => {
    surface.addEventListener('click', (event) => {
      if (state.wakeOnly) { state.wakeOnly = false; return; }
      clearTimeout(state.clickTimer);
      if (event.detail === 0) togglePlay();
      else if (event.detail === 1) state.clickTimer = setTimeout(togglePlay, 350);
    });
    surface.addEventListener('dblclick', () => { clearTimeout(state.clickTimer); toggleFullscreen(); });
  });
  document.addEventListener('keydown', (event) => {
    state.keyboard = true;
    showControls();
    if (event.key === 'Escape') {
      menus.forEach((menu) => {
        if (menu.open) { menu.querySelector('summary').focus(); menu.open = false; event.preventDefault(); }
      });
      return;
    }
    if (event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.altKey
      || event.target.closest('input, select, textarea, button, a, summary, [role="button"], [contenteditable]:not([contenteditable="false"])')) return;
    const key = event.key.toLowerCase();
    let action;
    if (event.shiftKey) {
      if (key === 'p') action = () => switchItem(-1);
      if (key === 'n') action = () => switchItem(1);
    } else {
      if (key === ' ' || key === 'k') action = togglePlay;
      if (key === 'arrowleft') action = () => seekTo(video.currentTime - 5);
      if (key === 'arrowright') action = () => seekTo(video.currentTime + 5);
      if (key === 'arrowup' || key === 'arrowdown') action = () => {
        video.volume = clamp(Math.round((video.volume + (key === 'arrowup' ? 0.05 : -0.05)) * 100) / 100, 0, 1);
        video.muted = video.volume === 0;
        notify(`音量 ${Math.round(video.volume * 100)}%`);
      };
      if (key === 'm') action = () => $('muteButton').click();
      if (key === 'f') action = toggleFullscreen;
      if (/^[0-9]$/.test(key)) action = () => seekTo(Number(key) / 10 * video.duration);
    }
    if (!action) return;
    event.preventDefault();
    if (event.repeat && [' ', 'k', 'm', 'f', 'p', 'n'].includes(key)) return;
    action();
  });
  window.addEventListener('pagehide', () => saveProgress(true));
  document.addEventListener('visibilitychange', () => { if (document.hidden) saveProgress(true); else showControls(); });
  video.volume = settings.volume;
  video.muted = settings.muted;
  video.playbackRate = settings.rate;
  syncSettings();
  renderItem();
  refresh();
})();
