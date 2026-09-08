# Personal AI 工作台

基于 Flask-AppBuilder 5.2.2 的多用户创作后台。统一登录、角色授权、菜单配置、页面侧栏与设计规范，保留 H3 视频、文本对话和 Photo Lab 业务。

## 启动

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/flask --app app:create_app fab create-admin
.venv/bin/python app.py --host 127.0.0.1 --port 4173
```

浏览器访问：

- <http://127.0.0.1:4173/> —— 工作台概览；未登录时跳转登录页
- <http://127.0.0.1:4173/video> —— H3 视频工作台
- <http://127.0.0.1:4173/image> —— 图片生成（完整页面，不使用 iframe）
- <http://127.0.0.1:4173/photo/> —— Photo Lab（ComfyUI 图片生成，前缀挂载）

## 结构

| 入口 | 说明 |
| --- | --- |
| `app.py` | 统一 Flask 入口，注册 console 与 Photo Lab 蓝图，所有接口共享认证链 |
| `server.py` | H3 视频工作台 Flask 蓝图（`console_bp`），也可独立运行 |
| `photo_lab/app.py` | Photo Lab 蓝图，禁止绕过统一入口单独启动 |
| `admin.py` | Flask-AppBuilder 用户/角色管理、菜单模型、业务鉴权与 CSRF |
| `ui-framework.js` / `admin.css` | 统一导航、账号信息、请求安全头与响应式页面样式 |
| `workspace-pages.css` | 业务页与原生后台内容区的统一样式，保留原有业务控件与交互 |

全页面 UI 重构范围、维护约定与实际验收边界见 [UI 重构说明](docs/UI_REFACTOR.md)。

图片历史、图库和标注页共用支持缩放、旋转、复制、下载及提示词展示的 [图片预览组件](docs/IMAGE_PREVIEW.md)。

视频配置与草稿、文本会话按用户 ID 分开保存在当前浏览器。视频历史按用户隔离，普通用户位于 `data/users/<用户ID>/history.json`，管理员保留原有 `data/history.json` 档案；Photo Lab 的 `photo_lab/data/tasks.json` 新记录具有服务端写入的 `owner_id`。没有归属的旧图片任务及 Skill 输出仅管理员可见，不自动分配给新用户。管理员可管理 Photo Lab 全量记录。

## 用户、权限和菜单

- 用户管理：`/users/list/`，支持开通账号、编辑资料、启用/停用、分配角色及重置密码。账号停用后已有会话也无法再访问接口。
- 角色与权限：`/roles/list/`。`Admin` 管理整个后台；`Creator` 默认开放视频、图片、对话、标注和图库；`Viewer` 初始无业务权限，可作为待授权角色。不开放公开注册，也不提供固定默认密码。
- 授权操作：在角色编辑页为目标角色选择 `can access on Workspace:video/image/chat/review/library` 等权限，然后将该角色分配给用户。角色变更在下次请求时生效。
- 菜单管理：`/workspacemenuview/list/`，可编辑名称、顺序和显示状态。菜单由已启用配置与当前角色权限共同生成。隐藏菜单不等于撤销权限；撤销访问必须修改角色。
- 服务设置与共享记忆仿写只允许管理员操作。普通用户的视频服务地址仅允许 AutoDL 和 `PERSONAL_AI_WORKFLOW_BASE_URLS` 明确列出的地址。
- 保护覆盖页面、JSON 接口、SSE 对话、图片/缩略图、历史、资产、取消、清空与标注操作。客户端不能通过提交历史记录认领他人的远端任务。
- 普通用户只能追踪自己已由服务端创建的任务，不支持直接输入未知远端任务 ID 导入。
- 所有写接口启用 CSRF：先登录，通过 `GET /api/session` 获取令牌，随后在 `X-CSRFToken` 请求头提交。前端统一自动携带；可附加 `X-Workspace-User` 防止切换账号后旧标签页误操作。
- 新后台不自动导入旧浏览器的无归属聊天/草稿，避免共享设备串号；旧浏览器数据不会被删除。

## 运行与安全配置

- 账号、角色、菜单保存在 `data/accounts.db`；会话签名密钥自动创建在 `data/.session-secret`（权限 600）。备份时保留整个 `data/`、`photo_lab/data/` 和归档作品目录。
- `PERSONAL_AI_STATE_DIR` 可更改账号数据库与会话密钥的目录；不改变业务媒体目录。
- `PERSONAL_AI_SECRET_KEY` 可由外部秘密管理系统提供。生产环境必须使用 HTTPS，并设置 `PERSONAL_AI_COOKIE_SECURE=1`。
- 会话和 CSRF 令牌有效期 8 小时；密码使用 PBKDF2-SHA256（一百万次迭代）；登录限制为每分钟 10 次。
- 当前 JSON 任务队列只支持单进程部署，不要启动多个 WSGI worker 写同一任务文件。多实例扩展前应迁移任务存储/队列与共享限流存储；可通过 `PERSONAL_AI_RATELIMIT_STORAGE_URI` 配置限流后端。
- `PERSONAL_AI_WORKFLOW_BASE_URLS` 使用逗号分隔管理员批准的额外工作流服务完整地址；不允许普通用户任意代理内网地址。
- 丢失管理员访问时，可使用上述 `flask fab create-admin` 命令在本机交互式创建新的管理员。不要把本机开发服务直接暴露到公网。

## API

主工作台（根路径）：

- `GET /api/health`
- `GET /api/history` · `POST /api/history` · `DELETE /api/history?id=...`
- `GET /api/assets`
- `GET /api/service/check?base_url=...`
- `POST /api/comfy/upload/file?base_url=...`
- `POST /api/workflow/generate`
- `GET /api/workflow/result?prompt_id=...&base_url=...`
- `POST /api/frames/generate`（服务端调用 Zero 生成首尾帧）
- `POST /api/chat/completions` · `POST /api/chat/stream`

Photo Lab（`/photo` 前缀）：`/photo/api/health`、`/photo/api/generate`、`/photo/api/tasks` 等，见 `photo_lab/README.md`。

## 凭据

服务端从环境变量读取凭据，不在浏览器端保存或提交密钥。也可以打开
<http://127.0.0.1:4173/settings> 在设置页面写入 **ComfyUI 地址**和 **MiniMax 视频生成 Key**，
保存后写入项目根目录 `.env`（已 gitignore，权限 600）并即时生效，无需重启。

- `AUTODL_ART_TOKEN`：AutoDL H3 视频工作流
- `AZT_API_KEY`：Zero 首尾帧生成
- `COMFY_URL`：Photo Lab 的 ComfyUI 地址（默认 SeetaCloud）
- `QWEN_API_URL` / `QWEN_MODEL`：文本对话后端

AutoDL H3 模式使用 `https://www.autodl.art` 作为服务地址，Workflow ID 为
`minimax_h3_lightx2v_v5_15s`；首尾帧分别映射到 `ref_image_0` 和 `ref_image_1`，
可继续使用 `ref_image_2`、`ref_image_3` 作为连续性参考。
