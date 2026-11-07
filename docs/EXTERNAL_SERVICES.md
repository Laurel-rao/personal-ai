# 外部资源与服务清单

> 维护日期：2026-11-07  
> 适用范围：`server.py`、`dmm_books.py`、`profile_enrich.py`、`admin.py` 及前端页面使用的公开网站和第三方服务。  
> 维护要求：新增/替换外部站点时，**先改这里，再改代码**；每次改动更新日期、调用位置和失败兜底。

## 1. 维护原则

- 外部网站随时可能改版、限流、封 IP 或停止服务；任何抓取都必须有超时、缓存/负缓存和失败兜底，不能把外部可用性当成系统可用性。
- 不在文档、日志、前端写入真实 Key、Cookie、账号密码；凭据只放 `.env` 或外部秘密管理。
- 所有 HTTP 抓取统一走 `NYAA_PROXY` 或 `DMM_PROXY`，不要在代码里硬编码个人代理、内网 IP 或节点名。
- 外部内容仅用于个人资料整理；部署者需自行确认目标站点的服务条款、版权和当地法律要求。
- 站点迁移时，优先改环境变量（`NYAA_BASE`、`JAVDB_BASE`），再改适配器；不要在前端散落 URL。

## 2. 网络分区

| 变量 | 默认 | 用途 |
| --- | --- | --- |
| `NYAA_PROXY` | `http://127.0.0.1:7897` | 番号搜索、JavDatabase、av-wiki、维基、theidolbase、theactorbase、NDL、btdig 等 |
| `DMM_PROXY` | `http://127.0.0.1:7898` | DMM/FANZA 日本出口：书籍试读、DMM 封面、DMM GraphQL、JavDatabase 页面/封面 |
| `DMM_JP_PORT` / `DMM_JP_CTL` / `DMM_JP_DIR` | `7898` / `9098` / `/tmp/dmm-jp` | 仅 macOS 的 `tools/dmm_jp_proxy.sh` 使用 |
| `NYAA_BASE` | `https://sukebei.nyaa.si` | 番号资源搜索根地址 |
| `JAVDB_BASE` | `https://javdb.com` | 目前主要作为 Referer/兼容配置；如启用 JavDB 抓取时使用 |

说明：

- `DMM_PROXY` 为空时，部分 JavDatabase/DMM 代码会回退到 `NYAA_PROXY`；生产环境建议两个都显式配置。
- `tools/dmm_jp_proxy.sh` 依赖 macOS 的 Clash Verge 和 `verge-mihomo`，只适用于本机 macOS。Linux/服务器请使用独立的 HTTP 代理，或直接把 `DMM_PROXY` 指向可访问日本的代理。
- 代理必须是 HTTP/HTTPS 代理（urllib `ProxyHandler` 使用）；SOCKS 代理需先转成 HTTP 混合端口。

## 3. 站点清单

| Key | 站点 / 域名 | 主要调用位置 | 用途 | 代理 | 缓存 / 兜底 | 失败表现 |
| --- | --- | --- | --- | --- | --- | --- |
| `dmm-cover` | `awsimgsrc.dmm.co.jp`、`pics.dmm.co.jp` | `server.py` `_nya_cover_urls()`、`/api/nya/cover`、`/api/player/official-cover` | 影片封面；支持 `pl.jpg`/`ps.jpg`、SOD 的 `1` 前缀、部分标签的 `118` 前缀 | `DMM_PROXY` | `data/nya-covers/`、`data/player/official-thumbs/`；失败负缓存 30 分钟 | 404 返回番号占位；不阻塞其他卡片 |
| `dmm-video` | `video.dmm.co.jp`、`www.dmm.co.jp` | `server.py` DMM GraphQL / 页面抓取 | 女优索引、作品、部分资料 | `DMM_PROXY` | 本地 `dmm-actresses.json`、请求内存缓存 | 保留已有索引，增量失败不致命 |
| `dmm-book` | `book.dmm.co.jp` | `dmm_books.py` | 写真集试读、Publus 瓦片、下载任务 | `DMM_PROXY` → `NYAA_PROXY` | 本地下载目录；图片缓存 | 任务失败，已下载文件保留 |
| `sukebei` | `NYAA_BASE` | `server.py` `_nya_search()`、`/api/nya/search`、`/api/nya/download` | 番号资源搜索、种子/磁力 | `NYAA_PROXY` | `_NYA_SEARCH_CACHE`；DHT 兜底 | 返回 502；前端提示，不影响已有页面 |
| `btdig` | `btdig.com` | `server.py` `_nya_search_btdig()` | DHT 磁力补充 | `NYAA_PROXY`（curl 兜底） | 10 分钟熔断 | 返回空补充结果，不阻断 sukebei 结果 |
| `javdatabase` | `www.javdatabase.com` | `_javdatabase_info()`、`_javdatabase_codes()`、`_javdatabase_cover_bytes()`、`_release_date()` | 发售日、厂牌、女优、封面；ABP/ABW/ABF/CHN 海报兜底 | `DMM_PROXY` | `data/nya-release.json`、封面缓存、负缓存 | 回退 av-wiki/维基；仍失败则空字段 |
| `av-wiki` | `av-wiki.net` | `_avwiki_release()` | 发售日兜底（企划单体覆盖较好） | `NYAA_PROXY` | `data/nya-release.json` | 返回空日期 |
| `wikipedia` | `ja.wikipedia.org` | `_wiki_release()` | 发售日最后兜底 | `NYAA_PROXY` | `data/nya-release.json` | 返回空日期 |
| `theidolbase` | `www.theidolbase.com`、`image.yingzhiben.info` | `_idolbase_profile()`、`_idolbase_gallery()`、`_ensure_player_avatar()` | 女优资料、写真画廊、480×600 半身头像 | `NYAA_PROXY` | 本地照片缓存、`data/amxiaolin/avatars/` | 返回空资料/跳过来源，保留 DMM 125px 小图 |
| `theactorbase` | `www.theactorbase.com`、`image.theactorbase.com` | `_actorbase_works()`、`_actorbase_images()` | 精确作品表、日常照 | `NYAA_PROXY` | 本地照片缓存 | 返回空作品/图片 |
| `ndl` | `ndlsearch.ndl.go.jp` | `_ndl_books()` | 写真集书目检索（NDL OpenSearch） | `NYAA_PROXY` | 请求缓存 | 返回空书目 |
| `all4jp` | `all4jp.com` | `_all4jp_images()` | 写真图备用源 | `NYAA_PROXY` | 本地照片缓存 | 跳过该来源 |
| `agency-sources` | `t-powers.co.jp`、`life-promotion.com`、`linx.live` | `_profile_source_images()` 等 | 事务所/写真图备用源 | `NYAA_PROXY` | 本地照片缓存 | 跳过该来源 |
| `gravure-sources` | `wpb.shueisha.co.jp`、`nikkan-spa.jp`、`menscyzo.com` | `_profile_source_images()` 等 | 写真图备用源 | `NYAA_PROXY` | 本地照片缓存 | 跳过该来源 |
| `javdb` | `JAVDB_BASE` | DMM/JavDatabase 请求的 Referer；预留数据源 | 兼容/预留 | `NYAA_PROXY` | — | 不作为关键路径 |
| `ipinfo` | `ipinfo.io` | `dmm_books.check_proxy()` | 代理出口国家检测 | `DMM_PROXY` | 设置页即时检测 | 检测失败仅提示，不阻断服务 |
| `ai-reeko` | `ai.reeko.net.cn` | `ZERO_IMAGE_BASE_URL` | H3 首尾帧生成 | 直连/按部署网络 | 服务端凭据 | 生成失败，任务报错 |
| `autodl` | `www.autodl.art` | H3 视频工作流 | 视频生成后端 | 直连 | 服务端 Token | 连接检查失败 |
| `seetacloud` | `*.seetacloud.com` | Photo Lab 图片直出 | 图片生成 | 直连/SSH 隧道 | 服务端 Key | 请求失败 |
| `comfyui` | `COMFY_URL` | Photo Lab | ComfyUI 工作流 | 直连/隧道 | 服务端 | 请求失败 |
| `qwen` | `QWEN_API_URL` | 文本对话 | 文本模型 | 直连 | 服务端 | 请求失败 |

> 上表是**当前代码实际引用**的站点，不是推荐抓取列表。站点的可用性、授权和内容合规由部署者自行确认。

## 4. 本地缓存与数据文件

| 路径 | 内容 | 是否可删 | 刷新方式 |
| --- | --- | --- | --- |
| `data/nya-covers/` | DMM/JavDatabase 封面缓存、`medium/` 中图 | 可删 | 删除后自动重建 |
| `data/nya-release.json` | 发售日/女优/厂牌缓存 | 可删 | 删除后重新抓取 |
| `data/player/official-thumbs/` | 视频官方封面/中图缓存 | 可删 | 删除后自动重建 |
| `data/player/thumbs/` | 本地视频截帧 | 可删 | 重新生成 |
| `data/player/catalog.json` | 视频资料 | 建议备份 | 重新采集 |
| `data/player/technical.json` | 时长/分辨率/编码 | 可重建 | `collect_media_technical.py` |
| `data/player/cover-refresh.json` | 封面定时任务上次成功时间 | 可删 | 删除会触发下次更新 |
| `data/player/hidden-videos.json` | 视频隐藏列表 | 建议备份 | 页面右键恢复 |
| `data/player/player-overrides.json` | DMM ID/评分覆盖层 | **建议备份** | 页面编辑 |
| `data/amxiaolin/dmm-actresses.json` | DMM 女优索引 | 可重建 | 索引脚本 |
| `data/amxiaolin/players-merged.json` | 合并后的选手数据 | **备份** | 数据导入流程 |
| `data/amxiaolin/player-user.json` | 手动添加的选手 | **备份** | 页面添加 |
| `data/amxiaolin/photos/` | 选手写真缓存 | 可删 | 重新抓取 |
| `data/amxiaolin/avatars/` | 高清半身头像缓存（theidolbase） | 可删 | 详情页自动重建 |
| `data/amxiaolin/avatar-meta.json` | 头像来源/尺寸/失败记录 | 可删 | 删除后重新抓取 |
| `data/accounts.db` | 账号/角色/菜单 | **必须备份** | 用户管理 |
| `data/.session-secret` | 会话签名密钥 | **必须备份** | 丢失会导致登录失效 |
| `NYAA_DIR` | 番号种子/下载 | 自行管理 | 迅雷/下载器 |
| `LOCAL_PHOTO_DIR` | 本地写真集；`.trash/` 为回收站 | 自行管理 | 页面下载/删除 |

旧数据清理前先备份；`data/`、`~/Movies`、`NYAA_DIR`、`LOCAL_PHOTO_DIR` 通常不在 Git 中。

## 5. 维护流程

### 每月/每次升级

1. 运行 `python tools/check_deployment.py --network`，确认代理、目录、ffmpeg 和关键站点可达。
2. 抽查搜索、封面、发售信息、女优名和写真下载是否仍正常。
3. 检查本文件顶部的维护日期是否需要更新。

### 站点改版时

1. 先定位调用函数（上表“主要调用位置”）。
2. 只改适配器里的 URL/解析器，不把站点细节扩散到前端。
3. 更新缓存 key 或封面 `v=` 参数，避免浏览器/磁盘缓存旧结果。
4. 为解析器补一个离线 fixture 测试；至少保留一份真实 HTML 样本。
5. 更新本文件的域名、代理、缓存和失败兜底。
6. 重新运行 `tools/check_deployment.py --network` 和相关测试。

### 站点不可用时的临时处置

- 封面：保留已有缓存；清空负缓存或等待 30 分钟；必要时返回番号占位。
- 搜索：保留 sukebei；btdig 熔断不影响主结果。
- 发售信息：回退 av-wiki/维基；仍无则空字段，不阻塞页面。
- 写真：任务失败保留已下载文件，可从任务中心重试。

## 6. 后续改造建议

当前多数 URL 仍直接写在函数里。建议下一轮拆成适配器：

```text
external/
  registry.py        # 站点、env、代理、超时、缓存 TTL 的单一来源
  http.py            # 统一 proxy/timeout/retry/circuit breaker/日志
  providers/
    dmm_cover.py
    dmm_book.py
    nyaa.py
    btdig.py
    release.py       # javdatabase -> av-wiki -> wikipedia
    profile.py       # theidolbase / theactorbase / agency / gravure
    library.py       # NDL
```

目标：

- 所有域名、超时、缓存 TTL、负缓存、代理名从 `registry.py` 读取。
- Provider 只返回结构化数据，不直接写页面/任务。
- 每个 Provider 有离线 fixture 测试和失败降级测试。
- 前端不再拼外部 URL；封面/搜索/下载都走后端适配器。
- 部署时可用环境变量切换站点/代理，不需要改代码。
- 外部失败计入日志和设置页诊断，而不是静默变空。

在完成前，本文档 + `tools/check_deployment.py` 就是维护入口。
