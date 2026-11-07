# 部署与迁移指南

> 维护日期：2026-11-07  
> 目标：在另一台 macOS / Linux 服务器上可复现地启动，并明确单进程、代理、媒体目录和外部依赖的边界。

## 1. 支持范围

| 项目 | 要求 |
| --- | --- |
| Python | 3.9+（当前开发环境 3.9） |
| 依赖 | `pip install -r requirements.txt` |
| 视频参数 | `ffmpeg` / `ffprobe` 在 `PATH` 中（可选，但视频技术信息需要） |
| 数据库 | SQLite（Flask-AppBuilder 账号库） |
| 反向代理 | 生产建议 Nginx/Caddy + HTTPS |
| 进程模型 | **单进程**；任务队列、封面定时器、下载 worker 都在进程内 |
| 迅雷 | macOS 可选；Linux 建议只保存种子或配置 `THUNDER_CMD` |
| 代理 | 一个 HTTP 代理给番号/资料站，一个 HTTP 代理给 DMM 日本出口（可相同） |

不要直接把 Flask 开发服务器暴露到公网。生产至少放在 Nginx/Caddy 后面，并启用 HTTPS。

## 2. 目录规划

推荐把**代码**和**持久数据**分开：

```text
/opt/personal-ai/                 # 代码 + .venv
/opt/personal-ai/data/            # 账号、选手、任务、缓存（持久卷）
/opt/personal-ai/photo_lab/data/  # Photo Lab 任务/作品
/srv/media/Movies/                # MOVIES_DIR：视频片库根目录
/srv/media/Videos/                # NYAA_DIR：番号下载
/srv/media/写真/                   # LOCAL_PHOTO_DIR：本地写真集
```

至少保证这些目录对运行用户可写：

- `data/`（账号、任务、缓存、密钥）
- `photo_lab/data/`
- `MOVIES_DIR`
- `NYAA_DIR`
- `LOCAL_PHOTO_DIR` 及其 `.trash/`

`MOVIES_DIR`、`NYAA_DIR`、`LOCAL_PHOTO_DIR` 支持环境变量覆盖；不要在代码里写死个人路径。

## 3. 首次部署

```bash
cd /opt/personal-ai
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env
chmod 600 .env
# 编辑 .env：至少检查 MOVIES_DIR / NYAA_DIR / LOCAL_PHOTO_DIR / 代理 / THUNDER_ENABLED

# 创建首个管理员（交互式，不会生成默认密码）
.venv/bin/flask --app app:create_app fab create-admin

# 本地部署自检（目录、依赖、代理）
.venv/bin/python tools/check_deployment.py

# 网络自检（需要代理已启动；会请求外部站点）
.venv/bin/python tools/check_deployment.py --network

# 启动
.venv/bin/python app.py --host 127.0.0.1 --port 4173
```

浏览器访问 `http://127.0.0.1:4173/`，登录后按角色授权菜单和功能。

### 首次启动会生成/需要的东西

- `data/accounts.db`：账号、角色、菜单。
- `data/.session-secret`：会话签名密钥；丢失会导致所有登录失效。
- `data/amxiaolin/dmm-actresses.json`：DMM 女优索引；没有它时添加选手只能手填。
- `data/player/`：片库资料/缓存；首次访问会创建。
- `data/nya-covers/`：封面缓存；按需创建。

## 4. .env 关键项

完整示例见 [`.env.example`](../.env.example)。

| 变量 | 说明 |
| --- | --- |
| `MOVIES_DIR` | 视频片库根目录；会递归扫描视频扩展名 |
| `NYAA_DIR` | 番号种子/下载保存目录 |
| `LOCAL_PHOTO_DIR` | 本地写真集根目录，删除进 `.trash/` |
| `NYAA_PROXY` | 番号/资料站 HTTP 代理 |
| `DMM_PROXY` | DMM/FANZA 日本出口 HTTP 代理 |
| `NYAA_BASE` | sukebei 根地址（迁移时改） |
| `JAVDB_BASE` | JavDB 根地址/Referer 兼容 |
| `THUNDER_ENABLED` | `0` = 只保存 `.torrent`，不调用下载器 |
| `THUNDER_APP` | macOS 迅雷应用名 |
| `THUNDER_CMD` | 跨平台下载器命令；目标路径作为最后一个参数 |
| `VIDEO_COVER_REFRESH_SECONDS` | 封面定时刷新间隔，最小 3600 |
| `AVATAR_WARM_ON_START` | 启动后后台补手动选手高清头像；`0` 关闭 |
| `PERSONAL_AI_STATE_DIR` | 账号库/会话密钥目录；默认 `data/` |
| `PERSONAL_AI_SECRET_KEY` | 外部秘密管理提供；留空自动生成 |
| `PERSONAL_AI_COOKIE_SECURE` | HTTPS 部署设为 `1` |
| `PERSONAL_AI_RATELIMIT_STORAGE_URI` | 多实例时共享限流后端；单进程可留空 |
| `AUTODL_ART_TOKEN` / `AZT_API_KEY` | AI 工作流凭据 |
| `COMFY_URL` / `SEETACLOUD_*` / `QWEN_*` | Photo Lab / 对话后端 |

## 5. 代理

### macOS 本机

- `tools/dmm_jp_proxy.sh` 复用 Clash Verge 的 JP 节点，在 `127.0.0.1:7898` 起独立 mihomo。
- `NYAA_PROXY` 通常指向 Clash 的混合端口 `7897`。
- 设置页可以检测 DMM 代理出口；脚本只在 macOS 且有 Clash Verge 的机器上可用。

### Linux / 云服务器

- 不要直接依赖 macOS 脚本；在服务器上运行 Clash/mihomo/squid 等 HTTP 代理，或使用云厂商的出口代理。
- `.env` 示例：

```dotenv
NYAA_PROXY=http://127.0.0.1:7897
DMM_PROXY=http://127.0.0.1:7898
```

- 两个站点组可以共用同一个代理；如果 DMM 要求日本 IP，则 `DMM_PROXY` 必须是日本出口。
- 代理不可用时，外部搜索/封面会失败；应用本身仍能打开。

## 6. 迅雷 / Linux 下载

macOS 默认：

```dotenv
THUNDER_ENABLED=1
THUNDER_APP=Thunder
```

Linux 推荐：

```dotenv
THUNDER_ENABLED=0
```

此时「送迅雷」会下载 `.torrent` 到 `NYAA_DIR/<番号>/`，不调用外部应用；可在页面/文件夹手动打开。任务仍会记录种子路径。

如要自动交给 Linux 下载器：

```dotenv
THUNDER_ENABLED=1
THUNDER_CMD=transmission-gtk
```

程序会以 `THUNDER_CMD` 拆分后的参数 + 种子路径执行，不经过 shell。请确保该命令在运行用户 `PATH` 中。

磁力链接没有对应 `.torrent` 文件时，必须配置 `THUNDER_CMD` 才能发送；否则接口返回明确错误，不会伪造成功。

## 7. systemd 示例

```ini
[Unit]
Description=Personal AI Console
After=network-online.target

[Service]
Type=simple
User=personalai
Group=personalai
WorkingDirectory=/opt/personal-ai
EnvironmentFile=/opt/personal-ai/.env
ExecStart=/opt/personal-ai/.venv/bin/python app.py --host 127.0.0.1 --port 4173
Restart=on-failure
RestartSec=3
# 媒体目录较大时按需调整
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now personal-ai
sudo journalctl -u personal-ai -f
```

**只启动一个进程。** 当前任务队列/封面调度/下载 worker 都在进程内；多 worker 会重复执行任务、争用 SQLite 和写文件。需要横向扩展时，先迁移任务存储和调度器。

## 8. Nginx + HTTPS

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    client_max_body_size 200m;

    location / {
        proxy_pass http://127.0.0.1:4173;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    # SSE / 流式对话
    location /api/chat/stream {
        proxy_pass http://127.0.0.1:4173;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }
}
```

HTTPS 时同步设置：

```dotenv
PERSONAL_AI_COOKIE_SECURE=1
```

## 9. 数据备份与迁移

必须备份：

- `data/` 整个目录（账号、选手、任务、覆盖层、缓存可重建但建议保留）
- `photo_lab/data/`
- `LOCAL_PHOTO_DIR`
- `NYAA_DIR`（下载文件/种子）
- `.env`（含密钥；不要提交 Git）
- `MOVIES_DIR`（视频片库本身）

迁移步骤：

1. 停旧服务。
2. 复制代码 + `.env` + 上述数据目录，保持相对路径一致。
3. 新机创建运行用户，修正目录属主。
4. `pip install -r requirements.txt`。
5. `python tools/check_deployment.py --network`。
6. 启动并检查 `/api/health`、登录、片库、资源搜索、封面、一次下载。
7. 确认正常后再切 DNS/反代。

## 10. 升级与回滚

```bash
cd /opt/personal-ai
git pull --ff-only
.venv/bin/pip install -r requirements.txt
sudo systemctl restart personal-ai
```

- 升级前备份 `data/` 和 `.env`。
- 封面/资料缓存不兼容时可以删除 `data/nya-covers/`、`data/nya-release.json`、`data/player/official-thumbs/`。
- 回滚代码后保留旧数据；如数据结构变更，按发布说明恢复备份。

## 11. 自检

```bash
# 本地检查：Python/依赖/目录/ffmpeg/代理端口/迅雷配置
.venv/bin/python tools/check_deployment.py

# 网络检查：代理 + 关键站点
.venv/bin/python tools/check_deployment.py --network

# 应用健康
curl -fsS http://127.0.0.1:4173/api/health
```

外部站点的变更和替换流程见 [外部资源与服务清单](EXTERNAL_SERVICES.md)。

## 12. 已知限制

- 单进程任务队列；不要用多 worker。
- 封面定时器在进程启动后运行；重启会重置等待窗口，但会读取上次成功时间。
- macOS 的 `Media.app`、开机启动和 `tools/dmm_jp_proxy.sh` 不可直接迁移到 Linux。
- DMM/番号站点的可用性取决于代理出口和站点策略；失败时应用降级，不保证外部内容始终可用。
- 生产环境必须自行处理 HTTPS、备份、访问控制和内容合规。
