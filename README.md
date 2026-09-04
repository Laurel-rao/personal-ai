# H3 视频工作台

启动本地服务：

```bash
python3 server.py --host 127.0.0.1 --port 4173
```

浏览器访问：

```text
http://127.0.0.1:4173/
```

页面中的服务地址和 Workflow ID 都可以动态修改并保存在当前浏览器。任务历史由后端持久化到 `data/history.json`，资产库会从已完成任务的接口结果中自动汇总图片和视频链接。

后端提供以下本地接口：

- `GET /api/health`
- `GET /api/history`
- `POST /api/history`
- `DELETE /api/history?id=...`
- `GET /api/assets`
- `GET /api/service/check?base_url=...`
- `POST /api/comfy/upload/file?base_url=...`
- `POST /api/workflow/generate`
- `GET /api/workflow/result?prompt_id=...&base_url=...`
- `POST /api/frames/generate`（服务端调用 Zero 生成首尾帧）

AutoDL H3 模式使用 `https://www.autodl.art` 作为服务地址，Workflow ID 为
`minimax_h3_lightx2v_v5_15s`。服务端从 `AUTODL_ART_TOKEN` 和 `AZT_API_KEY`
读取凭据，不在浏览器端保存或提交密钥；首尾帧分别映射到 `ref_image_0` 和
`ref_image_1`，可继续使用 `ref_image_2`、`ref_image_3` 作为连续性参考。
