(() => {
  "use strict";

  const STORAGE = {
    settings: "h3-video-console.settings.v3",
    draft: "h3-video-console.draft.v5",
    legacyDraft: "h3-video-console.draft.v4",
  };
  const POLL_INTERVAL_MS = 3000;
  const MAX_HISTORY = 50;

  const WORKFLOW_PROFILES = {
    "U00-minimax_h3提示词QWEN3.8群主版": {
      kind: "prompt",
      imageSlots: 9,
      minimumImages: 0,
      promptKey: "15:提示词",
      label: "H3 提示词工作流，可从 3 张参考图开始，点击 + 最多扩展至 9 张。",
    },
    "U04-minimax_h3_light2v-5图参考生视频加速版": {
      kind: "video",
      imageSlots: 5,
      minimumImages: 1,
      promptKey: "146:prompt",
      imageKeys: ["137:image", "139:image", "141:image", "148:image", "149:image"],
      label: "视频生成工作流支持 1 至 5 张参考图，已有图片可直接提交；画幅、步数与时长会一并提交。",
    },
    "minimax_h3_lightx2v_v5_15s": {
      kind: "autodl-video",
      imageSlots: 4,
      minimumImages: 1,
      promptKey: "prompt",
      imageKeys: ["ref_image_0", "ref_image_1", "ref_image_2", "ref_image_3"],
      label: "AutoDL H3 15 秒工作流：支持首帧、尾帧和最多两张连续性参考图。",
    },
  };

  const GENERIC_PROFILE = {
    kind: "generic",
    imageSlots: 9,
    minimumImages: 0,
    promptKey: "15:提示词",
    label: "自定义工作流：按通用图片与提示词字段提交。",
  };

  const elements = {
    baseUrl: document.querySelector("#baseUrl"),
    workflowId: document.querySelector("#workflowId"),
    testConnection: document.querySelector("#testConnection"),
    serviceState: document.querySelector("#serviceState"),
    serviceStateText: document.querySelector("#serviceStateText"),
    imageGrid: document.querySelector("#imageGrid"),
    imageCount: document.querySelector("#imageCount"),
    slotCount: document.querySelector("#slotCount"),
    imageSlotTemplate: document.querySelector("#imageSlotTemplate"),
    historyPicker: document.querySelector("#historyPicker"),
    historyPickerGrid: document.querySelector("#historyPickerGrid"),
    historyPickerStatus: document.querySelector("#historyPickerStatus"),
    historyPickerClose: document.querySelector("#historyPickerClose"),
    historyPickerSearch: document.querySelector("#historyPickerSearch"),
    historyPickerCount: document.querySelector("#historyPickerCount"),
    historyPickerSentinel: document.querySelector("#historyPickerSentinel"),
    workflowModeNote: document.querySelector("#workflowModeNote"),
    videoSettings: document.querySelector("#videoSettings"),
    stepsInput: document.querySelector("#stepsInput"),
    widthInput: document.querySelector("#widthInput"),
    heightInput: document.querySelector("#heightInput"),
    durationInput: document.querySelector("#durationInput"),
    resolutionInput: document.querySelector("#resolutionInput"),
    seedInput: document.querySelector("#seedInput"),
    musicPreset: document.querySelector("#musicPreset"),
    promptInput: document.querySelector("#promptInput"),
    promptLabel: document.querySelector("#promptLabel"),
    promptTemplate: document.querySelector("#promptTemplate"),
    loadWarringPrompt: document.querySelector("#loadWarringPrompt"),
    promptCount: document.querySelector("#promptCount"),
    formHint: document.querySelector("#formHint"),
    generateButton: document.querySelector("#generateButton"),
    generateFramesButton: document.querySelector("#generateFramesButton"),
    frameGenerationState: document.querySelector("#frameGenerationState"),
    emptyProgress: document.querySelector("#emptyProgress"),
    taskProgress: document.querySelector("#taskProgress"),
    stopPolling: document.querySelector("#stopPolling"),
    taskBadge: document.querySelector("#taskBadge"),
    taskTitle: document.querySelector("#taskTitle"),
    elapsedTime: document.querySelector("#elapsedTime"),
    progressTrack: document.querySelector("#progressTrack"),
    progressFill: document.querySelector("#progressFill"),
    promptIdValue: document.querySelector("#promptIdValue"),
    pollCountValue: document.querySelector("#pollCountValue"),
    updatedAtValue: document.querySelector("#updatedAtValue"),
    resultGallery: document.querySelector("#resultGallery"),
    rawResult: document.querySelector("#rawResult"),
    rawResultPanel: document.querySelector("#rawResultPanel"),
    historyBody: document.querySelector("#historyBody"),
    historyEmpty: document.querySelector("#historyEmpty"),
    historyTab: document.querySelector("#historyTab"),
    assetsTab: document.querySelector("#assetsTab"),
    historyView: document.querySelector("#historyView"),
    assetsView: document.querySelector("#assetsView"),
    assetCount: document.querySelector("#assetCount"),
    assetsGrid: document.querySelector("#assetsGrid"),
    assetsEmpty: document.querySelector("#assetsEmpty"),
    refreshAssets: document.querySelector("#refreshAssets"),
    trackPromptId: document.querySelector("#trackPromptId"),
    trackButton: document.querySelector("#trackButton"),
    clearHistory: document.querySelector("#clearHistory"),
    historyActions: document.querySelector(".history-actions"),
    toastRegion: document.querySelector("#toastRegion"),
  };

  const state = {
    images: Array.from({ length: 9 }, () => ({ value: "", preview: "", uploading: false })),
    visibleImageSlots: 3,
    history: [],
    assets: [],
    activeTask: null,
    pollTimer: null,
    elapsedTimer: null,
    connectionAbort: null,
    frameGenerating: false,
  };

  function normalizeBaseUrl(value) {
    return String(value || "").trim().replace(/\/+$/, "");
  }

  function getWorkflowProfile(workflowId = elements.workflowId.value) {
    return WORKFLOW_PROFILES[String(workflowId || "").trim()] || GENERIC_PROFILE;
  }

  function isVideoProfile(profile = getWorkflowProfile()) {
    return profile.kind === "video" || profile.kind === "autodl-video";
  }

  function isAutoDLProfile(profile = getWorkflowProfile()) {
    return profile.kind === "autodl-video";
  }

  function imageSlotLimit(profile = getWorkflowProfile()) {
    return profile.imageSlots || 9;
  }

  function previewForStoredImage(value) {
    if (!value) return "";
    if (isPreviewableUrl(value)) return value;
    const baseUrl = normalizeBaseUrl(elements.baseUrl.value);
    if (!baseUrl) return "";
    return `${baseUrl}/api/comfy/view?filename=${encodeURIComponent(value)}&type=input`;
  }

  function parseJSON(value, fallback) {
    if (value === null || value === undefined || value === "") return fallback;
    try {
      const parsed = JSON.parse(value);
      return parsed === null ? fallback : parsed;
    } catch {
      return fallback;
    }
  }

  function saveSettings() {
    localStorage.setItem(
      STORAGE.settings,
      JSON.stringify({
        baseUrl: normalizeBaseUrl(elements.baseUrl.value),
        workflowId: elements.workflowId.value.trim(),
      }),
    );
  }

  function saveDraft() {
    localStorage.setItem(
      STORAGE.draft,
      JSON.stringify({
        prompt: elements.promptInput.value,
        images: state.images.map((image) =>
          image.value.startsWith("data:image/") ? "" : image.value,
        ),
        visibleImageSlots: state.visibleImageSlots,
        videoSettings: {
          steps: elements.stepsInput.value,
          width: elements.widthInput.value,
          height: elements.heightInput.value,
          duration: elements.durationInput.value,
          resolution: elements.resolutionInput?.value || "768p竖",
          seed: elements.seedInput?.value || "212238359716024",
          musicPreset: elements.musicPreset?.value || "low-rise",
        },
      }),
    );
  }

  async function persistHistoryItem(item) {
    try {
      const response = await fetch("/api/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(item),
      });
      if (!response.ok) throw new Error(`历史保存失败（${response.status}）`);
    } catch (error) {
      showToast(error.message || "历史保存失败", "error");
    }
  }

  function loadSavedState() {
    const settings = parseJSON(localStorage.getItem(STORAGE.settings), {});
    const draft = parseJSON(
      localStorage.getItem(STORAGE.draft) || localStorage.getItem(STORAGE.legacyDraft),
      {},
    );

    if (settings.baseUrl) elements.baseUrl.value = settings.baseUrl;
    if (settings.workflowId) elements.workflowId.value = settings.workflowId;
    if (typeof draft.prompt === "string") elements.promptInput.value = draft.prompt;
    if (Array.isArray(draft.images)) {
      draft.images.slice(0, 9).forEach((value, index) => {
        if (typeof value === "string" && value) {
          state.images[index].value = value;
          state.images[index].preview = previewForStoredImage(value);
        }
      });
    }
    if (draft.videoSettings && typeof draft.videoSettings === "object") {
      elements.stepsInput.value = draft.videoSettings.steps || elements.stepsInput.value;
      elements.widthInput.value = draft.videoSettings.width || elements.widthInput.value;
      elements.heightInput.value = draft.videoSettings.height || elements.heightInput.value;
      elements.durationInput.value = draft.videoSettings.duration || elements.durationInput.value;
      if (elements.resolutionInput) elements.resolutionInput.value = draft.videoSettings.resolution || elements.resolutionInput.value;
      if (elements.seedInput) elements.seedInput.value = draft.videoSettings.seed || elements.seedInput.value;
      if (elements.musicPreset) elements.musicPreset.value = draft.videoSettings.musicPreset || elements.musicPreset.value;
    }
    const lastFilledIndex = state.images.reduce(
      (highest, image, index) => (image.value ? index : highest),
      -1,
    );
    const profile = getWorkflowProfile();
    const savedSlotCount = Number.isInteger(draft.visibleImageSlots) ? draft.visibleImageSlots : 3;
    state.visibleImageSlots = isVideoProfile(profile)
      ? profile.imageSlots
      : Math.min(imageSlotLimit(profile), Math.max(3, savedSlotCount, lastFilledIndex + 1));
  }

  function setServiceState(status, label) {
    elements.serviceState.dataset.state = status;
    elements.serviceStateText.textContent = label;
  }

  function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast${type === "error" ? " error" : ""}`;
    toast.textContent = message;
    elements.toastRegion.append(toast);
    window.setTimeout(() => toast.remove(), 3600);
  }

  function formatClock(dateValue) {
    const date = new Date(dateValue);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(date);
  }

  function formatElapsed(milliseconds) {
    const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
    const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
    const seconds = String(totalSeconds % 60).padStart(2, "0");
    return `${minutes}:${seconds}`;
  }

  function statusLabel(status) {
    return {
      submitting: "提交中",
      pending: "生成中",
      completed: "已完成",
      error: "失败",
      stopped: "已停止",
    }[status] || "等待中";
  }

  function isPreviewableUrl(value) {
    return /^(https?:\/\/|data:image\/|blob:)/i.test(value);
  }

  function setImageSlot(index, patch) {
    state.images[index] = { ...state.images[index], ...patch };
    updateImageSlot(index);
    updateFormState();
    saveDraft();
  }

  function applyWorkflowProfile({ rebuild = true } = {}) {
    const profile = getWorkflowProfile();
    const videoMode = isVideoProfile(profile);
    elements.workflowModeNote.textContent = profile.label;
    elements.workflowModeNote.dataset.kind = profile.kind;
    elements.videoSettings.hidden = !videoMode;
    document.querySelectorAll(".autodl-only-field").forEach((field) => {
      field.hidden = !isAutoDLProfile(profile);
    });
    if (elements.generateFramesButton) {
      elements.generateFramesButton.hidden = !isAutoDLProfile(profile);
    }
    elements.promptLabel.textContent = videoMode ? "视频提示词" : "提示词";
    elements.promptInput.placeholder = videoMode
      ? "粘贴 H3 生成的视频提示词，描述人物、场景、动作、镜头与声音……"
      : "描述人物、场景、动作、镜头、对白与声音……";
    const nextSlots = videoMode
      ? profile.imageSlots
      : Math.min(imageSlotLimit(profile), Math.max(3, state.visibleImageSlots));
    const shouldRebuild = rebuild && nextSlots !== state.visibleImageSlots;
    state.visibleImageSlots = nextSlots;
    if (shouldRebuild) rebuildImageSlots();
    else if (rebuild) renderAddSlotButton();
    updateFormState();
  }

  function updateImageSlot(index) {
    const slot = elements.imageGrid.children[index];
    if (!slot) return;
    const imageState = state.images[index];
    const image = slot.querySelector("img");
    const placeholder = slot.querySelector(".image-placeholder");
    const overlay = slot.querySelector(".upload-overlay");
    const remove = slot.querySelector(".remove-image");
    const urlInput = slot.querySelector(".url-field input");
    const hasValue = Boolean(imageState.value);

    slot.dataset.state = imageState.uploading ? "uploading" : hasValue ? "ready" : "empty";
    overlay.hidden = !imageState.uploading;
    remove.hidden = !hasValue || imageState.uploading;
    placeholder.hidden = hasValue || imageState.uploading;
    urlInput.value = imageState.value;

    if (imageState.preview && isPreviewableUrl(imageState.preview)) {
      image.src = imageState.preview;
      image.alt = `参考图 ${index + 1}`;
      image.hidden = false;
    } else {
      image.removeAttribute("src");
      image.hidden = true;
    }
  }

  function createImageSlot(index) {
    const fragment = elements.imageSlotTemplate.content.cloneNode(true);
    const slot = fragment.querySelector(".image-slot");
    const preview = fragment.querySelector(".image-preview");
    const fileInput = fragment.querySelector(".file-input");
    const urlInput = fragment.querySelector(".url-field input");
    const remove = fragment.querySelector(".remove-image");
    const historyPick = fragment.querySelector(".history-pick-button");
    fragment.querySelector(".slot-number").textContent = String(index + 1).padStart(2, "0");

    historyPick.addEventListener("click", () => openHistoryPicker(index));

    preview.addEventListener("click", (event) => {
      if (event.target.closest(".remove-image")) return;
      fileInput.click();
    });
    fileInput.addEventListener("change", () => {
      const [file] = fileInput.files;
      if (file) uploadImage(index, file);
      fileInput.value = "";
    });
    urlInput.addEventListener("change", () => {
      const value = urlInput.value.trim();
      setImageSlot(index, { value, preview: isPreviewableUrl(value) ? value : "" });
    });
    urlInput.addEventListener("input", () => {
      state.images[index].value = urlInput.value.trim();
      state.images[index].preview = isPreviewableUrl(state.images[index].value)
        ? state.images[index].value
        : "";
      updateFormState();
    });
    urlInput.addEventListener("blur", () => {
      updateImageSlot(index);
      saveDraft();
    });
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      setImageSlot(index, { value: "", preview: "", uploading: false });
    });

    ["dragenter", "dragover"].forEach((eventName) => {
      preview.addEventListener(eventName, (event) => {
        event.preventDefault();
        if (!state.images[index].uploading) slot.dataset.state = "drag";
      });
    });
    ["dragleave", "drop"].forEach((eventName) => {
      preview.addEventListener(eventName, (event) => {
        event.preventDefault();
        updateImageSlot(index);
      });
    });
    preview.addEventListener("drop", (event) => {
      const [file] = event.dataTransfer.files;
      if (file && file.type.startsWith("image/")) uploadImage(index, file);
    });

    elements.imageGrid.append(fragment);
    updateImageSlot(index);
  }

  function renderAddSlotButton() {
    elements.imageGrid.querySelector(".add-slot-button")?.remove();
    const profile = getWorkflowProfile();
    if (isVideoProfile(profile) || state.visibleImageSlots >= imageSlotLimit(profile)) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "add-slot-button";
    button.setAttribute("aria-label", "增加参考图");
    button.title = "增加参考图";
    button.innerHTML = '<span aria-hidden="true">+</span>';
    button.addEventListener("click", () => {
      const nextIndex = state.visibleImageSlots;
      state.visibleImageSlots += 1;
      button.remove();
      createImageSlot(nextIndex);
      renderAddSlotButton();
      updateFormState();
      saveDraft();
    });
    elements.imageGrid.append(button);
  }

  function rebuildImageSlots() {
    elements.imageGrid.replaceChildren();
    for (let index = 0; index < state.visibleImageSlots; index += 1) createImageSlot(index);
    renderAddSlotButton();
  }

  function initializeImageSlots() {
    rebuildImageSlots();
  }

  const picker = {
    index: 0,
    page: 0,
    pageSize: 50,
    query: "",
    total: 0,
    loaded: 0,
    loading: false,
    finished: false,
  };
  let pickerSearchTimer = null;
  let pickerObserver = null;

  function appendHistoryCards(images) {
    images.forEach((image) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "history-picker-card";
      card.title = image.prompt;
      const thumb = document.createElement("img");
      thumb.src = image.thumb;
      thumb.alt = "历史生成图片";
      thumb.loading = "lazy";
      const meta = document.createElement("span");
      meta.textContent = image.prompt || "生成图片";
      card.append(thumb, meta);
      card.addEventListener("click", () => pickHistoryImage(picker.index, image));
      elements.historyPickerGrid.append(card);
    });
  }

  function updatePickerStatus() {
    const status = elements.historyPickerStatus;
    const count = elements.historyPickerCount;
    if (picker.total > 0) {
      count.textContent = `${elements.historyPickerGrid.children.length} 张可选 · 共 ${picker.total} 条`;
      status.textContent = picker.finished
        ? "已全部加载，点击图片即设为参考图"
        : `已加载 ${picker.loaded} 张，继续下滚加载更多；点击图片即设为参考图 ${picker.index + 1}`;
    } else if (picker.query) {
      count.textContent = "";
      status.textContent = `没有匹配「${picker.query}」的图片`;
    } else {
      count.textContent = "";
      status.textContent = "还没有生成过的图片，先去「图片生成」生成几张吧";
    }
  }

  async function loadHistoryPage(reset) {
    if (picker.loading) return;
    picker.loading = true;
    elements.historyPickerSentinel.classList.add("loading");
    const page = reset ? 1 : picker.page + 1;
    try {
      const params = new URLSearchParams({
        include_history: "1",
        history_page: String(page),
        history_page_size: String(picker.pageSize),
      });
      if (picker.query) params.set("q", picker.query);
      const response = await fetch(`/photo/api/tasks?${params.toString()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`历史接口返回 ${response.status}`);
      const data = await response.json();
      const history = data.history || {};
      const items = history.items || [];
      picker.page = history.page || page;
      picker.total = history.total || 0;
      picker.finished = items.length === 0 || picker.page >= (history.total_pages || 1);
      if (reset) elements.historyPickerGrid.replaceChildren();
      const images = [];
      for (const item of items) {
        const output = item.outputs && item.outputs[0];
        if (output && output.url) {
          images.push({
            url: output.url,
            thumb: output.thumb_url || output.url,
            prompt: item.prompt || output.filename || "",
          });
        }
      }
      picker.loaded = reset ? images.length : picker.loaded + images.length;
      appendHistoryCards(images);
      updatePickerStatus();
    } catch (error) {
      elements.historyPickerStatus.textContent = "加载历史图片失败：" + error.message;
    } finally {
      picker.loading = false;
      elements.historyPickerSentinel.classList.remove("loading");
    }
  }

  function ensurePickerObserver() {
    if (pickerObserver) return;
    pickerObserver = new IntersectionObserver((entries) => {
      if (!elements.historyPicker.open || picker.finished || picker.loading) return;
      if (entries.some((entry) => entry.isIntersecting)) loadHistoryPage(false);
    });
    pickerObserver.observe(elements.historyPickerSentinel);
  }

  function openHistoryPicker(index) {
    picker.index = index;
    picker.page = 0;
    picker.total = 0;
    picker.loaded = 0;
    picker.loading = false;
    picker.finished = false;
    picker.query = "";
    pickerSearchTimer = null;
    elements.historyPickerSearch.value = "";
    elements.historyPickerGrid.replaceChildren();
    elements.historyPickerCount.textContent = "";
    elements.historyPickerStatus.textContent = "正在加载历史图片…";
    elements.historyPicker.showModal();
    ensurePickerObserver();
    loadHistoryPage(true);
  }

  async function pickHistoryImage(index, image) {
    try {
      const response = await fetch(image.url, { cache: "no-store" });
      if (!response.ok) throw new Error(`图片获取失败（${response.status}）`);
      const blob = await response.blob();
      const value = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error("图片读取失败"));
        reader.readAsDataURL(blob);
      });
      setImageSlot(index, { value, preview: value, uploading: false });
      elements.historyPicker.close();
      showToast(`第 ${index + 1} 张参考图已选用`);
      saveDraft();
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function uploadImage(index, file) {
    if (isAutoDLProfile()) {
      const reader = new FileReader();
      reader.onload = () => {
        const value = String(reader.result || "");
        setImageSlot(index, { value, preview: value, uploading: false });
        showToast(`参考图 ${index + 1} 已就绪`);
      };
      reader.onerror = () => {
        setImageSlot(index, { value: "", preview: "", uploading: false });
        showToast("读取图片失败", "error");
      };
      setImageSlot(index, { uploading: true, preview: URL.createObjectURL(file) });
      reader.readAsDataURL(file);
      return;
    }
    if (!normalizeBaseUrl(elements.baseUrl.value)) {
      showToast("请先填写服务地址", "error");
      return;
    }
    const localPreview = URL.createObjectURL(file);
    setImageSlot(index, { uploading: true, preview: localPreview });

    try {
      const body = new FormData();
      body.append("file", file);
      body.append("overwrite", "true");
      const response = await fetch(
        `/api/comfy/upload/file?base_url=${encodeURIComponent(normalizeBaseUrl(elements.baseUrl.value))}`,
        { method: "POST", body },
      );
      const data = await readResponse(response);
      if (!response.ok) throw new Error(extractError(data, `上传失败（${response.status}）`));
      const value = data.name || data.filename || data.path || data.url;
      if (!value) throw new Error("上传接口未返回文件名");
      setImageSlot(index, { value: String(value), preview: localPreview, uploading: false });
      setServiceState("online", "服务可用");
      showToast(`参考图 ${index + 1} 上传成功`);
    } catch (error) {
      setImageSlot(index, { value: "", preview: "", uploading: false });
      showToast(error.message || "图片上传失败", "error");
    }
  }

  async function generateReferenceFrames() {
    if (!isAutoDLProfile() || state.frameGenerating) return;
    const prompt = elements.promptInput.value.trim();
    if (!prompt) {
      showToast("先填写视频提示词，再生成首尾帧", "error");
      return;
    }
    state.frameGenerating = true;
    elements.generateFramesButton.disabled = true;
    elements.frameGenerationState.textContent = "Zero 正在生成首尾帧";
    try {
      const response = await fetch("/api/frames/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: `生成同一连续镜头的两张竖屏首尾帧。${prompt}\n图1为首帧，图2为尾帧；保持同一人物、服装、场景、光线和色彩连续，不要文字、额外人物、拼贴或分屏。`,
          size: "1024x1536",
          quality: "medium",
        }),
      });
      const data = await readResponse(response);
      if (!response.ok || !Array.isArray(data.files) || data.files.length < 2) {
        throw new Error(extractError(data, `首尾帧生成失败（${response.status}）`));
      }
      data.files.slice(0, 2).forEach((file, index) => {
        const value = String(file.data_url || "");
        if (value) setImageSlot(index, { value, preview: value, uploading: false });
      });
      state.visibleImageSlots = Math.max(state.visibleImageSlots, 4);
      rebuildImageSlots();
      data.files.slice(0, 2).forEach((file, index) => {
        const value = String(file.data_url || "");
        if (value) setImageSlot(index, { value, preview: value, uploading: false });
      });
      elements.frameGenerationState.textContent = "首帧与尾帧已就绪，可继续补充参考图";
      showToast("Zero 首尾帧生成完成");
    } catch (error) {
      elements.frameGenerationState.textContent = "首尾帧生成失败，请重试";
      showToast(error.message || "首尾帧生成失败", "error");
    } finally {
      state.frameGenerating = false;
      elements.generateFramesButton.disabled = false;
      updateFormState();
    }
  }

  function updateFormState() {
    const prompt = elements.promptInput.value.trim();
    const baseUrl = normalizeBaseUrl(elements.baseUrl.value);
    const workflowId = elements.workflowId.value.trim();
    const profile = getWorkflowProfile(workflowId);
    const imageCount = state.images.slice(0, imageSlotLimit(profile)).filter((image) => image.value.trim()).length;
    const uploading = state.images.some((image) => image.uploading);
    const enoughImages = imageCount >= profile.minimumImages;

    elements.imageCount.textContent = String(imageCount);
    elements.slotCount.textContent = String(state.visibleImageSlots);
    elements.promptCount.textContent = `${elements.promptInput.value.length} 字`;
    elements.generateButton.disabled = !prompt || !baseUrl || !workflowId || !enoughImages || uploading || state.frameGenerating || Boolean(state.activeTask?.polling);

    if (uploading) elements.formHint.textContent = "图片上传完成后即可提交";
    else if (!baseUrl) elements.formHint.textContent = "请填写服务地址";
    else if (!workflowId) elements.formHint.textContent = "请填写 Workflow ID";
    else if (!enoughImages) elements.formHint.textContent = `当前工作流需要 ${profile.minimumImages} 张参考图，还差 ${profile.minimumImages - imageCount} 张`;
    else if (!prompt) elements.formHint.textContent = "填写提示词后即可提交";
    else if (isAutoDLProfile(profile)) elements.formHint.textContent = `将提交 ${imageCount} 张 AutoDL 参考图与视频参数`;
    else elements.formHint.textContent = `将提交 ${imageCount} 张参考图${isVideoProfile(profile) ? "与视频参数" : ""}`;
  }

  async function readResponse(response) {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      return { message: text };
    }
  }

  function extractError(data, fallback) {
    if (!data) return fallback;
    if (typeof data === "string") return data;
    if (typeof data.error === "string") return data.error;
    if (data.error?.message) return data.error.message;
    return data.message || data.detail || fallback;
  }

  async function checkConnection() {
    const baseUrl = normalizeBaseUrl(elements.baseUrl.value);
    if (!baseUrl) {
      showToast("请填写服务地址", "error");
      return;
    }
    saveSettings();
    elements.testConnection.disabled = true;
    elements.testConnection.textContent = "检查中";
    setServiceState("idle", "正在连接");

    if (state.connectionAbort) state.connectionAbort.abort();
    state.connectionAbort = new AbortController();
    const timeout = window.setTimeout(() => state.connectionAbort.abort(), 10000);
    try {
      const response = await fetch(`/api/service/check?base_url=${encodeURIComponent(baseUrl)}`, {
        method: "GET",
        cache: "no-store",
        signal: state.connectionAbort.signal,
      });
      if (!response.ok) throw new Error(`服务返回 ${response.status}`);
      setServiceState("online", "服务可用");
      showToast("连接检查通过");
    } catch (error) {
      setServiceState("error", "连接失败");
      showToast(error.name === "AbortError" ? "连接检查超时" : error.message, "error");
    } finally {
      window.clearTimeout(timeout);
      elements.testConnection.disabled = false;
      elements.testConnection.textContent = "检查连接";
    }
  }

  async function loadWarringRef2VAPrompt() {
    elements.loadWarringPrompt.disabled = true;
    elements.loadWarringPrompt.textContent = "载入中";
    try {
      const isFirstChapter = elements.promptTemplate.value === "meeting-chase";
      const templateUrl = isFirstChapter
        ? "/templates/warring-states-01-meeting-chase-ref2va.txt"
        : "/templates/warring-states-02-command-transition-ref2va.txt";
      const response = await fetch(templateUrl, { cache: "no-store" });
      if (!response.ok) throw new Error(`模板读取失败（${response.status}）`);
      elements.durationInput.value = "15";
      elements.promptInput.value = (await response.text()).trim();
      updateFormState();
      saveDraft();
      showToast(`已载入战国 ${isFirstChapter ? "01 双人交错特写" : "02 喝止转场"} Ref2VA`);
    } catch (error) {
      showToast(error.message || "模板读取失败", "error");
    } finally {
      elements.loadWarringPrompt.disabled = false;
      elements.loadWarringPrompt.textContent = "载入战国 Ref2VA";
    }
  }

  function buildMusicPrompt(prompt) {
    if (!isAutoDLProfile() || elements.musicPreset?.value === "none") return prompt;
    const music = {
      "low-rise": "音乐从低沉克制开始：前段以低音弦乐和稀疏脉冲为主；镜头上摇时逐渐加入温暖弦乐、木管和渐强节奏；镜头打开山谷后转为明亮、激昂、欢快的电影感主题，转折平滑、无歌词。",
      ambient: "使用自然环境氛围音乐，保持轻柔、开阔并与镜头运动同步。",
    }[elements.musicPreset.value];
    return `${prompt}\n\n音乐设计：${music}`;
  }

  function buildInputValues() {
    const profile = getWorkflowProfile();
    const values = {};
    state.images.slice(0, imageSlotLimit(profile)).forEach((image, index) => {
      const value = image.value.trim();
      if (!value) return;
      const key = profile.imageKeys?.[index] || `${index + 1}:image`;
      values[key] = value;
    });
    const prompt = buildMusicPrompt(elements.promptInput.value.trim());
    values[profile.promptKey] = prompt;
    if (isAutoDLProfile(profile)) {
      values.duration = parsePositiveInteger(elements.durationInput.value, 15);
      values.resolution = elements.resolutionInput?.value || "768p竖";
      values.seed = parsePositiveInteger(elements.seedInput?.value, 212238359716024);
      values.prompt = prompt;
    }
    if (isVideoProfile(profile)) {
      values["124:steps"] = parsePositiveInteger(elements.stepsInput.value, 12);
      values["145:自定义宽"] = parsePositiveInteger(elements.widthInput.value, 864);
      values["145:自定义高"] = parsePositiveInteger(elements.heightInput.value, 480);
      values["147:value"] = parsePositiveInteger(elements.durationInput.value, 10);
    }
    return values;
  }

  function parsePositiveInteger(value, fallback) {
    const number = Number.parseInt(value, 10);
    return Number.isFinite(number) && number > 0 ? number : fallback;
  }

  async function generateVideo() {
    const baseUrl = normalizeBaseUrl(elements.baseUrl.value);
    const workflowId = elements.workflowId.value.trim();
    const prompt = elements.promptInput.value.trim();
    const profile = getWorkflowProfile(workflowId);
    const imageCount = state.images.slice(0, imageSlotLimit(profile)).filter((image) => image.value.trim()).length;
    if (!baseUrl || !workflowId || !prompt || imageCount < profile.minimumImages) return;

    saveSettings();
    saveDraft();
    stopPolling(false);
    const createdAt = new Date().toISOString();
    const task = {
      id: `local-${Date.now()}`,
      promptId: "",
      baseUrl,
      workflowId,
      workflowKind: profile.kind,
      prompt,
      images: state.images
        .slice(0, imageSlotLimit(profile))
        .map((image, index) => (image.value.startsWith("data:image/") ? `inline-image-${index + 1}` : image.value))
        .filter(Boolean),
      status: "submitting",
      createdAt,
      updatedAt: createdAt,
      pollCount: 0,
      result: null,
      error: "",
      polling: true,
    };
    state.activeTask = task;
    renderActiveTask();
    updateFormState();

    try {
      const response = await fetch("/api/workflow/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_url: baseUrl,
          workflow_id: workflowId,
          input_values: buildInputValues(),
          metadata: { prompt, images: task.images, workflowKind: profile.kind, createdAt },
        }),
      });
      const data = await readResponse(response);
      if (!response.ok) throw new Error(extractError(data, `提交失败（${response.status}）`));
      if (!data.prompt_id) throw new Error(extractError(data, "接口未返回 prompt_id"));

      task.id = data.prompt_id;
      task.promptId = data.prompt_id;
      task.status = "pending";
      task.updatedAt = new Date().toISOString();
      task.result = data;
      upsertHistory(task);
      setServiceState("online", "服务可用");
      showToast("任务已提交，开始轮询结果");
      renderActiveTask();
      schedulePoll(400);
    } catch (error) {
      task.status = "error";
      task.error = error.message || "任务提交失败";
      task.updatedAt = new Date().toISOString();
      task.polling = false;
      upsertHistory(task);
      setServiceState("error", "请求失败");
      showToast(task.error, "error");
      renderActiveTask();
    }
  }

  function schedulePoll(delay = POLL_INTERVAL_MS) {
    window.clearTimeout(state.pollTimer);
    if (!state.activeTask?.polling || !state.activeTask.promptId) return;
    state.pollTimer = window.setTimeout(pollActiveTask, delay);
  }

  async function pollActiveTask() {
    const task = state.activeTask;
    if (!task?.polling || !task.promptId) return;
    task.pollCount += 1;
    task.updatedAt = new Date().toISOString();
    renderActiveTask();

    try {
      const response = await fetch(
        `/api/workflow/result?prompt_id=${encodeURIComponent(task.promptId)}&base_url=${encodeURIComponent(task.baseUrl)}`,
        { cache: "no-store" },
      );
      const data = await readResponse(response);
      if (!response.ok) throw new Error(extractError(data, `轮询失败（${response.status}）`));
      task.result = data;
      task.updatedAt = new Date().toISOString();

      const failed = data.success === false || data.error || data.status === "error" || data.status === "failed";
      const pending = data.pending === true || data.status === "pending" || data.status === "running" || data.status === "queued";
      const assets = extractMedia(data, task.baseUrl);

      if (failed) {
        task.status = "error";
        task.error = extractError(data, "生成任务失败");
        task.polling = false;
      } else if (!pending && (assets.length > 0 || data.success === true)) {
        task.status = "completed";
        task.polling = false;
      } else {
        task.status = "pending";
      }

      upsertHistory(task);
      renderActiveTask();
      if (task.polling) schedulePoll();
      else if (task.status === "completed") showToast("视频生成完成");
      else if (task.status === "error") showToast(task.error, "error");
    } catch (error) {
      task.error = error.message || "轮询请求失败";
      task.status = "pending";
      task.updatedAt = new Date().toISOString();
      upsertHistory(task);
      renderActiveTask();
      schedulePoll(5000);
    }
  }

  function stopPolling(markStopped = true) {
    window.clearTimeout(state.pollTimer);
    window.clearInterval(state.elapsedTimer);
    state.pollTimer = null;
    state.elapsedTimer = null;
    if (state.activeTask) {
      state.activeTask.polling = false;
      if (markStopped && state.activeTask.status === "pending") state.activeTask.status = "stopped";
      if (markStopped) upsertHistory(state.activeTask);
    }
    updateFormState();
    renderActiveTask();
  }

  function extractMedia(data, baseUrl) {
    const found = new Set();
    const keys = new Set(["url", "video_url", "image_url", "download_url", "file_url", "src"]);

    function visit(value, key = "") {
      if (typeof value === "string") {
        const looksLikeMedia = /\.(mp4|webm|mov|m4v|png|jpe?g|webp|gif)(\?|#|$)/i.test(value);
        if ((keys.has(key) || looksLikeMedia) && !value.startsWith("data:")) {
          try {
            found.add(new URL(value, `${baseUrl}/`).href);
          } catch {
            // Ignore malformed media values.
          }
        }
        return;
      }
      if (Array.isArray(value)) {
        value.forEach((item) => visit(item, key));
        return;
      }
      if (value && typeof value === "object") {
        Object.entries(value).forEach(([childKey, child]) => visit(child, childKey));
      }
    }

    visit(data);
    return [...found];
  }

  function mediaPreviewUrl(task, index, fallbackUrl) {
    const taskId = String(task?.promptId || task?.id || "").trim();
    const supportsProxy = /^https:\/\/[^/]+\.cos\.ap-beijing\.myqcloud\.com\//i.test(fallbackUrl || "");
    return taskId && supportsProxy ? `/api/media?task_id=${encodeURIComponent(taskId)}&index=${index}` : fallbackUrl;
  }

  function extractTextResults(data) {
    const found = [];

    function visit(value) {
      if (Array.isArray(value)) {
        value.forEach(visit);
        return;
      }
      if (!value || typeof value !== "object") return;
      if (value.type === "text" && typeof value.text === "string" && value.text.trim()) {
        found.push(value.text.trim());
      }
      Object.values(value).forEach(visit);
    }

    visit(data);
    return [...new Set(found)];
  }

  function formatGeneratedText(value) {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }

  function renderMedia(task) {
    elements.resultGallery.replaceChildren();
    const assets = extractMedia(task.result, task.baseUrl);
    assets.forEach((url, index) => {
      const wrapper = document.createElement("div");
      wrapper.className = "result-item";
      const isVideo = /\.(mp4|webm|mov|m4v)(\?|#|$)/i.test(url);
      const media = document.createElement(isVideo ? "video" : "img");
      media.src = mediaPreviewUrl(task, index, url);
      if (isVideo) {
        media.controls = true;
        media.preload = "metadata";
      } else {
        media.alt = "生成结果";
      }
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = "打开原始文件";
      wrapper.append(media, link);
      elements.resultGallery.append(wrapper);
    });

    extractTextResults(task.result).forEach((text) => {
      const result = document.createElement("section");
      result.className = "text-result";
      const heading = document.createElement("h4");
      heading.textContent = (task.workflowKind || getWorkflowProfile(task.workflowId).kind) === "prompt"
        ? "生成的 H3 提示词"
        : "文本输出";
      const output = document.createElement("pre");
      output.textContent = formatGeneratedText(text);
      result.append(heading, output);
      elements.resultGallery.append(result);
    });
  }

  function renderActiveTask() {
    const task = state.activeTask;
    elements.emptyProgress.hidden = Boolean(task);
    elements.taskProgress.hidden = !task;
    elements.stopPolling.hidden = !task?.polling;
    window.clearInterval(state.elapsedTimer);
    state.elapsedTimer = null;

    if (!task) return;
    elements.taskBadge.textContent = statusLabel(task.status);
    elements.taskBadge.dataset.status = task.status;
    const hasTextOutput = extractTextResults(task.result).length > 0;
    const isPromptTask = (task.workflowKind || getWorkflowProfile(task.workflowId).kind) === "prompt";
    elements.taskTitle.textContent = task.error || {
      submitting: "正在提交任务",
      pending: "工作流正在运行",
      completed: isPromptTask && hasTextOutput ? "H3 提示词已生成" : "生成结果已就绪",
      stopped: "已暂停自动轮询",
      error: "任务未能完成",
    }[task.status] || "等待任务状态";
    elements.promptIdValue.textContent = task.promptId || "等待接口返回";
    elements.promptIdValue.title = task.promptId || "";
    elements.pollCountValue.textContent = `${task.pollCount || 0} 次`;
    elements.updatedAtValue.textContent = formatClock(task.updatedAt);
    elements.rawResult.textContent = task.result ? JSON.stringify(task.result, null, 2) : "等待接口返回……";
    elements.progressTrack.dataset.indeterminate = String(task.status === "submitting" || task.status === "pending");
    elements.progressFill.style.width = task.status === "completed" ? "100%" : task.status === "error" ? "100%" : "16%";
    elements.progressFill.style.background = task.status === "error" ? "var(--danger)" : "var(--accent)";
    renderMedia(task);

    const updateElapsed = () => {
      const end = task.status === "completed" || task.status === "error" || task.status === "stopped"
        ? new Date(task.updatedAt).getTime()
        : Date.now();
      elements.elapsedTime.textContent = formatElapsed(end - new Date(task.createdAt).getTime());
    };
    updateElapsed();
    if (task.polling) state.elapsedTimer = window.setInterval(updateElapsed, 1000);
    updateFormState();
  }

  function historySnapshot(task) {
    return {
      id: task.promptId || task.id,
      promptId: task.promptId,
      baseUrl: task.baseUrl,
      workflowId: task.workflowId,
      workflowKind: task.workflowKind,
      prompt: task.prompt,
      images: task.images,
      status: task.status,
      createdAt: task.createdAt,
      updatedAt: task.updatedAt,
      pollCount: task.pollCount,
      result: task.result,
      error: task.error,
    };
  }

  function upsertHistory(task) {
    const snapshot = historySnapshot(task);
    const key = snapshot.promptId || snapshot.id;
    const index = state.history.findIndex((item) => (item.promptId || item.id) === key);
    if (index >= 0) state.history.splice(index, 1);
    state.history.unshift(snapshot);
    state.history = state.history.slice(0, MAX_HISTORY);
    renderHistory();
    persistHistoryItem(snapshot);
    if (snapshot.status === "completed") loadAssets();
  }

  function renderHistory() {
    elements.historyBody.replaceChildren();
    elements.historyEmpty.hidden = state.history.length > 0;

    state.history.forEach((item) => {
      const row = document.createElement("tr");
      const status = statusLabel(item.status);
      const prompt = item.prompt || "外部任务";
      const promptId = item.promptId || "—";
      row.innerHTML = `
        <td>${escapeHtml(formatClock(item.createdAt))}</td>
        <td title="${escapeHtml(prompt)}">${escapeHtml(prompt)}</td>
        <td>${Array.isArray(item.images) ? item.images.length : 0} 张</td>
        <td><span class="status-badge" data-status="${escapeHtml(item.status)}">${escapeHtml(status)}</span></td>
        <td title="${escapeHtml(promptId)}">${escapeHtml(promptId)}</td>
        <td>
          <div class="row-actions">
            <button class="row-button view" type="button">查看</button>
            <button class="row-button resume" type="button">轮询</button>
            <button class="row-button reuse" type="button">复用</button>
            <button class="row-button delete" type="button">删除</button>
          </div>
        </td>
      `;
      row.querySelector(".view").addEventListener("click", () => viewHistory(item, false));
      row.querySelector(".resume").addEventListener("click", () => viewHistory(item, true));
      row.querySelector(".reuse").addEventListener("click", () => reuseHistory(item));
      row.querySelector(".delete").addEventListener("click", () => deleteHistory(item));
      elements.historyBody.append(row);
    });
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function viewHistory(item, resume) {
    stopPolling(false);
    state.activeTask = { ...item, polling: Boolean(resume && item.promptId), pollCount: item.pollCount || 0 };
    if (resume) {
      state.activeTask.status = "pending";
      state.activeTask.error = "";
    }
    renderActiveTask();
    if (resume) schedulePoll(200);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function reuseHistory(item) {
    if (item.baseUrl) elements.baseUrl.value = item.baseUrl;
    if (item.workflowId) elements.workflowId.value = item.workflowId;
    elements.promptInput.value = item.prompt || "";
    state.images = Array.from({ length: 9 }, (_, index) => {
      const value = item.images?.[index] || "";
      return { value, preview: previewForStoredImage(value), uploading: false };
    });
    const profile = getWorkflowProfile();
    state.visibleImageSlots = isVideoProfile(profile)
      ? profile.imageSlots
      : Math.min(imageSlotLimit(profile), Math.max(3, item.images?.length || 0));
    rebuildImageSlots();
    applyWorkflowProfile({ rebuild: false });
    saveSettings();
    saveDraft();
    updateFormState();
    showToast("已恢复该任务参数");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function deleteHistory(item) {
    const key = item.promptId || item.id;
    state.history = state.history.filter((entry) => (entry.promptId || entry.id) !== key);
    renderHistory();
    try {
      const response = await fetch(`/api/history?id=${encodeURIComponent(key)}`, { method: "DELETE" });
      if (!response.ok) throw new Error(`删除失败（${response.status}）`);
      await loadAssets();
    } catch (error) {
      showToast(error.message || "删除历史失败", "error");
      await loadHistory();
    }
  }

  async function clearHistory() {
    if (!state.history.length) return;
    if (!window.confirm("确定清空全部生成历史吗？")) return;
    state.history = [];
    renderHistory();
    try {
      const response = await fetch("/api/history", { method: "DELETE" });
      if (!response.ok) throw new Error(`清空失败（${response.status}）`);
      state.assets = [];
      renderAssets();
      showToast("历史记录已清空");
    } catch (error) {
      showToast(error.message || "清空历史失败", "error");
      await loadHistory();
    }
  }

  async function loadHistory() {
    try {
      const response = await fetch("/api/history", { cache: "no-store" });
      const data = await readResponse(response);
      if (!response.ok) throw new Error(extractError(data, `历史读取失败（${response.status}）`));
      state.history = Array.isArray(data.items) ? data.items.slice(0, MAX_HISTORY) : [];
      renderHistory();
    } catch (error) {
      showToast(error.message || "历史读取失败", "error");
    }
  }

  async function loadAssets() {
    elements.refreshAssets.disabled = true;
    elements.refreshAssets.textContent = "刷新中";
    try {
      const response = await fetch("/api/assets", { cache: "no-store" });
      const data = await readResponse(response);
      if (!response.ok) throw new Error(extractError(data, `资产读取失败（${response.status}）`));
      state.assets = Array.isArray(data.items) ? data.items : [];
      renderAssets();
    } catch (error) {
      showToast(error.message || "资产读取失败", "error");
    } finally {
      elements.refreshAssets.disabled = false;
      elements.refreshAssets.textContent = "刷新资产";
    }
  }

  function renderAssets() {
    elements.assetsGrid.replaceChildren();
    elements.assetCount.textContent = String(state.assets.length);
    elements.assetsEmpty.hidden = state.assets.length > 0;

    state.assets.forEach((asset) => {
      const item = document.createElement("article");
      item.className = "asset-item";
      const mediaWrap = document.createElement("div");
      mediaWrap.className = "asset-media";
      const media = document.createElement(asset.type === "video" ? "video" : "img");
      media.src = mediaPreviewUrl(asset, Number(asset.mediaIndex) || 0, asset.url);
      if (asset.type === "video") {
        media.controls = true;
        media.preload = "metadata";
      } else {
        media.alt = asset.prompt || "生成资产";
        media.loading = "lazy";
      }
      media.addEventListener("error", () => {
        media.remove();
        mediaWrap.textContent = "资产暂时无法预览";
      });
      mediaWrap.append(media);

      const info = document.createElement("div");
      info.className = "asset-info";
      const prompt = document.createElement("p");
      prompt.textContent = asset.prompt || "未记录提示词";
      prompt.title = prompt.textContent;
      const meta = document.createElement("div");
      meta.className = "asset-meta";
      const taskId = document.createElement("span");
      taskId.textContent = String(asset.promptId || "—").slice(0, 14);
      taskId.title = asset.promptId || "";
      const open = document.createElement("a");
      open.href = asset.url;
      open.target = "_blank";
      open.rel = "noreferrer";
      open.textContent = "打开原文件";
      meta.append(taskId, open);
      info.append(prompt, meta);
      item.append(mediaWrap, info);
      elements.assetsGrid.append(item);
    });
  }

  function switchHistoryView(view) {
    const showAssets = view === "assets";
    elements.historyView.hidden = showAssets;
    elements.assetsView.hidden = !showAssets;
    elements.historyTab.classList.toggle("is-active", !showAssets);
    elements.assetsTab.classList.toggle("is-active", showAssets);
    elements.historyTab.setAttribute("aria-selected", String(!showAssets));
    elements.assetsTab.setAttribute("aria-selected", String(showAssets));
    elements.historyActions.hidden = showAssets;
    if (showAssets) loadAssets();
  }

  function trackPrompt() {
    const promptId = elements.trackPromptId.value.trim();
    const baseUrl = normalizeBaseUrl(elements.baseUrl.value);
    if (!promptId) {
      showToast("请输入任务 ID", "error");
      return;
    }
    if (!baseUrl) {
      showToast("请先填写服务地址", "error");
      return;
    }
    const now = new Date().toISOString();
    const existing = state.history.find((item) => item.promptId === promptId);
    stopPolling(false);
    state.activeTask = existing
      ? { ...existing, status: "pending", error: "", polling: true }
      : {
          id: promptId,
          promptId,
          baseUrl,
          workflowId: elements.workflowId.value.trim(),
          prompt: "外部任务",
          images: [],
          status: "pending",
          createdAt: now,
          updatedAt: now,
          pollCount: 0,
          result: null,
          error: "",
          polling: true,
        };
    elements.trackPromptId.value = "";
    upsertHistory(state.activeTask);
    renderActiveTask();
    schedulePoll(150);
  }

  function bindEvents() {
    elements.baseUrl.addEventListener("change", () => {
      elements.baseUrl.value = normalizeBaseUrl(elements.baseUrl.value);
      saveSettings();
      setServiceState("idle", "等待检查");
      updateFormState();
    });
    elements.workflowId.addEventListener("change", () => {
      saveSettings();
      applyWorkflowProfile();
    });
    elements.promptInput.addEventListener("input", () => {
      updateFormState();
      saveDraft();
    });
    elements.loadWarringPrompt.addEventListener("click", loadWarringRef2VAPrompt);
    [elements.stepsInput, elements.widthInput, elements.heightInput, elements.durationInput, elements.resolutionInput, elements.seedInput, elements.musicPreset].filter(Boolean).forEach((input) => {
      input.addEventListener("input", saveDraft);
      input.addEventListener("change", saveDraft);
    });
    elements.testConnection.addEventListener("click", checkConnection);
    elements.historyPickerClose.addEventListener("click", () => elements.historyPicker.close());
    elements.historyPicker.addEventListener("click", (event) => {
      if (event.target === elements.historyPicker) elements.historyPicker.close();
    });
    elements.historyPickerSearch.addEventListener("input", () => {
      clearTimeout(pickerSearchTimer);
      pickerSearchTimer = setTimeout(() => {
        const query = elements.historyPickerSearch.value.trim();
        if (query === picker.query) return;
        picker.query = query;
        picker.page = 0;
        picker.total = 0;
        picker.loaded = 0;
        picker.finished = false;
        elements.historyPickerGrid.replaceChildren();
        elements.historyPickerCount.textContent = "";
        elements.historyPickerStatus.textContent = query ? `搜索「${query}」…` : "正在加载历史图片…";
        loadHistoryPage(true);
      }, 300);
    });
    elements.generateButton.addEventListener("click", generateVideo);
    elements.generateFramesButton.addEventListener("click", generateReferenceFrames);
    elements.stopPolling.addEventListener("click", () => stopPolling(true));
    elements.trackButton.addEventListener("click", trackPrompt);
    elements.trackPromptId.addEventListener("keydown", (event) => {
      if (event.key === "Enter") trackPrompt();
    });
    elements.clearHistory.addEventListener("click", clearHistory);
    elements.historyTab.addEventListener("click", () => switchHistoryView("history"));
    elements.assetsTab.addEventListener("click", () => switchHistoryView("assets"));
    elements.refreshAssets.addEventListener("click", loadAssets);
    window.addEventListener("beforeunload", () => stopPolling(false));
  }

  loadSavedState();
  initializeImageSlots();
  bindEvents();
  applyWorkflowProfile({ rebuild: false });
  renderHistory();
  renderAssets();
  updateFormState();
  loadHistory();
  checkConnection();
})();
