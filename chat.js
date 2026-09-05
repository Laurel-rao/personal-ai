(() => {
  "use strict";

  const STORAGE_KEY = "media-creator.chat.sse.v1";
  const list = document.querySelector("#conversationList");
  const messages = document.querySelector("#messageList");
  const form = document.querySelector("#chatForm");
  const input = document.querySelector("#chatInput");
  const sendButton = document.querySelector("#sendButton");
  const newChatButton = document.querySelector("#newChatButton");
  const countBadge = document.querySelector("#conversationCount");

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

  // ---------- 轻量 Markdown 渲染（先转义，再转换，防注入） ----------
  function escapeHtml(value) {
    return value.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function safeHref(url) {
    return /^(https?:|mailto:)/i.test(url) ? url : "";
  }

  function mdInline(text) {
    return text
      .replace(/`([^`]+)`/g, (_, code) => `<code>${code}</code>`)
      .replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, url) => {
        const src = /^(https?:|data:image\/|\/)/i.test(url) ? url : "";
        return src ? `<img src="${src}" alt="${alt}" loading="lazy">` : alt;
      })
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, url) => {
        const href = safeHref(url);
        return href ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>` : label;
      })
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
      .replace(/~~([^~]+)~~/g, "<del>$1</del>");
  }

  function mdToHtml(source) {
    if (!source) return "";
    const escaped = escapeHtml(source);
    const blocks = [];
    let text = escaped;

    // 围栏代码块（先抽离，避免后续行内规则误伤）
    text = text.replace(/```([\w+-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
      const id = `\u0000${blocks.length}\u0000`;
      blocks.push(`<pre><code class="language-${escapeHtml(lang) || "text"}">${code.replace(/\n$/, "")}</code></pre>`);
      return id;
    });

    const lines = text.split("\n");
    const out = [];
    let i = 0;
    const flush = (buf, tag) => {
      if (!buf.length) return;
      const body = buf.join("\n").split("\n").map((l) => mdInline(l.trim())).join("<br>");
      out.push(tag === "p" ? `<p>${body}</p>` : body);
    };

    while (i < lines.length) {
      const line = lines[i];
      const blockId = line.match(/^\u0000(\d+)\u0000$/);

      if (blockId) {
        out.push(blocks[Number(blockId[1])]);
        i += 1;
        continue;
      }
      if (/^\s*$/.test(line)) { i += 1; continue; }
      if (/^\|.*\|$/.test(line)) {
        const rows = [];
        while (i < lines.length && /^\|.*\|$/.test(lines[i])) rows.push(lines[i++]);
        if (rows.length > 1 && /^\|[\s:|-]+\|$/.test(rows[1])) {
          out.push(mdTable(rows));
          continue;
        }
        out.push(`<p>${mdInline(rows.join("<br>"))}</p>`);
        continue;
      }
      if (/^#{1,6}\s/.test(line)) {
        const level = line.match(/^(#{1,6})\s/)[1].length;
        out.push(`<h${level}>${mdInline(line.replace(/^#{1,6}\s*/, ""))}</h${level}>`);
        i += 1;
        continue;
      }
      if (/^>\s?/.test(line)) {
        const quote = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ""));
        out.push(`<blockquote>${quote.map((l) => mdInline(l)).join("<br>")}</blockquote>`);
        continue;
      }
      if (/^\s*[-*+]\s/.test(line) || /^\s*\d+[.)]\s/.test(line)) {
        const ordered = /^\s*\d+[.)]\s/.test(line);
        const items = [];
        const marker = ordered ? /^\s*\d+[.)]\s/ : /^\s*[-*+]\s/;
        while (i < lines.length && marker.test(lines[i])) items.push(lines[i++].replace(marker, ""));
        out.push(`<${ordered ? "ol" : "ul"}>${items.map((it) => `<li>${mdInline(it)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`);
        continue;
      }
      if (/^-{3,}$/.test(line.trim())) { out.push("<hr>"); i += 1; continue; }

      const paragraph = [];
      while (i < lines.length && lines[i].trim() && !/^#{1,6}\s/.test(lines[i]) && !/^\s*[-*+]\s/.test(lines[i]) && !/^\s*\d+[.)]\s/.test(lines[i]) && !/^>\s?/.test(lines[i]) && !/^\|.*\|$/.test(lines[i]) && !/^-{3,}$/.test(lines[i].trim()) && !/^```/.test(lines[i]) && !/^\u0000\d+\u0000$/.test(lines[i])) {
        paragraph.push(lines[i++]);
      }
      flush(paragraph, "p");
    }
    return out.join("\n");
  }

  function mdTable(rows) {
    const parse = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
    const header = parse(rows[0]).map((c) => mdInline(c));
    const body = rows.slice(2).map((row) => parse(row).map((c) => mdInline(c)));
    return `<table><thead><tr>${header.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${body
      .map((cells) => `<tr>${cells.map((c) => `<td>${c}</td>`).join("")}</tr>`)
      .join("")}</tbody></table>`;
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
    if (countBadge) countBadge.textContent = String(state.conversations.length);
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
      const empty = document.createElement("div");
      empty.className = "empty-conversation";
      empty.innerHTML = `
        <div class="empty-orbit" aria-hidden="true">
          <span class="orbit orbit-a"></span>
          <span class="orbit orbit-b"></span>
          <span class="orbit-core">✦</span>
        </div>
        <h2>开始一段新对话</h2>
        <p>创作文案、拆解思路、打磨创意，从你的第一个问题开始。</p>
        <div class="empty-chips" aria-label="灵感提示">
          <button type="button" data-suggestion="帮我想 3 个短视频脚本的创意方向">短视频脚本创意</button>
          <button type="button" data-suggestion="用通俗的语言解释一个复杂概念">解释复杂概念</button>
          <button type="button" data-suggestion="帮我优化这段文案，让它更有感染力">文案润色</button>
        </div>`;
      empty.querySelectorAll("[data-suggestion]").forEach((chip) => {
        chip.addEventListener("click", () => {
          if (streaming) return;
          input.value = chip.dataset.suggestion;
          resizeInput();
          submit();
        });
      });
      messages.append(empty);
      return;
    }
    conversation.messages.forEach((message) => {
      const item = document.createElement("article");
      item.className = `message ${message.role}${message.streaming ? " streaming" : ""}`;
      const body = message.content || (message.streaming ? "正在思考" : "");
      item.innerHTML = body ? mdToHtml(body) : "";
      (message.images || []).forEach((image) => {
        const figure = document.createElement("figure");
        figure.className = "chat-image";
        const img = document.createElement("img");
        img.src = image.url || image.data_url || "";
        img.alt = image.prompt || "生成图片";
        img.loading = "lazy";
        figure.append(img);
        item.append(figure);
      });
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

  function applySseChunk(chunk, onText, onImages) {
    chunk.split(/\r?\n/).forEach((line) => {
      if (!line.startsWith("data:")) return;
      const data = line.slice(5).trim();
      if (!data || data === "[DONE]") return;
      try {
        const payload = JSON.parse(data);
        if (Array.isArray(payload.images) && onImages) onImages(payload.images);
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
      body: JSON.stringify({ messages: apiMessages(conversation), temperature: 0.7, max_tokens: 10240, enable_thinking: document.getElementById("thinkingToggle")?.checked || false, tools: true }),
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
      }, (images) => {
        assistant.images = (assistant.images || []).concat(images);
        renderMessages();
      }));
      if (done) break;
    }
    if (buffer) applySseChunk(buffer, (content) => { assistant.content += content; }, (images) => {
      assistant.images = (assistant.images || []).concat(images);
    });
  }

  async function submit() {
    const content = input.value.trim();
    if (!content || streaming) return;
    const conversation = activeConversation();
    conversation.messages.push({ role: "user", content });
    if (conversation.title === "新对话") conversation.title = content.replace(/\s+/g, " ").slice(0, 24);
    const assistant = { role: "assistant", content: "", images: [], streaming: true };
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
