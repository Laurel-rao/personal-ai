(() => {
  "use strict";

  const PAGE_SIZE = 100;
  const LIST_POLL_MS = 6000;
  const RUNNING_POLL_MS = 8000;
  const LOG_POLL_MS = 2000;
  const NOTIFY_COOLDOWN_MS = 8000;

  const KIND_LABELS = Object.freeze({
    download: "下载",
    refresh: "资料刷新",
    photos: "写真查询",
    works: "作品查询",
    books: "写真集书目",
    preview: "写真集预览",
    pack: "PDF 打包",
    covers: "封面更新",
  });
  const STATUS_LABELS = Object.freeze({
    running: "运行中",
    success: "成功",
    failed: "失败",
    cancelled: "已取消",
  });
  const BULK_ACTIONS = Object.freeze({
    retry_failed: { done: "已重试" },
    cancel_running: { done: "已取消" },
    clear_done: { done: "已清理" },
  });

  const context = window.personalAI || {};
  const els = {
    denied: document.getElementById("tkDenied"),
    content: document.getElementById("tkContent"),
    kind: document.getElementById("tkKind"),
    status: document.getElementById("tkStatus"),
    search: document.getElementById("tkSearch"),
    refresh: document.getElementById("tkRefresh"),
    count: document.getElementById("tkCount"),
    panel: document.getElementById("tkPanel"),
    list: document.getElementById("tkList"),
    updated: document.getElementById("tkUpdated"),
    pager: document.getElementById("tkPager"),
    prev: document.getElementById("tkPrev"),
    next: document.getElementById("tkNext"),
    pages: document.getElementById("tkPages"),
    range: document.getElementById("tkRange"),
    drawer: document.getElementById("tkDrawer"),
    drawerBackdrop: document.getElementById("tkDrawerBackdrop"),
    drawerTitle: document.getElementById("tkDrawerTitle"),
    drawerMeta: document.getElementById("tkDrawerMeta"),
    drawerStatus: document.getElementById("tkDrawerStatus"),
    drawerClose: document.getElementById("tkDrawerClose"),
    drawerRefresh: document.getElementById("tkDrawerRefresh"),
    drawerHint: document.getElementById("tkDrawerHint"),
    logs: document.getElementById("tkLogs"),
    lightbox: document.getElementById("tkLightbox"),
    lightboxTitle: document.getElementById("tkLightboxTitle"),
    lightboxCounter: document.getElementById("tkLightboxCounter"),
    lightboxImage: document.getElementById("tkLightboxImage"),
    lightboxPrev: document.getElementById("tkLightboxPrev"),
    lightboxNext: document.getElementById("tkLightboxNext"),
    lightboxClose: document.getElementById("tkLightboxClose"),
    lightboxDownload: document.getElementById("tkLightboxDownload"),
    lightboxCaption: document.getElementById("tkLightboxCaption"),
    toasts: document.getElementById("tkToasts"),
  };

  if (!els.list) return;

  const state = {
    kind: "",
    status: "",
    q: "",
    offset: 0,
    total: 0,
    items: [],
    loading: false,
    loadSeq: 0,
    signature: "",
    pagerSignature: "",
  };

  let accessDenied = false;
  let searchTimer = 0;
  let listTimer = 0;
  let runningTimer = 0;
  let bulkBusy = false;

  let activeLogId = "";
  let logSeq = 0;
  let logTimer = 0;
  let logTrigger = null;
  let drawerFirstLoad = true;

  let lightboxImages = [];
  let lightboxIndex = 0;
  let lightboxTrigger = null;
  let lightboxSeq = 0;

  let knownRunning = new Set();
  let runningSeeded = false;
  let runningSyncing = false;
  let notifyQueue = [];
  let notifyTimer = 0;
  let lastNotifyAt = 0;

  const reduceMotion = () => {
    try {
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch (error) {
      return false;
    }
  };

  function createElement(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clearNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function formatDate(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).replace("T", " ").slice(0, 16);
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function timeOnly(date) {
    return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  }

  function clampProgress(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(0, Math.min(1, number));
  }

  function kindLabel(value) {
    return KIND_LABELS[value] || (value ? String(value) : "未知类型");
  }

  function statusLabel(value) {
    return STATUS_LABELS[value] || (value ? String(value) : "未知状态");
  }

  function hasFilters() {
    return Boolean(state.kind || state.status || state.q);
  }

  function buildSignature(items) {
    try {
      return JSON.stringify(items.map((task) => [
        task.id,
        task.status,
        task.progress,
        task.error,
        task.finished_at,
        task.result,
      ]));
    } catch (error) {
      return String(Date.now());
    }
  }

  async function api(path, options = {}) {
    const init = {
      cache: "no-store",
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.headers || {}),
      },
    };
    const response = await fetch(path, init);
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    if (!response.ok || !data || data.success === false) {
      let message = data && data.error ? String(data.error) : "";
      if (!message) {
        message = response.status === 403
          ? "当前账号没有访问此功能的权限"
          : `请求失败（${response.status}）`;
      }
      const failure = new Error(message);
      failure.status = response.status;
      throw failure;
    }
    return data;
  }

  function canAccess() {
    if (!context.user) return true;
    if (context.admin) return true;
    const menus = Array.isArray(context.menus) ? context.menus : [];
    return menus.some((item) => item && (item.key === "idols" || item.key === "tasks"));
  }

  function showAccessDenied() {
    if (accessDenied) return;
    accessDenied = true;
    stopTimers();
    closeLogs();
    closeLightbox();
    els.content.hidden = true;
    els.denied.hidden = false;
    els.count.textContent = "";
  }

  function countOf(task, key, unit) {
    const result = task && task.result && typeof task.result === "object" ? task.result : {};
    const raw = result.count;
    let count = raw === null || raw === undefined || raw === "" ? NaN : Number(raw);
    if (!Number.isFinite(count)) {
      count = Array.isArray(result[key]) ? result[key].length : 0;
    }
    return count > 0 ? `${count} ${unit}` : "";
  }

  function taskSummary(task) {
    if (!task || typeof task !== "object") return "";
    const result = task.result && typeof task.result === "object" ? task.result : {};
    if (task.status === "failed" && task.error) return String(task.error);
    switch (task.kind) {
      case "download": {
        const total = Number(result.total) || 0;
        const finished = Number(result.finished) || 0;
        const pages = Number(result.pages) || 0;
        const failed = Number(result.failed) || 0;
        if (!total && !finished && !pages) return result.message ? String(result.message) : "";
        const parts = [`${finished}/${total || "?"} 本`];
        if (pages) parts.push(`${pages} 张`);
        if (failed) parts.push(`失败 ${failed}`);
        return parts.join(" · ");
      }
      case "refresh": {
        const updated = Array.isArray(result.updated)
          ? result.updated.filter((item) => typeof item === "string" && item)
          : [];
        if (updated.length) {
          const head = updated.slice(0, 3).join("、");
          return `更新 ${head}${updated.length > 3 ? "…" : ""}`;
        }
        if (result.message) return String(result.message);
        return result.changed ? "资料有更新" : "";
      }
      case "photos":
        return countOf(task, "photos", "张写真");
      case "works":
        return countOf(task, "works", "部作品");
      case "books":
        return countOf(task, "books", "本书目");
      case "preview":
        return countOf(task, "images", "张预览图");
      case "covers":
        return `官方 ${Number(result.official) || 0} · 截帧 ${Number(result.frame) || 0}`;
      case "pack": {
        const books = Number(result.books) || 0;
        const pages = Number(result.pages) || 0;
        const parts = [];
        if (books) parts.push(`${books} 本`);
        if (pages) parts.push(`${pages} 页`);
        if (result.layout) {
          const layouts = { auto: "自动", spread: "跨页", page: "单页" };
          parts.push(`版式 ${layouts[result.layout] || result.layout}`);
        }
        return parts.join(" · ");
      }
      default:
        return countOf(task, "items", "项");
    }
  }

  function normalizeImageSrc(value) {
    if (typeof value !== "string") return "";
    const url = value.trim();
    if (!url) return "";
    if (/^(?:javascript|vbscript):/i.test(url)) return "";
    if (/^data:text\/html/i.test(url)) return "";
    return url;
  }

  function collectImages(task) {
    const result = task && task.result && typeof task.result === "object" ? task.result : {};
    const images = [];
    const seen = new Set();
    const add = (value, label) => {
      const src = normalizeImageSrc(value);
      if (!src || seen.has(src)) return;
      seen.add(src);
      images.push({ src, label: typeof label === "string" ? label : "" });
    };
    if (Array.isArray(result.photos)) {
      result.photos.forEach((url) => add(url, "写真"));
    }
    if (Array.isArray(result.images)) {
      result.images.forEach((url) => add(url, "预览图"));
    }
    if (Array.isArray(result.books)) {
      result.books.forEach((book, index) => {
        if (!book || typeof book !== "object") return;
        add(book.cover, book.title || book.name || book.isbn || `封面 ${index + 1}`);
      });
    }
    return images;
  }

  function imageFileName(src, index) {
    try {
      const parsed = new URL(src, window.location.href);
      const segment = parsed.pathname.split("/").filter(Boolean).pop() || "";
      const name = decodeURIComponent(segment);
      if (name && /\.(?:jpe?g|png|webp|gif|avif|bmp)$/i.test(name)) return name;
    } catch (error) {
      /* 使用兜底文件名 */
    }
    return `task-image-${index + 1}.jpg`;
  }

  function buildErrorState(message) {
    const box = createElement("div", "tk-empty tk-empty--error");
    box.append(createElement("strong", null, "任务加载失败"));
    box.append(createElement("p", null, message || "请稍后重试"));
    const retry = createElement("button", "tk-btn tk-btn-sm", "重试");
    retry.type = "button";
    retry.addEventListener("click", () => loadTasks());
    box.append(retry);
    return box;
  }

  function renderList() {
    clearNode(els.list);
    if (!state.items.length) {
      const empty = createElement("div", "tk-empty");
      empty.append(createElement("strong", null, "没有符合条件的任务"));
      empty.append(createElement("p", null, hasFilters()
        ? "试试调整类型、状态或搜索关键词。"
        : "新的下载、资料刷新或查询任务会出现在这里。"));
      els.list.append(empty);
      return;
    }
    const fragment = document.createDocumentFragment();
    state.items.forEach((task) => fragment.append(buildRow(task)));
    els.list.append(fragment);
  }

  function buildRow(task) {
    const status = task.status || "";
    const row = createElement("article", "tk-row");
    row.setAttribute("role", "listitem");
    row.dataset.taskId = task.id || "";

    const dot = createElement("span", `tk-dot tk-dot--${status || "unknown"}`);
    dot.setAttribute("role", "img");
    dot.setAttribute("aria-label", `状态：${statusLabel(status)}`);
    dot.title = statusLabel(status);

    const kind = createElement("span", "tk-kind", kindLabel(task.kind));

    const main = createElement("div", "tk-main");
    const titleLine = createElement("div", "tk-title-line");
    const title = createElement("h3", "tk-title", task.title || "(无标题任务)");
    title.title = `${task.title || ""}${task.id ? `\n${task.id}` : ""}`;
    const statusChip = createElement("span", `tk-status tk-status--${status || "unknown"}`, statusLabel(status));
    titleLine.append(title, statusChip);

    const meta = createElement("div", "tk-meta");
    const playerName = task.player_name || (task.player_id ? `#${task.player_id}` : "");
    if (playerName) {
      const player = createElement("span", "tk-meta-player", playerName);
      player.title = task.player_id ? `选手编号：${task.player_id}` : playerName;
      meta.append(player);
    }
    const createdAt = formatDate(task.created_at);
    if (createdAt) {
      const time = createElement("span", "tk-meta-time", createdAt);
      const lines = [];
      if (task.created_at) lines.push(`创建：${task.created_at}`);
      if (task.started_at) lines.push(`开始：${task.started_at}`);
      if (task.finished_at) lines.push(`结束：${task.finished_at}`);
      time.title = lines.join("\n");
      meta.append(time);
    }
    const summary = taskSummary(task);
    if (summary) {
      const summaryNode = createElement(
        "span",
        task.status === "failed" ? "tk-meta-summary tk-meta-summary--error" : "tk-meta-summary",
        summary,
      );
      summaryNode.title = summary;
      meta.append(summaryNode);
    }
    main.append(titleLine);
    if (meta.childNodes.length) main.append(meta);

    if (status === "running") {
      const percent = clampProgress(task.progress) * 100;
      const progressLine = createElement("div", "tk-progress-line");
      const progress = createElement("div", "tk-progress");
      progress.setAttribute("role", "progressbar");
      progress.setAttribute("aria-label", "任务进度");
      progress.setAttribute("aria-valuemin", "0");
      progress.setAttribute("aria-valuemax", "100");
      progress.setAttribute("aria-valuenow", String(Math.round(percent)));
      const bar = createElement("span", "tk-progress-bar");
      bar.style.width = `${percent.toFixed(1)}%`;
      progress.append(bar);
      const percentText = createElement(
        "span",
        "tk-progress-text",
        percent > 0 ? `${Math.round(percent)}%` : "准备中",
      );
      progressLine.append(progress, percentText);
      main.append(progressLine);
    }

    const actions = createElement("div", "tk-actions");
    const logButton = createElement("button", "tk-btn tk-btn-sm", "日志");
    logButton.type = "button";
    logButton.setAttribute("aria-label", `查看「${task.title || "任务"}」的日志`);
    logButton.addEventListener("click", () => openLogs(task.id, logButton));
    actions.append(logButton);

    const images = collectImages(task);
    if (images.length) {
      const imageButton = createElement("button", "tk-btn tk-btn-sm", `图片 ${images.length}`);
      imageButton.type = "button";
      imageButton.setAttribute("aria-label", `查看「${task.title || "任务"}」的 ${images.length} 张图片`);
      imageButton.addEventListener("click", () => openTaskImages(task, imageButton));
      actions.append(imageButton);
    }

    if (task.player_id) {
      const playerLink = createElement("a", "tk-btn tk-btn-sm", "选手");
      playerLink.href = `/players?player_id=${encodeURIComponent(task.player_id)}`;
      playerLink.setAttribute("aria-label", `查看选手 ${playerName || task.player_id}`);
      actions.append(playerLink);
    }

    if (status === "running") {
      const cancelButton = createElement("button", "tk-btn tk-btn-sm tk-btn-danger", "取消");
      cancelButton.type = "button";
      cancelButton.setAttribute("aria-label", `取消任务「${task.title || "任务"}」`);
      cancelButton.addEventListener("click", () => cancelTask(task, cancelButton));
      actions.append(cancelButton);
    } else {
      const retryButton = createElement("button", "tk-btn tk-btn-sm", "重试");
      retryButton.type = "button";
      retryButton.setAttribute("aria-label", `重试任务「${task.title || "任务"}」`);
      retryButton.addEventListener("click", () => retryTask(task, retryButton));
      actions.append(retryButton);
    }

    row.append(dot, kind, main, actions);
    return row;
  }

  function renderCount() {
    els.count.textContent = state.total > 0 ? `共 ${state.total} 条` : "共 0 条";
  }

  function pageWindow(totalPages, current) {
    if (totalPages <= 7) {
      return Array.from({ length: totalPages }, (_, index) => index + 1);
    }
    const pages = new Set([1, totalPages, current - 1, current, current + 1]);
    if (current <= 4) {
      [2, 3, 4, 5].forEach((page) => pages.add(page));
    }
    if (current >= totalPages - 3) {
      for (let page = totalPages - 4; page <= totalPages; page += 1) pages.add(page);
    }
    const sorted = [...pages]
      .filter((page) => page >= 1 && page <= totalPages)
      .sort((left, right) => left - right);
    const output = [];
    let previous = 0;
    sorted.forEach((page) => {
      if (previous && page - previous > 1) output.push("…");
      output.push(page);
      previous = page;
    });
    return output;
  }

  function renderPager() {
    const totalPages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
    const current = Math.floor(state.offset / PAGE_SIZE) + 1;
    els.pager.hidden = state.total === 0;
    els.prev.disabled = current <= 1;
    els.next.disabled = current >= totalPages;
    const pagerKey = `${totalPages}:${current}:${state.total}`;
    if (pagerKey !== state.pagerSignature) {
      state.pagerSignature = pagerKey;
      clearNode(els.pages);
      pageWindow(totalPages, current).forEach((entry) => {
        if (entry === "…") {
          const gap = createElement("span", "tk-page-gap", "…");
          gap.setAttribute("aria-hidden", "true");
          els.pages.append(gap);
          return;
        }
        const button = createElement("button", "tk-page-btn", String(entry));
        button.type = "button";
        if (entry === current) {
          button.classList.add("is-active");
          button.setAttribute("aria-current", "page");
        }
        button.setAttribute("aria-label", `第 ${entry} 页`);
        button.addEventListener("click", () => goToPage(entry));
        els.pages.append(button);
      });
    }
    const start = state.offset + 1;
    const end = state.offset + state.items.length;
    els.range.textContent = state.items.length
      ? `${start}–${end} / ${state.total}`
      : `0 / ${state.total}`;
  }

  function scrollPanelTop() {
    if (!els.panel || typeof els.panel.getBoundingClientRect !== "function") return;
    const top = els.panel.getBoundingClientRect().top + window.scrollY - 82;
    try {
      window.scrollTo({ top: Math.max(0, top), behavior: reduceMotion() ? "auto" : "smooth" });
    } catch (error) {
      window.scrollTo(0, Math.max(0, top));
    }
  }

  function goToPage(page) {
    const totalPages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
    const target = Math.min(Math.max(1, page), totalPages);
    const offset = (target - 1) * PAGE_SIZE;
    if (offset === state.offset) return;
    state.offset = offset;
    state.signature = "";
    loadTasks({ force: true });
    scrollPanelTop();
  }

  async function loadTasks(options = {}) {
    if (accessDenied) return;
    const silent = options.silent === true;
    const force = options.force === true;
    if (options.reset === true) state.offset = 0;
    const seq = ++state.loadSeq;
    state.loading = true;
    els.refresh.disabled = true;
    els.refresh.classList.add("is-loading");
    els.refresh.textContent = silent ? "刷新" : "加载中…";
    els.list.setAttribute("aria-busy", "true");
    if (!silent && !state.items.length) {
      clearNode(els.list);
      state.signature = "";
      els.list.append(createElement("div", "tk-empty", "加载中…"));
    }

    const params = new URLSearchParams();
    if (state.kind) params.set("kind", state.kind);
    if (state.status) params.set("status", state.status);
    if (state.q) params.set("q", state.q);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(state.offset));

    try {
      const data = await api(`/api/tasks?${params.toString()}`);
      if (seq !== state.loadSeq) return;
      state.items = Array.isArray(data.items) ? data.items : [];
      const total = Number(data.total);
      state.total = Number.isFinite(total) && total >= 0 ? total : state.items.length;
      const lastOffset = state.total > 0
        ? Math.floor((state.total - 1) / PAGE_SIZE) * PAGE_SIZE
        : 0;
      if (state.total === 0 && state.offset > 0) {
        state.offset = 0;
        window.setTimeout(() => loadTasks({ silent: true, force: true }), 0);
        return;
      }
      if (state.total > 0 && state.offset > lastOffset) {
        state.offset = lastOffset;
        window.setTimeout(() => loadTasks({ silent: true, force: true }), 0);
        return;
      }
      if (runningSeeded) {
        state.items.forEach((task) => {
          if (task && task.status === "running" && task.id) knownRunning.add(task.id);
        });
      }
      const signature = buildSignature(state.items);
      if (force || signature !== state.signature) {
        state.signature = signature;
        renderList();
      }
      renderPager();
      renderCount();
      els.updated.textContent = `更新于 ${timeOnly(new Date())}`;
    } catch (error) {
      if (seq !== state.loadSeq) return;
      if (error.status === 403) {
        showAccessDenied();
        return;
      }
      if (!silent) {
        state.signature = "";
        clearNode(els.list);
        els.list.append(buildErrorState(error.message));
        els.updated.textContent = "";
      }
    } finally {
      if (seq === state.loadSeq) {
        state.loading = false;
        els.refresh.disabled = false;
        els.refresh.classList.remove("is-loading");
        els.refresh.textContent = "刷新";
        els.list.setAttribute("aria-busy", "false");
      }
    }
  }

  async function retryTask(task, button) {
    if (!task || !task.id || button.disabled) return;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "重试中…";
    try {
      const data = await api(`/api/tasks/${encodeURIComponent(task.id)}/retry`, { method: "POST" });
      toast("已创建重试任务", "success");
      state.signature = "";
      await loadTasks({ silent: true, force: true });
      if (data.task && data.task.id) openLogs(data.task.id);
    } catch (error) {
      toast(error.message || "重试失败", "error");
      button.disabled = false;
      button.textContent = original;
    }
  }

  async function cancelTask(task, button) {
    if (!task || !task.id || button.disabled) return;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "取消中…";
    try {
      await api(`/api/tasks/${encodeURIComponent(task.id)}/cancel`, { method: "POST" });
      toast("已发送取消请求", "info");
      state.signature = "";
      await loadTasks({ silent: true, force: true });
      if (activeLogId === task.id) refreshLogs(false);
    } catch (error) {
      toast(error.message || "取消失败", "error");
      button.disabled = false;
      button.textContent = original;
    }
  }

  function taskMetaText(task) {
    if (!task) return "";
    const bits = [];
    if (task.kind) bits.push(kindLabel(task.kind));
    if (task.player_name || task.player_id) bits.push(task.player_name || `#${task.player_id}`);
    if (task.created_at) bits.push(`创建 ${formatDate(task.created_at)}`);
    if (task.id) bits.push(task.id);
    return bits.join(" · ");
  }

  function openLogs(taskId, trigger) {
    if (!taskId || accessDenied) return;
    logTrigger = trigger || null;
    activeLogId = taskId;
    logSeq += 1;
    drawerFirstLoad = true;
    const known = state.items.find((item) => item.id === taskId);
    els.drawerTitle.textContent = known && known.title ? known.title : "任务日志";
    els.drawerMeta.textContent = known ? taskMetaText(known) : taskId;
    clearNode(els.drawerStatus);
    els.logs.textContent = "加载中…";
    els.drawerHint.textContent = "";
    els.drawer.hidden = false;
    els.drawerBackdrop.hidden = false;
    updateModalLock();
    els.drawerClose.focus({ preventScroll: true });
    refreshLogs(false);
    startLogPoll();
  }

  function closeLogs() {
    if (els.drawer.hidden) return;
    stopLogPoll();
    activeLogId = "";
    logSeq += 1;
    els.drawer.hidden = true;
    els.drawerBackdrop.hidden = true;
    updateModalLock();
    if (logTrigger && document.contains(logTrigger)) {
      try {
        logTrigger.focus({ preventScroll: true });
      } catch (error) {
        logTrigger.focus();
      }
    }
    logTrigger = null;
  }

  function startLogPoll() {
    stopLogPoll();
    logTimer = window.setInterval(() => {
      if (document.hidden || !activeLogId) return;
      refreshLogs(true);
    }, LOG_POLL_MS);
  }

  function stopLogPoll() {
    if (logTimer) {
      window.clearInterval(logTimer);
      logTimer = 0;
    }
  }

  function applyDrawerTask(task) {
    const status = task.status || "";
    els.drawerTitle.textContent = task.title || "任务日志";
    els.drawerMeta.textContent = taskMetaText(task);
    clearNode(els.drawerStatus);
    els.drawerStatus.append(
      createElement("span", `tk-status tk-status--${status || "unknown"}`, statusLabel(status)),
    );
    const summary = taskSummary(task);
    if (summary) {
      els.drawerStatus.append(createElement("span", "tk-drawer-summary", summary));
    }
    if (status === "running") {
      const percent = Math.round(clampProgress(task.progress) * 100);
      els.drawerStatus.append(
        createElement("span", "tk-drawer-progress", percent > 0 ? `${percent}%` : "准备中"),
      );
    }

    const logs = typeof task.logs === "string" && task.logs ? task.logs : "暂无日志";
    const nearBottom = els.logs.scrollHeight - els.logs.scrollTop - els.logs.clientHeight < 64;
    const first = drawerFirstLoad || !els.logs.textContent || els.logs.textContent === "加载中…";
    els.logs.textContent = logs;
    if (first || nearBottom) els.logs.scrollTop = els.logs.scrollHeight;
    drawerFirstLoad = false;
    els.drawerHint.textContent = status === "running"
      ? "运行中 · 每 2 秒自动刷新"
      : "已结束 · 自动刷新已停止";
    if (status !== "running") {
      stopLogPoll();
      loadTasks({ silent: true });
    }
  }

  async function refreshLogs(isPoll) {
    const id = activeLogId;
    if (!id) return;
    const seq = ++logSeq;
    try {
      const data = await api(`/api/tasks/${encodeURIComponent(id)}`);
      if (id !== activeLogId || seq !== logSeq) return;
      if (!data.task) throw new Error("任务数据为空");
      applyDrawerTask(data.task);
    } catch (error) {
      if (id !== activeLogId || seq !== logSeq) return;
      if (error.status === 403) {
        showAccessDenied();
        return;
      }
      if (error.status === 404) {
        els.logs.textContent = "任务不存在或已被清理。";
        els.drawerHint.textContent = "";
        stopLogPoll();
        return;
      }
      if (!isPoll) {
        els.logs.textContent = `日志加载失败：${error.message}`;
      }
    }
  }

  function updateModalLock() {
    const locked = !els.drawer.hidden || !els.lightbox.hidden;
    document.body.classList.toggle("tk-modal-open", locked);
  }

  function showLightbox(images, index, title, trigger) {
    if (!images.length) return;
    lightboxTrigger = trigger || null;
    lightboxImages = images;
    lightboxIndex = Math.min(Math.max(0, index), images.length - 1);
    els.lightboxTitle.textContent = title || "任务图片";
    els.lightbox.hidden = false;
    lightboxSeq += 1;
    updateModalLock();
    renderLightbox();
    els.lightboxClose.focus({ preventScroll: true });
  }

  function renderLightbox() {
    const item = lightboxImages[lightboxIndex];
    if (!item) return;
    const total = lightboxImages.length;
    els.lightboxImage.src = item.src;
    els.lightboxImage.alt = item.label
      ? `${item.label}（${lightboxIndex + 1}/${total}）`
      : `任务图片 ${lightboxIndex + 1}/${total}`;
    els.lightboxCounter.textContent = `${lightboxIndex + 1} / ${total}`;
    els.lightboxCaption.textContent = item.label || "";
    els.lightboxDownload.href = item.src;
    els.lightboxDownload.setAttribute("download", imageFileName(item.src, lightboxIndex));
    const multiple = total > 1;
    els.lightboxPrev.disabled = !multiple;
    els.lightboxNext.disabled = !multiple;
    els.lightboxPrev.hidden = !multiple;
    els.lightboxNext.hidden = !multiple;
  }

  function stepLightbox(delta) {
    if (els.lightbox.hidden || lightboxImages.length < 2) return;
    lightboxIndex = (lightboxIndex + delta + lightboxImages.length) % lightboxImages.length;
    renderLightbox();
  }

  function closeLightbox() {
    if (els.lightbox.hidden) return;
    els.lightbox.hidden = true;
    els.lightboxImage.removeAttribute("src");
    lightboxImages = [];
    lightboxIndex = 0;
    updateModalLock();
    if (lightboxTrigger && document.contains(lightboxTrigger)) {
      try {
        lightboxTrigger.focus({ preventScroll: true });
      } catch (error) {
        lightboxTrigger.focus();
      }
    }
    lightboxTrigger = null;
  }

  function openTaskImages(task, trigger) {
    const initial = collectImages(task);
    if (!initial.length) {
      toast("该任务没有可预览的图片", "info");
      return;
    }
    showLightbox(initial, 0, task.title || "任务图片", trigger);
    if (!task.id) return;
    const seq = lightboxSeq;
    api(`/api/tasks/${encodeURIComponent(task.id)}`).then((data) => {
      if (els.lightbox.hidden || seq !== lightboxSeq) return;
      const full = collectImages(data.task || {});
      if (full.length <= lightboxImages.length) return;
      const current = lightboxImages[lightboxIndex];
      lightboxImages = full;
      const found = current
        ? full.findIndex((image) => image.src === current.src)
        : -1;
      lightboxIndex = found >= 0 ? found : 0;
      if (data.task && data.task.title) els.lightboxTitle.textContent = data.task.title;
      renderLightbox();
    }).catch(() => {
      /* 列表数据已足够预览时静默忽略详情失败 */
    });
  }

  function toast(message, type, onClick) {
    if (!els.toasts) return;
    const box = createElement("div", `tk-toast tk-toast--${type || "info"}`);
    const text = createElement("span", "tk-toast-text", message);
    const close = createElement("button", "tk-toast-close", "✕");
    close.type = "button";
    close.setAttribute("aria-label", "关闭提示");
    box.append(text, close);
    let timer = 0;
    const remove = () => {
      if (timer) window.clearTimeout(timer);
      if (box.parentNode) box.remove();
    };
    timer = window.setTimeout(remove, 5200);
    close.addEventListener("click", remove);
    if (typeof onClick === "function") {
      box.classList.add("is-actionable");
      text.title = "查看任务";
      text.addEventListener("click", () => {
        remove();
        onClick();
      });
    }
    els.toasts.append(box);
    while (els.toasts.children.length > 4) {
      els.toasts.firstElementChild.remove();
    }
  }

  function requestNotificationPermission() {
    if (!("Notification" in window) || Notification.permission !== "default") return;
    try {
      const request = Notification.requestPermission();
      if (request && typeof request.catch === "function") request.catch(() => {});
    } catch (error) {
      /* 不支持时静默降级为页面提示 */
    }
  }

  function showSystemNotification(title, body, onClick) {
    if (document.visibilityState !== "visible") return false;
    if (!("Notification" in window) || Notification.permission !== "granted") return false;
    try {
      const note = new Notification(title, {
        body: body || "",
        tag: "external-data-task",
      });
      note.onclick = () => {
        try {
          note.close();
          window.focus();
        } catch (error) {
          /* 忽略 */
        }
        onClick();
      };
      window.setTimeout(() => {
        try {
          note.close();
        } catch (error) {
          /* 忽略 */
        }
      }, 8000);
      return true;
    } catch (error) {
      return false;
    }
  }

  function flushNotifications() {
    if (!notifyQueue.length) return;
    if (notifyTimer) return;
    const remaining = NOTIFY_COOLDOWN_MS - (Date.now() - lastNotifyAt);
    if (remaining > 0) {
      notifyTimer = window.setTimeout(() => {
        notifyTimer = 0;
        flushNotifications();
      }, remaining);
      return;
    }
    const batch = notifyQueue.splice(0, notifyQueue.length);
    lastNotifyAt = Date.now();
    announceFinished(batch);
  }

  function announceFinished(tasks) {
    if (!tasks.length) return;
    const first = tasks[0];
    const succeeded = tasks.filter((task) => task.status === "success").length;
    const failed = tasks.length - succeeded;
    let title;
    let body;
    if (tasks.length === 1) {
      title = `任务${first.status === "success" ? "完成" : "失败"}：${first.title || first.id || ""}`;
      body = taskSummary(first) || (first.status === "success" ? "任务已成功结束" : "任务执行失败");
    } else {
      title = `${tasks.length} 个外部数据任务已结束`;
      body = `${succeeded} 个成功${failed ? `，${failed} 个失败` : ""}`;
    }
    const openFirst = () => {
      try {
        window.focus();
      } catch (error) {
        /* 忽略 */
      }
      if (first.id) openLogs(first.id);
    };
    const notified = showSystemNotification(title, body, openFirst);
    if (!notified) {
      toast(`${title}${body ? ` · ${body}` : ""}`, failed ? "error" : "success", openFirst);
    }
    if (!document.hidden) loadTasks({ silent: true });
  }

  function queueNotification(task) {
    if (!task || !task.id) return;
    if (task.status !== "success" && task.status !== "failed") return;
    if (notifyQueue.some((item) => item.id === task.id)) return;
    notifyQueue.push(task);
    flushNotifications();
  }

  async function syncRunning() {
    if (accessDenied || runningSyncing) return;
    if (document.hidden && runningSeeded) return;
    runningSyncing = true;
    try {
      const data = await api("/api/tasks?status=running&limit=100");
      const items = Array.isArray(data.items) ? data.items : [];
      const current = new Set(
        items.map((item) => item && item.id).filter((id) => typeof id === "string" && id),
      );
      if (runningSeeded) {
        const missing = [...knownRunning].filter((id) => !current.has(id));
        if (missing.length) {
          const settled = await Promise.all(missing.map((id) => api(`/api/tasks/${encodeURIComponent(id)}`)
            .then((detail) => detail.task)
            .catch(() => null)));
          settled.forEach((task) => {
            if (task && (task.status === "success" || task.status === "failed")) {
              queueNotification(task);
            }
          });
        }
      }
      knownRunning = current;
      runningSeeded = true;
    } catch (error) {
      if (error.status === 403) showAccessDenied();
      /* 轮询失败保持静默，等待下一轮 */
    } finally {
      runningSyncing = false;
    }
  }

  function startTimers() {
    stopTimers();
    listTimer = window.setInterval(() => {
      if (document.hidden || accessDenied || state.loading) return;
      loadTasks({ silent: true });
    }, LIST_POLL_MS);
    runningTimer = window.setInterval(() => {
      if (document.hidden || accessDenied) return;
      syncRunning();
    }, RUNNING_POLL_MS);
  }

  function stopTimers() {
    if (listTimer) {
      window.clearInterval(listTimer);
      listTimer = 0;
    }
    if (runningTimer) {
      window.clearInterval(runningTimer);
      runningTimer = 0;
    }
  }

  async function runCoverUpdate(button) {
    if (bulkBusy) return;
    bulkBusy = true;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "提交中…";
    try {
      const data = await api("/api/players/covers/run", { method: "POST" });
      toast(data.task?.id ? "已开始更新视频封面" : "已提交", "success");
      state.signature = "";
      await loadTasks({ silent: true, force: true });
      await syncRunning();
    } catch (error) {
      if (error.status === 403) showAccessDenied();
      toast(error.message || "提交失败", "error");
    } finally {
      bulkBusy = false;
      button.disabled = false;
      button.textContent = original;
    }
  }

  async function runBulk(action, button) {
    const config = BULK_ACTIONS[action];
    if (!config || bulkBusy) return;
    bulkBusy = true;
    const buttons = [...document.querySelectorAll("[data-bulk]")];
    const original = button.textContent;
    buttons.forEach((item) => {
      item.disabled = true;
    });
    button.textContent = "处理中…";
    try {
      const data = await api("/api/tasks/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const count = Number(data.count) || 0;
      toast(
        count > 0 ? `${config.done} ${count} 个任务` : "没有需要处理的任务",
        count > 0 ? "success" : "info",
      );
      state.signature = "";
      await loadTasks({ silent: true, force: true });
      await syncRunning();
    } catch (error) {
      if (error.status === 403) showAccessDenied();
      toast(error.message || "批量操作失败", "error");
    } finally {
      bulkBusy = false;
      buttons.forEach((item) => {
        item.disabled = false;
      });
      button.textContent = original;
    }
  }

  function onSearchChanged() {
    const value = els.search.value.trim();
    if (value === state.q) return;
    state.q = value;
    state.offset = 0;
    state.signature = "";
    loadTasks({ force: true });
  }

  function bindEvents() {
    els.kind.addEventListener("change", () => {
      state.kind = els.kind.value;
      state.offset = 0;
      state.signature = "";
      loadTasks({ force: true });
    });
    els.status.addEventListener("change", () => {
      state.status = els.status.value;
      state.offset = 0;
      state.signature = "";
      loadTasks({ force: true });
    });
    els.search.addEventListener("input", () => {
      if (searchTimer) window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        searchTimer = 0;
        onSearchChanged();
      }, 300);
    });
    els.search.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      if (searchTimer) {
        window.clearTimeout(searchTimer);
        searchTimer = 0;
      }
      onSearchChanged();
    });
    els.search.addEventListener("search", () => {
      if (searchTimer) {
        window.clearTimeout(searchTimer);
        searchTimer = 0;
      }
      onSearchChanged();
    });
    els.refresh.addEventListener("click", () => {
      loadTasks();
      syncRunning();
    });
    els.prev.addEventListener("click", () => {
      goToPage(Math.floor(state.offset / PAGE_SIZE));
    });
    els.next.addEventListener("click", () => {
      goToPage(Math.floor(state.offset / PAGE_SIZE) + 2);
    });
    document.querySelectorAll("[data-bulk]").forEach((button) => {
      button.addEventListener("click", () => runBulk(button.dataset.bulk, button));
    });
    document.getElementById("tkRunCovers")?.addEventListener("click", (event) => runCoverUpdate(event.currentTarget));

    els.drawerBackdrop.addEventListener("click", closeLogs);
    els.drawerClose.addEventListener("click", closeLogs);
    els.drawerRefresh.addEventListener("click", () => {
      refreshLogs(false);
      if (!logTimer) startLogPoll();
    });

    els.lightboxClose.addEventListener("click", closeLightbox);
    els.lightboxPrev.addEventListener("click", () => stepLightbox(-1));
    els.lightboxNext.addEventListener("click", () => stepLightbox(1));
    els.lightbox.addEventListener("click", (event) => {
      if (event.target === els.lightbox) closeLightbox();
    });

    document.addEventListener("keydown", (event) => {
      if (!els.lightbox.hidden) {
        if (event.key === "Escape") {
          event.preventDefault();
          closeLightbox();
        } else if (event.key === "ArrowLeft") {
          event.preventDefault();
          stepLightbox(-1);
        } else if (event.key === "ArrowRight") {
          event.preventDefault();
          stepLightbox(1);
        }
        return;
      }
      if (!els.drawer.hidden && event.key === "Escape") {
        event.preventDefault();
        closeLogs();
      }
    });

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible" || accessDenied) return;
      loadTasks({ silent: true });
      syncRunning();
      flushNotifications();
    });
  }

  function init() {
    if (!canAccess()) {
      showAccessDenied();
      return;
    }
    bindEvents();
    requestNotificationPermission();
    loadTasks();
    syncRunning();
    startTimers();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
