# Personal AI 工作台

统一 Flask 启动，单进程、单端口同时提供 H3 视频工作台与 Photo Lab。

## 启动

```bash
pip install -r requirements.txt
python3 app.py --host 127.0.0.1 --port 4173
```

浏览器访问：

- <http://127.0.0.1:4173/> —— H3 视频工作台（视频生成 / 文本对话 / 首尾帧）
- <http://127.0.0.1:4173/photo/> —— Photo Lab（ComfyUI 图片生成，前缀挂载）

## 结构

| 入口 | 说明 |
| --- | --- |
| `app.py` | 统一 Flask 入口，注册 console 蓝图 + `/photo` 前缀挂载 Photo Lab |
| `server.py` | H3 视频工作台 Flask 蓝图（`console_bp`），也可独立运行 |
| `photo_lab/app.py` | Photo Lab 独立 Flask 应用，可随统一入口挂载，也可单独运行（默认 4174） |

页面中的服务地址和 Workflow ID 都可以动态修改并保存在当前浏览器。任务历史由后端持久化到 `data/history.json`，资产库会从已完成任务的接口结果中自动汇总图片和视频链接；Photo Lab 任务记录在 `photo_lab/data/tasks.json`。

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