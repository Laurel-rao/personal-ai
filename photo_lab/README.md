# Photo Lab

Flask + ComfyUI 异步图片生成工作台。默认调用用户提供的 SeetaCloud ComfyUI 地址，也可以通过 `COMFY_URL` 覆盖。

## 启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
COMFY_URL='https://u288331-788499bf7eab.bjb1.seetacloud.com:8443' python app.py
```

打开 <http://127.0.0.1:4173>。

任务记录保存在 `data/tasks.json`，生成结果通过 Flask 的 `/api/tasks/<id>/image` 代理，不需要把 ComfyUI 文件系统暴露给浏览器。

## API

- `GET /api/health`：检查 ComfyUI 连接与 GPU。
- `GET /api/tasks`：最近 50 条任务。
- `POST /api/generate`：提交 `{prompt, negative_prompt, width, height, seed}`，返回 `202` 和任务 ID。
- `GET /api/tasks/<id>`：查看队列、进度和输出。
- `POST /api/tasks/<id>/cancel`：取消排队或正在执行的任务。
- `DELETE /api/tasks/history`：清理已完成和失败的历史记录。

进度优先来自 ComfyUI WebSocket 的 `progress` 事件；若 WebSocket 不可用，会自动降级为历史轮询和时间估算。生产环境建议在应用前增加鉴权，并限制 `/interrupt` 的调用权限。
