(() => {
  "use strict";
  const context = JSON.parse(document.getElementById("workspace-context")?.textContent || "{}");
  window.personalAI = context;
  context.renderIcons = () => {
    const icons = {copy:"copy",download:"download","maximize-2":"expand",play:"play","trash-2":"trash",check:"check","thumbs-up":"thumbs-up","thumbs-down":"thumbs-down",x:"xmark"};
    document.querySelectorAll("[data-lucide]").forEach((element) => {
      element.className = `fa fa-${icons[element.dataset.lucide] || "circle"}`;
      element.setAttribute("aria-hidden", "true");
    });
  };
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (resource, options = {}) => {
    const url = new URL(resource instanceof Request ? resource.url : resource, location.href);
    if (url.origin !== location.origin) return originalFetch(resource, options);
    const headers = new Headers(options.headers || (resource instanceof Request ? resource.headers : undefined));
    const method = (options.method || (resource instanceof Request ? resource.method : "GET")).toUpperCase();
    if (context.user) headers.set("X-Workspace-User", String(context.user.id));
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers.set("X-CSRFToken", context.csrf);
    const response = await originalFetch(resource, { ...options, headers });
    if (response.status === 401) location.assign("/login/");
    if (response.status === 409 && response.headers.get("X-Workspace-Changed")) location.reload();
    return response;
  };
  const escape = (text) => String(text).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  const pages = {
    video: ["视频生成", "连接参考图与视频提示词，追踪从创意到成片的每一步。", "film"],
    image: ["图片生成", "描述画面、调整参数，单张创作与批量生成在这里完成。", "image"],
    chat: ["文本对话", "讨论灵感、拆解思路与打磨文案，保留每一次创作对话。", "comment"],
    review: ["图片标注", "筛选作品、记录偏好，让每一次标注成为下一次创作的参考。", "check-square"],
    library: ["图片库", "按提示词、类别、标注和时间，找到需要的那一张作品。", "images"],
    rewrite: ["记忆仿写", "按类别管理共享记忆、仿写参数与运行日志。", "wand-magic-sparkles"],
    settings: ["服务设置", "集中维护生成引擎与密钥，安全查看当前生效配置。", "sliders"],
    "legacy-chat": ["Photo Lab 对话", "保留原有对话组件与连接状态，继续使用 Qwen 创作助手。", "comment"],
    users: ["用户管理", "管理成员资料、账号状态与角色分配。", "users"],
    roles: ["角色与权限", "通过角色配置功能访问范围，授权在下次请求时生效。", "shield-halved"],
    menus: ["菜单管理", "统一管理菜单名称、显示顺序与可见状态。", "bars"],
  };
  const icon = (name) => `<i class="fa fa-${name}" aria-hidden="true"></i>`;
  document.addEventListener("DOMContentLoaded", () => {
    if (!context.user) {
      document.body.classList.add("workspace-login-page");
      return;
    }
    context.renderIcons();
    if (window.self !== window.top) {
      document.body.classList.add("workspace-embedded");
      return;
    }
    document.body.classList.add("workspace-authenticated");
    const path = location.pathname;
    const page = document.body.dataset.page || (path.startsWith("/users/") ? "users" : path.startsWith("/roles/") ? "roles" : path.startsWith("/workspacemenuview/") ? "menus" : "");
    if (page) document.body.dataset.page = page;
    const active = context.menus.find((item) => item.key === page || (page === "legacy-chat" && item.key === "chat"));
    if (["users", "roles", "menus"].includes(page)) {
      const helpLabels = {
        "It's not a good policy to remove a user, just make it inactive": "建议停用账号而非直接删除，以保留业务记录。",
        "The user group on the application, this will associate with a list of roles associated with the group": "用户组可统一关联一组角色，为成员继承相应权限。",
        "The user's password for authentication": "用于登录验证的账号密码。",
      };
      document.querySelectorAll(".help-block").forEach((element) => {
        const translation = helpLabels[element.textContent.trim()];
        if (translation) element.textContent = translation;
      });
      document.querySelectorAll('input[type="password"]').forEach((element) => element.setAttribute("autocomplete", "new-password"));
      document.querySelectorAll("td").forEach((cell) => {
        if (cell.textContent === "True" || cell.textContent === "False") {
          const enabled = cell.textContent === "True";
          cell.innerHTML = `<span class="workspace-status-chip ${enabled ? "enabled" : "disabled"}">${page === "menus" ? (enabled ? "显示中" : "已隐藏") : (enabled ? "已启用" : "已停用")}</span>`;
        } else if (cell.textContent === "[]") cell.textContent = "—";
      });
      document.querySelectorAll("th, label").forEach((element) => {
        element.childNodes.forEach((node) => {
          if (node.nodeType === 3 && node.textContent.trim() === "Groups") node.textContent = "用户组";
        });
      });
      const actionLabels = {Add: "新增", Show: "查看", Edit: "编辑", Delete: "删除"};
      document.querySelectorAll("a .sr-only").forEach((label) => {
        const translation = actionLabels[label.textContent.trim()];
        if (translation) {
          label.textContent = translation;
          label.closest("a").setAttribute("title", translation);
        }
      });
      document.querySelectorAll('a[href$="/add"], a[href$="/add/"]').forEach((link) => {
        const label = page === "users" ? "新增用户" : page === "roles" ? "新增角色" : "新增";
        link.setAttribute("aria-label", label);
        link.insertAdjacentHTML("beforeend", `<span class="workspace-action-label">${label}</span>`);
      });
    }
    const management = path.startsWith("/users/") || path.startsWith("/roles/") || path.startsWith("/workspacemenuview/");
    const title = pages[page]?.[0] || active?.title || (path === "/" ? "工作台概览" : management ? "组织与权限" : "账号管理");
    const menuLink = (item) => `<a href="${item.url}" ${active?.key === item.key ? 'aria-current="page"' : ""}><span class="workspace-nav-icon">${icon(pages[item.key]?.[2] || "circle")}</span>${escape(item.title)}</a>`;
    const sidebar = document.createElement("aside");
    sidebar.className = "workspace-sidebar";
    sidebar.id = "workspace-sidebar";
    sidebar.innerHTML = `<a class="workspace-brand" href="/"><span>p<span class="workspace-brand-dot">.</span></span><div>Personal AI<small>创作管理工作台</small></div></a><nav aria-label="主导航"><span class="workspace-nav-label">工作空间</span><a href="/" ${path === "/" ? 'aria-current="page"' : ""}><span class="workspace-nav-icon">▤</span>工作台概览</a>${context.menus.filter(item => !["settings", "rewrite"].includes(item.key)).map(menuLink).join("")}<span class="workspace-nav-label">管理与配置</span>${context.menus.filter(item => ["settings", "rewrite"].includes(item.key)).map(menuLink).join("")}${context.admin ? `<a href="/users/list/" ${path.startsWith("/users/") ? 'aria-current="page"' : ""}><span class="workspace-nav-icon">♙</span>用户管理</a><a href="/roles/list/" ${path.startsWith("/roles/") ? 'aria-current="page"' : ""}><span class="workspace-nav-icon">◇</span>角色与权限</a>` : '<p class="workspace-nav-hint">功能由管理员按角色授权</p>'}</nav><div class="workspace-sidebar-bottom"><span class="workspace-avatar">${escape(context.user.name.slice(0, 1))}</span><div><strong>${escape(context.user.name)}</strong><small>${escape(context.user.roles.join(" / ") || "待授权")}</small></div><button type="button" id="workspace-logout" aria-label="退出登录" title="退出登录">↪</button></div>`;
    const header = document.createElement("header");
    if (context.admin) {
      const menuSettings = document.createElement("a");
      menuSettings.href = "/workspacemenuview/list/";
      menuSettings.innerHTML = '<span class="workspace-nav-icon">☷</span>菜单管理';
      if (path.startsWith("/workspacemenuview/")) menuSettings.setAttribute("aria-current", "page");
      sidebar.querySelector("nav").append(menuSettings);
    }
    const sidebarIcons = {"/": "table-cells-large", "/users/list/": "users", "/roles/list/": "shield-halved", "/workspacemenuview/list/": "bars"};
    sidebar.querySelectorAll("nav a").forEach((link) => {
      const name = sidebarIcons[link.getAttribute("href")];
      if (name) link.querySelector(".workspace-nav-icon").innerHTML = icon(name);
    });
    header.className = "workspace-header";
    header.innerHTML = `<div><button class="workspace-menu-toggle" aria-label="切换侧栏" aria-controls="workspace-sidebar" aria-expanded="true">☰</button><h1>${escape(title)}</h1></div>`;
    const pageHeading = document.querySelector("[data-page-heading]");
    const pageActions = pageHeading?.querySelector(".page-heading-actions");
    if (pageActions?.querySelector('[id], button')) header.append(pageActions);
    pageHeading?.remove();
    if (page === "video") {
      const connection = document.querySelector(".connection-band");
      const settings = document.createElement("details");
      settings.className = "workspace-connection";
      const summary = document.createElement("summary");
      summary.textContent = "服务连接配置";
      connection.before(settings);
      settings.append(summary, connection);
      document.querySelector("main.workspace").append(document.querySelector(".history-section"));
    }
    if (page === "library") {
      const filters = document.querySelector(".library-filter-row");
      const disclosure = document.createElement("details");
      disclosure.className = "workspace-filter-disclosure";
      const summary = document.createElement("summary");
      summary.textContent = "筛选条件 · 类别 / 状态 / 时间";
      filters.before(disclosure);
      disclosure.append(summary, filters);
      const mobile = matchMedia("(max-width: 900px)");
      disclosure.open = !mobile.matches;
      mobile.addEventListener("change", () => { disclosure.open = !mobile.matches; });
    }
    const overlay = document.createElement("button");
    overlay.className = "workspace-overlay";
    overlay.setAttribute("aria-label", "关闭导航");
    document.body.prepend(sidebar, header, overlay);
    const toggle = header.querySelector("button");
    const toggleSidebar = () => {
      if (matchMedia("(max-width: 900px)").matches) toggle.setAttribute("aria-expanded", String(document.body.classList.toggle("workspace-menu-open")));
      else toggle.setAttribute("aria-expanded", String(!document.body.classList.toggle("workspace-sidebar-collapsed")));
    };
    toggle.setAttribute("aria-expanded", String(!matchMedia("(max-width: 900px)").matches));
    toggle.addEventListener("click", toggleSidebar);
    overlay.addEventListener("click", toggleSidebar);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && document.body.classList.contains("workspace-menu-open")) toggleSidebar();
    });
    document.getElementById("workspace-logout").addEventListener("click", async () => {
      const button = document.getElementById("workspace-logout");
      button.disabled = true;
      try {
        const response = await fetch("/api/logout", { method: "POST" });
        if (response.ok) location.assign("/login/");
        else button.title = "退出失败，请刷新页面后重试";
      } catch {
        button.title = "网络不可用，请重试";
      } finally {
        button.disabled = false;
      }
    });
    document.querySelectorAll("table").forEach((table) => {
      if (table.closest("form")) {
        table.classList.add("workspace-form-table");
        return;
      }
      if (table.parentElement.classList.contains("table-responsive")) return;
      const wrapper = document.createElement("div");
      wrapper.className = "workspace-table-scroll";
      wrapper.tabIndex = 0;
      wrapper.setAttribute("role", "region");
      wrapper.setAttribute("aria-label", "数据表格，可横向滚动");
      table.before(wrapper);
      wrapper.append(table);
    });
  });
})();
