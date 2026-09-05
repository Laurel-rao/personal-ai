/* 设置页逻辑：读取/保存生效配置，测试引擎连通性。密钥不回显完整值。 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const statusEl = $("settingsStatus");

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

  $("saveButton").addEventListener("click", saveSettings);
  $("verifyComfyButton").addEventListener("click", verifyComfy);
  $("verifyVideoButton").addEventListener("click", verifyVideo);
  loadSettings();
})();