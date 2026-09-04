(() => {
  const root = document.getElementById("chatRoot");
  const status = document.getElementById("chatStatus");
  const healthDot = document.getElementById("chatHealthDot");
  const nlux = window["@nlux/core"];

  const setStatus = (text, online) => {
    status.textContent = text;
    healthDot.classList.toggle("online", online);
    healthDot.classList.toggle("offline", online === false);
  };

  const messagesForApi = (history, message) => {
    const messages = (Array.isArray(history) ? history : [])
      .filter((item) => item && ["system", "user", "assistant"].includes(item.role) && typeof item.message === "string")
      .map((item) => ({ role: item.role, content: item.message }));
    const last = messages[messages.length - 1];
    if (!last || last.role !== "user" || last.content !== message) {
      messages.push({ role: "user", content: message });
    }
    return messages.slice(-40);
  };

  const adapter = {
    async batchText(message, extras) {
      const response = await fetch("api/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: messagesForApi(extras.conversationHistory, message),
          temperature: 0.7,
          max_tokens: 1024,
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(result.error || "对话服务暂时不可用");
      }
      const content = result.choices?.[0]?.message?.content;
      if (typeof content !== "string" || !content.trim()) {
        throw new Error("模型没有返回可显示的内容");
      }
      return content.trim();
    },
  };

  if (!nlux?.createAiChat) {
    setStatus("聊天组件加载失败", false);
    root.textContent = "NLUX 组件未能加载，请刷新页面后重试。";
    return;
  }

  nlux.createAiChat()
    .withAdapter(adapter)
    .withDisplayOptions({ colorScheme: "light", width: "100%", height: "100%" })
    .withConversationOptions({
      historyPayloadSize: "max",
      layout: "bubbles",
      showWelcomeMessage: true,
      conversationStarters: [
        { label: "提示词优化", prompt: "帮我优化一段用于图片生成的提示词。" },
        { label: "创意构思", prompt: "给我三个有视觉张力的图片创意方向。" },
      ],
    })
    .withComposerOptions({
      autoFocus: true,
      placeholder: "输入消息，Enter 发送，Shift + Enter 换行",
      submitShortcut: "Enter",
    })
    .withMessageOptions({ markdownLinkTarget: "blank" })
    .mount(root);

  fetch("api/chat/health")
    .then((response) => response.json().then((body) => ({ response, body })))
    .then(({ response, body }) => setStatus(response.ok && body.ok ? `已连接 ${body.model}` : "Qwen 服务不可用", response.ok && body.ok))
    .catch(() => setStatus("Qwen 服务不可用", false));
})();
