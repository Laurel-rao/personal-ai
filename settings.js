/* 设置页逻辑：读取/保存生效配置，测试引擎连通性。密钥不回显完整值。 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const statusEl = $("settingsStatus");
  const startupToggle = $("startupEnabled");
  const startupStatus = $("startupStatus");
  const reloadStartupButton = $("reloadStartupButton");
  let startupEnabled = false;

  function setStartupStatus(text, tone) {
    startupStatus.textContent = text;
    startupStatus.className = "settings-status" + (tone ? " " + tone : "");
  }

  async function updateStartup(save) {
    const enabled = startupToggle.checked;
    startupToggle.disabled = true;
    reloadStartupButton.disabled = true;
    setStartupStatus(save ? "正在保存…" : "正在读取…");
    try {
      const response = await fetch("/api/settings/startup", save ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      } : { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || "请求失败");
      startupEnabled = data.enabled;
      startupToggle.checked = startupEnabled;
      startupToggle.disabled = !data.supported;
      setStartupStatus(data.supported
        ? (startupEnabled ? "已开启：下次登录后自动启动 4173 后端。" : "已关闭：下次登录后不自动启动，当前服务不受影响。")
        : "开机启动设置仅支持 macOS。", data.supported ? "ok" : "");
    } catch (error) {
      startupToggle.checked = startupEnabled;
      setStartupStatus("操作失败：" + error.message + "；请刷新状态后重试。", "err");
    } finally {
      reloadStartupButton.disabled = false;
    }
  }

  function setStatus(text, tone) {
    statusEl.textContent = text;
    statusEl.className = "settings-status" + (tone ? " " + tone : "");
  }

  function mask(value) {
    if (!value) return "未设置";
    return value;
  }

  async function loadSettings() {
    try {
      const response = await fetch("/api/settings", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || "读取失败");
      $("effectiveComfyUrl").value = data.comfy_url || "";
      $("effectiveAutodlToken").value = data.autodl_token_set
        ? (data.autodl_token_masked || "已设置")
        : "未设置";
      $("effectiveAztKey").value = data.azt_key_set ? (data.azt_key_masked || "已设置") : "未设置";
      $("comfyUrls").textContent = "当前：" + (data.comfy_url || "未配置");
      $("autodlTokenState").textContent = data.autodl_token_set ? "已配置（保存时留空保持不变）" : "尚未配置";
      $("aztKeyState").textContent = data.azt_key_set ? "已配置（保存时留空保持不变）" : "尚未配置";
      const dmmProxy = data.dmm_proxy || "";
      const fallback = (data.dmm_proxy_candidates || [])[0] || "未配置";
      $("dmmProxyState").textContent = dmmProxy
        ? "当前：" + dmmProxy
        : "未配置（回退：" + fallback + "）";
      setStatus("");
    } catch (error) {
      setStatus("读取设置失败：" + error.message, "err");
    }
  }

  async function saveSettings() {
    const payload = {};
    const comfyUrl = $("comfyUrl").value.trim();
    const autodlToken = $("autodlToken").value.trim();
    const aztKey = $("aztKey").value.trim();
    if (comfyUrl) payload.comfyUrl = comfyUrl;
    if (autodlToken) payload.autodlToken = autodlToken;
    if (aztKey) payload.aztKey = aztKey;
    if (!Object.keys(payload).length) {
      setStatus("没有需要保存的内容（输入框留空即保持不变）", "err");
      return;
    }
    const saveButton = $("saveButton");
    saveButton.disabled = true;
    setStatus("保存中…");
    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || "保存失败");
      $("comfyUrl").value = "";
      $("autodlToken").value = "";
      $("aztKey").value = "";
      setStatus("已保存并生效：" + data.updated.join("、"), "ok");
      await loadSettings();
    } catch (error) {
      setStatus("保存失败：" + error.message, "err");
    } finally {
      saveButton.disabled = false;
    }
  }

  async function verifyComfy() {
    setStatus("正在测试 ComfyUI…");
    try {
      const response = await fetch("/photo/api/health", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "服务不可用");
      setStatus("ComfyUI 正常：" + (data.version || "") + " · " + (data.device || ""), "ok");
    } catch (error) {
      setStatus("ComfyUI 连接失败：" + error.message, "err");
    }
  }

  async function verifyVideo() {
    setStatus("正在测试视频服务…");
    try {
      const response = await fetch("/api/service/check?base_url=" + encodeURIComponent("https://www.autodl.art"), {
        cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || "服务不可用");
      setStatus("视频服务正常：" + (data.provider || "AutoDL.Art") + " " + (data.status || ""), "ok");
    } catch (error) {
      setStatus("视频服务检查失败：" + error.message, "err");
    }
  }

  function setDmmStatus(text, tone) {
    const element = $("dmmProxyStatus");
    element.textContent = text;
    element.className = "settings-status" + (tone ? " " + tone : "");
  }

  function renderDmmResults(results) {
    const box = $("dmmProxyResult");
    box.innerHTML = "";
    for (const result of results) {
      const line = document.createElement("div");
      const place = result.country ? `出口 ${result.country}${result.city ? "/" + result.city : ""}` : "出口未知";
      if (result.ok && result.dmm_ok) {
        line.textContent = `${result.proxy} · 可用 · ${place} · ${result.latency_ms || "—"}ms · DMM 可达`;
      } else if (result.ok) {
        line.textContent = `${result.proxy} · 代理可用但 DMM 不可达（${result.dmm_status || result.error || "未知"}）`;
      } else {
        line.textContent = `${result.proxy} · 不可用 · ${result.error || "未知错误"}`;
      }
      box.appendChild(line);
    }
  }

  async function saveDmmProxy() {
    const button = $("saveDmmProxy");
    button.disabled = true;
    setDmmStatus("保存中…");
    try {
      const response = await fetch("/api/settings/dmm-proxy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proxy: $("dmmProxy").value.trim() }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || "保存失败");
      $("dmmProxy").value = "";
      setDmmStatus("已保存并立即生效", "ok");
      await loadSettings();
    } catch (error) {
      setDmmStatus("保存失败：" + error.message, "err");
    } finally {
      button.disabled = false;
    }
  }

  async function checkDmmProxy() {
    const button = $("checkDmmProxy");
    button.disabled = true;
    setDmmStatus("正在检测代理…");
    try {
      const response = await fetch("/api/settings/dmm-proxy?check=1", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || "检测失败");
      renderDmmResults(data.results || []);
      const usable = (data.results || []).some((item) => item.ok && item.dmm_ok);
      setDmmStatus(usable ? "检测完成" : "没有可用的 DMM 代理", usable ? "ok" : "err");
    } catch (error) {
      setDmmStatus("检测失败：" + error.message, "err");
    } finally {
      button.disabled = false;
    }
  }

  async function startDmmProxy() {
    const button = $("startDmmProxy");
    button.disabled = true;
    setDmmStatus("正在启动本机 JP 出口…");
    try {
      const response = await fetch("/api/settings/dmm-proxy/start", { method: "POST" });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || data.output || "启动失败");
      setDmmStatus("JP 出口已启动", "ok");
      $("dmmProxyResult").textContent = data.output || "";
      await checkDmmProxy();
    } catch (error) {
      setDmmStatus("启动失败：" + (error.message || "未知错误"), "err");
    } finally {
      button.disabled = false;
    }
  }

  $("saveButton").addEventListener("click", saveSettings);
  $("saveDmmProxy").addEventListener("click", saveDmmProxy);
  $("checkDmmProxy").addEventListener("click", checkDmmProxy);
  $("startDmmProxy").addEventListener("click", startDmmProxy);
  $("verifyComfyButton").addEventListener("click", verifyComfy);
  $("verifyVideoButton").addEventListener("click", verifyVideo);
  startupToggle.addEventListener("change", () => updateStartup(true));
  reloadStartupButton.addEventListener("click", () => updateStartup(false));
  updateStartup(false);
  loadSettings();
})();
