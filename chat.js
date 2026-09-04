(() => {
  "use strict";

  const STORAGE_KEY = "media-creator.chat.sse.v1";
  const list = document.querySelector("#conversationList");
  const messages = document.querySelector("#messageList");
  const form = document.querySelector("#chatForm");
  const input = document.querySelector("#chatInput");
  const sendButton = document.querySelector("#sendButton");
  const newChatButton = document.querySelector("#newChatButton");

  let streaming = false;
  let state = loadState();

  function makeConversation() {
    return {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      title: "新对话",
      messages: [],
      updatedAt: Date.now(),
    };
  }

  function loadState() {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      if (Array.isArray(stored.conversations) && stored.conversations.length) {
        return { conversations: stored.conversations.slice(0, 30), activeId: stored.activeId || stored.conversations[0].id };
      }
    } catch {
      // Start clean if an older local cache is malformed.
    }
    const conversation = makeConversation();
    return { conversations: [conversation], activeId: conversation.id };
  }

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function activeConversation() {
    return state.conversations.find((conversation) => conversation.id === state.activeId) || state.conversations[0];
  }

  function renderList() {
    list.replaceChildren();
    state.conversations
      .slice()
      .sort((left, right) => right.updatedAt - left.updatedAt)
      .forEach((conversation) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `conversation-item${conversation.id === state.activeId ? " active" : ""}`;
        button.title = conversation.title;
        const label = document.createElement("span");
        label.textContent = conversation.title;
        button.append(label);
        button.addEventListener("click", () => {
          if (!streaming) {
            state.activeId = conversation.id;
            saveState();
            render();
          }
        });
        list.append(button);
      });
  }

  function renderMessages() {
    const conversation = activeConversation();
    messages.replaceChildren();
    if (!conversation.messages.length) {
      const empty = document.createElement("p");
      empty.className = "empty-conversation";
      empty.textContent = "开始新对话";
      messages.append(empty);
      return;
    }
    conversation.messages.forEach((message) => {
      const item = document.createElement("article");
      item.className = `message ${message.role}${message.streaming ? " streaming" : ""}`;
      item.textContent = message.content || (message.streaming ? "正在思考" : "");
      messages.append(item);
    });
    messages.scrollTop = messages.scrollHeight;
  }

  function render() {
    renderList();
    renderMessages();
  }

  function resizeInput() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 144)}px`;
  }

  function apiMessages(conversation) {
    return conversation.messages
      .filter((message) => !message.streaming && message.content)
      .map((message) => ({ role: message.role, content: message.content }))
      .slice(-40);
  }

  function applySseChunk(chunk, onText) {
    chunk.split(/\r?\n/).forEach((line) => {
      if (!line.startsWith("data:")) return;
      const data = line.slice(5).trim();
      if (!data || data === "[DONE]") return;
      try {
        const payload = JSON.parse(data);
        const content = payload.choices?.[0]?.delta?.content;
        if (typeof content === "string") onText(content);
      } catch {
        // Ignore provider keepalive and non-OpenAI SSE events.
      }
    });
  }

  async function streamReply(conversation, assistant) {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ messages: apiMessages(conversation), temperature: 0.7, max_tokens: 1024 }),
    });
    if (!response.ok || !response.body) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || "对话服务暂时不可用");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() || "";
      events.forEach((event) => applySseChunk(event, (content) => {
        assistant.content += content;
        renderMessages();
      }));
      if (done) break;
    }
    if (buffer) applySseChunk(buffer, (content) => { assistant.content += content; });
  }

  async function submit() {
    const content = input.value.trim();
    if (!content || streaming) return;
    const conversation = activeConversation();
    conversation.messages.push({ role: "user", content });
    if (conversation.title === "新对话") conversation.title = content.replace(/\s+/g, " ").slice(0, 24);
    const assistant = { role: "assistant", content: "", streaming: true };
    conversation.messages.push(assistant);
    conversation.updatedAt = Date.now();
    input.value = "";
    resizeInput();
    streaming = true;
    sendButton.disabled = true;
    render();
    try {
      await streamReply(conversation, assistant);
      assistant.streaming = false;
      if (!assistant.content) assistant.content = "模型没有返回内容。";
      conversation.updatedAt = Date.now();
      saveState();
    } catch (error) {
      assistant.streaming = false;
      assistant.content = error.message || "对话请求失败。";
      saveState();
    } finally {
      streaming = false;
      sendButton.disabled = false;
      render();
      input.focus();
    }
  }

  newChatButton.addEventListener("click", () => {
    if (streaming) return;
    const conversation = makeConversation();
    state.conversations.unshift(conversation);
    state.conversations = state.conversations.slice(0, 30);
    state.activeId = conversation.id;
    saveState();
    render();
    input.focus();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit();
  });

  input.addEventListener("input", resizeInput);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  });

  render();
  resizeInput();
})();
