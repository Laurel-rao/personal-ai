import json
import os
import re
import secrets
from datetime import timedelta
from pathlib import Path

from flask import current_app, jsonify, redirect, render_template, request, session
from flask_appbuilder import AppBuilder, IndexView, ModelView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.manager import AUTH_DB
from flask_login import current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parent
MODULES = (
    ("video", "视频生成", "/video", "从首尾帧到完整视频，管理你的生成任务", "film"),
    ("image", "图片生成", "/image", "用自然语言描述创意，生成单图或批量作品", "image"),
    ("chat", "文本对话", "/chat", "与创作助手对话，梳理灵感与文案", "comment"),
    ("review", "图片标注", "/photo/review", "筛选、评价与整理生成结果", "check-square"),
    ("library", "图片库", "/photo/library", "在自己的作品中查找与预览图片", "th-large"),
    ("rewrite", "记忆仿写", "/photo/rewrite", "管理员维护共享记忆与批量仿写任务", "magic"),
    ("settings", "服务设置", "/settings", "集中维护生成服务与平台凭据", "sliders"),
)
db = SQLAlchemy()


class WorkspaceMenu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(32), unique=True, nullable=False)
    title = db.Column(db.String(64), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    enabled = db.Column(db.Boolean, nullable=False, default=True)


class WorkspaceMenuView(ModelView):
    datamodel = SQLAInterface(WorkspaceMenu)
    base_permissions = ["can_list", "can_show", "can_edit"]
    list_title = "菜单管理"
    edit_title = "编辑菜单"
    show_title = "菜单详情"
    list_columns = ["title", "key", "position", "enabled"]
    edit_columns = ["title", "position", "enabled"]
    show_columns = list_columns
    label_columns = {"title": "菜单名称", "key": "权限标识", "position": "显示顺序", "enabled": "显示菜单"}
    base_order = ("position", "asc")


def is_admin():
    return current_user.is_authenticated and any(role.name == "Admin" for role in current_user.roles)


def owns_record(record):
    return current_user.is_authenticated and (is_admin() or record.get("owner_id") == current_user.id)


def allowed(module):
    return current_app.appbuilder.sm.has_access("can_access", f"Workspace:{module}")


def menu_items():
    definitions = {item[0]: item for item in MODULES}
    result = []
    for menu in db.session.query(WorkspaceMenu).filter_by(enabled=True).order_by(WorkspaceMenu.position, WorkspaceMenu.id):
        if menu.key not in definitions or not allowed(menu.key):
            continue
        if menu.key in {"settings", "rewrite"} and not is_admin():
            continue
        key, title, url, description, icon = definitions[menu.key]
        result.append(dict(key=key, title=menu.title, url=url, description=description, icon=icon))
    return result


class WorkspaceIndex(IndexView):
    @expose("/")
    def index(self):
        return self.render_template("admin/dashboard.html", menus=menu_items())


def route_module():
    path = request.path.rstrip("/") or "/"
    if path.startswith("/photo/api/rewrite") or path == "/photo/rewrite":
        return "rewrite"
    if path.startswith("/photo/api/review") or path == "/photo/review":
        return "review" if request.method != "GET" else ("review", "library")
    if path.startswith("/photo/api/library-image") or path == "/photo/library":
        return "library"
    if path.startswith(("/photo/chat", "/photo/api/chat", "/api/chat")) or path in ("/chat", "/chat.html"):
        return "chat"
    if path.startswith("/api/settings") or path in ("/settings", "/settings.html"):
        return "settings"
    if path.startswith("/photo/api/tasks"):
        return ("image", "video", "review", "library") if request.method == "GET" else "image"
    if path.startswith("/photo") or path in ("/image", "/image.html"):
        return "image"
    if path.startswith(("/api/", "/templates/")) or path in ("/video", "/index.html"):
        return "video"
    return None


def init_admin(app):
    state_dir = Path(app.config.get("PERSONAL_AI_STATE_DIR") or os.getenv("PERSONAL_AI_STATE_DIR", ROOT / "data"))
    state_dir.mkdir(parents=True, exist_ok=True)
    secret_path = state_dir / ".session-secret"
    if not app.config.get("SECRET_KEY"):
        if not secret_path.exists():
            try:
                descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as output:
                    output.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        app.config["SECRET_KEY"] = os.getenv("PERSONAL_AI_SECRET_KEY") or secret_path.read_text().strip()
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", f"sqlite:///{state_dir / 'accounts.db'}")
    app.config.update(
        AUTH_TYPE=AUTH_DB, AUTH_USER_REGISTRATION=False, APP_NAME="Personal AI",
        LANGUAGES={"zh": {"flag": "cn", "name": "中文"}}, BABEL_DEFAULT_LOCALE="zh",
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("PERSONAL_AI_COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8), WTF_CSRF_TIME_LIMIT=28800,
        AUTH_RATE_LIMITED=True, AUTH_RATE_LIMIT="10 per minute",
        RATELIMIT_STORAGE_URI=os.getenv("PERSONAL_AI_RATELIMIT_STORAGE_URI", "memory://"),
        FAB_API_SWAGGER_UI=False,
        FAB_PASSWORD_HASH_METHOD="pbkdf2:sha256:1000000",
        AUTH_DB_FAKE_PASSWORD_HASH_CHECK=generate_password_hash(secrets.token_urlsafe(32), method="pbkdf2:sha256:1000000"),
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        builder = AppBuilder(app, db.session, indexview=WorkspaceIndex)
        manager = builder.sm
        creator = manager.find_role("Creator")
        new_creator = creator is None
        creator = creator or manager.add_role("Creator")
        manager.add_role("Viewer")
        for position, (key, title, url, description, icon) in enumerate(MODULES):
            manager.add_permissions_view(["can_access"], f"Workspace:{key}")
            builder.add_link(title, href=url, icon=f"fa-{icon}", category="创作工作台")
            if not db.session.query(WorkspaceMenu).filter_by(key=key).first():
                db.session.add(WorkspaceMenu(key=key, title=title, position=position, enabled=True))
            if new_creator and key not in {"settings", "rewrite"}:
                manager.add_permission_role(creator, manager.find_permission_view_menu("can_access", f"Workspace:{key}"))
        db.session.commit()
        builder.add_view(WorkspaceMenuView, "菜单管理", icon="fa-bars", category="管理与配置")

    @app.before_request
    def authorize():
        endpoint = request.endpoint or ""
        public = endpoint.endswith(".static") or endpoint == "static" or (
            endpoint.startswith("console.static_") and request.path.endswith((".css", ".js")))
        if public or request.path == "/login/" or request.path == "/api/health":
            return None
        if not current_user.is_authenticated or not current_user.is_active:
            logout_user()
            if "/api/" in request.path:
                return jsonify(success=False, error="请先登录"), 401
            return redirect("/login/")
        requested_user = request.headers.get("X-Workspace-User")
        if requested_user and requested_user != str(current_user.id):
            return jsonify(success=False, error="账号已切换，请刷新页面后重试"), 409, {"X-Workspace-Changed": "1"}
        if request.path == "/logout/":
            return redirect("/")
        if request.path in {"/", "/api/session", "/api/logout"}:
            return None
        module = route_module()
        if module:
            modules = (module,) if isinstance(module, str) else module
            granted = any(allowed(item) for item in modules)
            if module in ("rewrite", "settings"):
                granted = granted and is_admin()
            if not granted:
                if "/api/" in request.path:
                    return jsonify(success=False, error="当前账号没有此功能的访问权限"), 403
                return render_template("admin/forbidden.html"), 403
        elif not public and not is_admin():
            return render_template("admin/forbidden.html"), 403

    CSRFProtect(app)

    @app.context_processor
    def workspace_template_context():
        return {"appbuilder": app.appbuilder, "base_template": "appbuilder/baselayout.html"}

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        if "/api/" in request.path:
            return jsonify(success=False, error="安全令牌无效或已过期，请刷新页面"), 400
        return render_template("admin/forbidden.html", message="页面已过期，请刷新后重试"), 400

    @app.get("/api/session")
    def workspace_session():
        return jsonify(user={"id": current_user.id, "name": current_user.first_name or current_user.username},
                       roles=[role.name for role in current_user.roles], menus=menu_items(), csrf=generate_csrf())

    @app.post("/api/logout")
    def workspace_logout():
        logout_user()
        session.clear()
        return jsonify(success=True)

    @app.after_request
    def workspace_response(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        if response.mimetype == "text/html" and response.status_code != 302:
            response.direct_passthrough = False
            content = response.get_data(as_text=True)
            content = re.sub(r'<script src="https://(?:cdn.tailwindcss.com|unpkg.com/lucide@latest)[^"]*"></script>', "", content)
            content = re.sub(r'<link[^>]*href="https://fonts\.(?:googleapis|gstatic)\.com[^"]*"[^>]*>', "", content)
            content = re.sub(r'<script src="(?:\.\./|\./|/)ui-framework.js"></script>', "", content)
            context = {"user": None, "menus": [], "csrf": generate_csrf()}
            if current_user.is_authenticated and current_user.is_active:
                context.update(user={"id": current_user.id, "name": current_user.first_name or current_user.username,
                                     "roles": [role.name for role in current_user.roles]},
                               menus=menu_items(), admin=is_admin())
            encoded = json.dumps(context, ensure_ascii=False).replace("<", "\\u003c")
            bootstrap = f'<script id="workspace-context" type="application/json">{encoded}</script>'
            bootstrap += '<script src="/ui-framework.js"></script><link rel="stylesheet" href="/ui-framework.css"><link rel="stylesheet" href="/admin.css"><link rel="stylesheet" href="/workspace-pages.css">'
            if 'fontawesome.min.css' not in content:
                bootstrap += '<link rel="stylesheet" href="/static/appbuilder/css/fontawesome/fontawesome.min.css"><link rel="stylesheet" href="/static/appbuilder/css/fontawesome/solid.min.css">'
            content = content.replace("</head>", bootstrap + "</head>")
            response.set_data(content)
            response.headers.pop("ETag", None)
        if response.mimetype in {"text/html", "application/json"} or "/api/" in request.path:
            response.headers["Cache-Control"] = "no-store, private"
        return response
