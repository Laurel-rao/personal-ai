import copy
import json
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
try:
    import websocket
except ImportError:  # WebSocket 不可用时自动回退到轮询
    websocket = None


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
TASKS_FILE = DATA_DIR / "tasks.json"
LABELS_FILE = DATA_DIR / "labels.json"
WORKFLOW_FILE = ROOT / "workflow.json"
OUTPUTS_DIR = ROOT / "outputs"
ARCHIVE_DIR = DATA_DIR / "images"
ARCHIVE_DIR.mkdir(exist_ok=True)
COMFY_URL = os.getenv(
    "COMFY_URL",
    "https://u288331-788499bf7eab.bjb1.seetacloud.com:8443",
).rstrip("/")
QWEN_API_URL = os.getenv(
    "QWEN_API_URL",
    "https://uu288331-788499bf7eab.bjb1.seetacloud.com:8443/v1",
).rstrip("/")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen3:4b")

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)
http = requests.Session()
lock = threading.RLock()
tasks = {}
labels = {}
queue = []
worker_wakeup = threading.Event()


def now():
    return datetime.now(timezone.utc).isoformat()


def load_tasks():
    global tasks, queue
    if TASKS_FILE.exists():
        try:
            tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            tasks = {}
    for task_id, item in sorted(tasks.items(), key=lambda pair: pair[1].get("created_at", "")):
        if item.get("status") not in {"queued", "running"} or item.get("cancel_requested"):
            continue
        if item.get("status") == "running":
            item["message"] = "服务恢复，继续监控 ComfyUI 任务"
        else:
            item["message"] = "服务恢复，等待执行"
        item["updated_at"] = now()
        queue.append(task_id)
    save_tasks()


def load_labels():
    global labels
    if LABELS_FILE.exists():
        try:
            labels = json.loads(LABELS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            labels = {}


def save_labels():
    tmp = LABELS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LABELS_FILE)


def save_tasks():
    tmp = TASKS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TASKS_FILE)


def load_workflow():
    return json.loads(WORKFLOW_FILE.read_text(encoding="utf-8"))


def update_task(task_id, **changes):
    with lock:
        if task_id not in tasks:
            return
        tasks[task_id].update(changes, updated_at=now())
        save_tasks()


def make_workflow(payload):
    workflow = copy.deepcopy(load_workflow())
    workflow["6"]["inputs"]["text"] = payload.get("prompt", "")
    workflow["7"]["inputs"]["text"] = payload.get("negative_prompt", "blurry ugly bad")
    workflow["3"]["inputs"]["seed"] = int(payload["seed"])
    workflow["13"]["inputs"]["width"] = int(payload.get("width", 1024))
    workflow["13"]["inputs"]["height"] = int(payload.get("height", 1024))
    workflow["13"]["inputs"]["batch_size"] = int(payload.get("batch_size", 1))
    workflow["9"]["inputs"]["filename_prefix"] = f"PhotoLab/{payload.get('filename_prefix', 'result')}"
    return workflow


def local_image_path(task_id, image):
    """Return an archived image, including the legacy one-file browser cache."""
    filename = Path(str(image.get("local_filename") or image.get("filename") or "")).name
    if filename:
        archived = ARCHIVE_DIR / task_id / filename
        if archived.is_file():
            return archived
    legacy = DATA_DIR / f"{task_id}.png"
    return legacy if legacy.is_file() else None


def archive_images(task_id, images):
    """Copy ComfyUI outputs locally before a completed task becomes history."""
    destination = ARCHIVE_DIR / task_id
    destination.mkdir(parents=True, exist_ok=True)
    archived_images = []
    for position, image in enumerate(images, start=1):
        filename = Path(str(image.get("filename") or f"image-{position}.png")).name
        target = destination / filename
        params = {key: image[key] for key in ("filename", "subfolder", "type") if image.get(key)}
        if not target.is_file():
            response = http.get(f"{COMFY_URL}/view", params=params, timeout=60, stream=True)
            response.raise_for_status()
            temporary = target.with_suffix(f"{target.suffix}.tmp")
            with temporary.open("wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file.write(chunk)
            temporary.replace(target)
        archived_images.append({**image, "local_filename": filename})
    return archived_images


def worker():
    while True:
        with lock:
            task_id = queue.pop(0) if queue else None
        if not task_id:
            worker_wakeup.wait(1)
            worker_wakeup.clear()
            continue
        run_task(task_id)


def run_task(task_id):
    task = tasks[task_id]
    ws = None
    try:
        if task.get("cancel_requested"):
            update_task(task_id, status="cancelled", progress=0, message="任务已取消")
            return
        comfy_id = task.get("comfy_prompt_id")
        if comfy_id:
            update_task(
                task_id,
                status="running",
                progress=max(24, int(task.get("progress", 0))),
                message="恢复监控 ComfyUI 任务",
            )
        else:
            update_task(task_id, status="running", progress=8, message="正在提交到 ComfyUI")
            response = http.post(
                f"{COMFY_URL}/prompt",
                json={"prompt": task["workflow"], "client_id": task_id},
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            if result.get("node_errors"):
                raise RuntimeError(json.dumps(result["node_errors"], ensure_ascii=False))
            comfy_id = result["prompt_id"]
            update_task(
                task_id,
                comfy_prompt_id=comfy_id,
                started_at=now(),
                progress=24,
                message="已进入生成队列",
            )

        if websocket:
            parsed = urlparse(COMFY_URL)
            ws_scheme = "wss" if parsed.scheme == "https" else "ws"
            ws_url = f"{ws_scheme}://{parsed.netloc}/ws?clientId={quote(task_id)}"
            try:
                ws = websocket.create_connection(ws_url, timeout=1)
            except Exception:
                ws = None

        started = time.monotonic()
        while True:
            if tasks.get(task_id, {}).get("cancel_requested"):
                http.post(f"{COMFY_URL}/interrupt", timeout=10)
                update_task(task_id, status="cancelled", progress=0, message="任务已取消")
                return
            if ws:
                try:
                    raw = ws.recv()
                    if isinstance(raw, str):
                        event = json.loads(raw)
                        data = event.get("data", {})
                        if event.get("type") == "progress" and data.get("prompt_id") == comfy_id:
                            maximum = max(1, int(data.get("max", 1)))
                            value = min(maximum, int(data.get("value", 0)))
                            update_task(task_id, progress=24 + int(value / maximum * 72), message=f"采样中 · {value}/{maximum}")
                        elif event.get("type") == "executing" and data.get("prompt_id") == comfy_id:
                            update_task(task_id, message=f"执行节点 {data.get('node') or '收尾'}")
                except Exception as exc:
                    if websocket and isinstance(exc, websocket.WebSocketTimeoutException):
                        pass
                    else:
                        ws = None
            history = http.get(f"{COMFY_URL}/history/{comfy_id}", timeout=20).json()
            record = history.get(comfy_id)
            if record:
                status = record.get("status", {}).get("status_str")
                outputs = record.get("outputs", {})
                if status == "error":
                    raise RuntimeError(record.get("status", {}).get("messages", "ComfyUI 执行失败"))
                if status == "success" or outputs:
                    images = []
                    for node_output in outputs.values():
                        images.extend(node_output.get("images", []))
                    archived_images = archive_images(task_id, images)
                    update_task(
                        task_id,
                        status="success",
                        progress=100,
                        message="生成完成，已归档到本地",
                        outputs=archived_images,
                        archived_at=now(),
                        duration=round(time.monotonic() - started, 1),
                        completed_at=now(),
                    )
                    return
            elapsed = time.monotonic() - started
            estimated = min(92, 24 + int(elapsed / 2))
            current = tasks.get(task_id, {}).get("progress", 24)
            update_task(task_id, progress=max(current, estimated), message="模型生成中" if current <= estimated else tasks.get(task_id, {}).get("message", "模型生成中"))
            time.sleep(1)
    except Exception as exc:
        update_task(task_id, status="error", progress=0, message=str(exc), completed_at=now())
    finally:
        if ws:
            ws.close()


def public_task(task):
    result = {k: v for k, v in task.items() if k != "workflow"}
    prefix = request.script_root.rstrip("/")
    result["outputs"] = [
        {**image, "url": f"{prefix}/api/tasks/{task['id']}/image?filename={image['filename']}"}
        for image in task.get("outputs", [])
    ]
    return result


def history_items():
    """Return persisted generated images, with one history row per image."""
    prefix = request.script_root.rstrip("/")
    items = []
    for task in tasks.values():
        if task.get("status") not in {"success", "error", "cancelled"}:
            continue
        outputs = task.get("outputs", [])
        if outputs:
            for image in outputs:
                item = public_task(task)
                item["id"] = f"task:{task['id']}:{image.get('filename', '')}"
                item["task_id"] = task["id"]
                item["outputs"] = [{
                    **image,
                    "url": f"{prefix}/api/tasks/{task['id']}/image?filename={image.get('filename', '')}",
                }]
                items.append(item)
        else:
            items.append(public_task(task))
    if OUTPUTS_DIR.exists():
        for image_path in OUTPUTS_DIR.rglob("*"):
            if not image_path.is_file() or image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            relative = image_path.relative_to(OUTPUTS_DIR).as_posix()
            items.append({
                "id": f"file:{relative}",
                "status": "success",
                "prompt": image_path.parent.name,
                "created_at": datetime.fromtimestamp(image_path.stat().st_mtime, timezone.utc).isoformat(),
                "outputs": [{
                    "filename": image_path.name,
                    "url": f"{prefix}/api/library-image/{relative}",
                }],
                "source": "本地归档",
            })
    return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)


def review_items():
    """Return every local task result and Skill output with stable IDs for annotation."""
    prefix = request.script_root.rstrip("/")
    items = []
    for task in tasks.values():
        if task.get("status") != "success":
            continue
        for image in task.get("outputs", []):
            image_id = f"task:{task['id']}:{image.get('filename')}"
            items.append({
                "id": image_id,
                "url": f"{prefix}/api/tasks/{task['id']}/image?filename={image.get('filename')}",
                "prompt": task.get("prompt", ""),
                "created_at": task.get("created_at"),
                "source": "Photo Lab",
                "label": labels.get(image_id, {}).get("value"),
            })
    if OUTPUTS_DIR.exists():
        for image_path in OUTPUTS_DIR.rglob("*"):
            if not image_path.is_file() or image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            relative = image_path.relative_to(OUTPUTS_DIR).as_posix()
            image_id = f"file:{relative}"
            items.append({
                "id": image_id,
                "url": f"{prefix}/api/library-image/{relative}",
                "prompt": image_path.parent.name,
                "created_at": datetime.fromtimestamp(image_path.stat().st_mtime, timezone.utc).isoformat(),
                "source": "Skill 输出",
                "label": labels.get(image_id, {}).get("value"),
            })
    return sorted(items, key=lambda item: item.get("created_at") or "")


@app.get("/")
def index():
    return render_template("index.html", embedded=request.args.get("embedded") == "1")


@app.get("/review")
def review():
    return render_template("review.html", embedded=request.args.get("embedded") == "1")


@app.get("/chat")
def chat():
    return render_template("chat.html")


@app.get("/api/health")
def health():
    try:
        result = http.get(f"{COMFY_URL}/system_stats", timeout=8).json()
        device = (result.get("devices") or [{}])[0]
        return jsonify({"ok": True, "comfy_url": COMFY_URL, "version": result.get("system", {}).get("comfyui_version"), "device": device.get("name")})
    except requests.RequestException as exc:
        return jsonify({"ok": False, "comfy_url": COMFY_URL, "error": str(exc)}), 502


@app.get("/api/chat/health")
def chat_health():
    """Expose Qwen availability without revealing its public endpoint to the browser."""
    try:
        response = http.get(f"{QWEN_API_URL}/models", timeout=15)
        response.raise_for_status()
        models = response.json().get("data", [])
        return jsonify({
            "ok": True,
            "model": QWEN_MODEL,
            "available_models": [item.get("id") for item in models if item.get("id")],
        })
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"ok": False, "model": QWEN_MODEL, "error": str(exc)}), 502


def chat_messages(payload):
    messages = payload.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 40:
        raise ValueError("messages 必须为 1 到 40 条")
    cleaned = []
    total_characters = 0
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("消息格式无效")
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            raise ValueError("消息角色或内容无效")
        content = content.strip()
        if not content or len(content) > 12000:
            raise ValueError("单条消息须为 1 到 12000 个字符")
        total_characters += len(content)
        cleaned.append({"role": role, "content": content})
    if total_characters > 36000:
        raise ValueError("对话总长度不能超过 36000 个字符")
    return cleaned


@app.post("/api/chat/completions")
def chat_completions():
    payload = request.get_json(silent=True) or {}
    try:
        messages = chat_messages(payload)
        temperature = float(payload.get("temperature", 0.7))
        max_tokens = int(payload.get("max_tokens", 1024))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    if not 0 <= temperature <= 2:
        return jsonify({"error": "temperature 必须在 0 到 2 之间"}), 400
    if not 64 <= max_tokens <= 2048:
        return jsonify({"error": "max_tokens 必须在 64 到 2048 之间"}), 400
    try:
        response = http.post(
            f"{QWEN_API_URL}/chat/completions",
            json={
                "model": QWEN_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=180,
        )
        response.raise_for_status()
        result = response.json()
    except requests.HTTPError as exc:
        body = exc.response.text[:1000] if exc.response is not None else ""
        return jsonify({"error": "Qwen 请求失败", "detail": body}), 502
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"error": "Qwen 服务不可用", "detail": str(exc)}), 502
    return jsonify(result)


@app.get("/api/tasks")
def list_tasks():
    include_history = request.args.get("include_history") == "1"
    try:
        history_page = max(1, int(request.args.get("history_page", 1)))
        history_page_size = min(50, max(1, int(request.args.get("history_page_size", 10))))
    except ValueError:
        return jsonify({"error": "分页参数必须是数字"}), 400
    with lock:
        items = sorted(tasks.values(), key=lambda item: item.get("created_at", ""), reverse=True)
        active_items = [item for item in items if item.get("status") in {"queued", "running"}]
        response = {
            "items": [public_task(item) for item in active_items],
            "active_items": [public_task(item) for item in active_items],
        }
        if not include_history:
            return jsonify(response)
        completed_items = history_items()
        history_total = len(completed_items)
        history_pages = max(1, (history_total + history_page_size - 1) // history_page_size)
        history_page = min(history_page, history_pages)
        history_start = (history_page - 1) * history_page_size
        response["history"] = {
            "items": completed_items[history_start:history_start + history_page_size],
            "page": history_page,
            "page_size": history_page_size,
            "total": history_total,
            "total_pages": history_pages,
        }
        return jsonify(response)


@app.get("/api/tasks/<task_id>")
def get_task(task_id):
    with lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404
        return jsonify(public_task(task))


def generation_parameters(payload):
    try:
        width = int(payload.get("width", 1024))
        height = int(payload.get("height", 1024))
        batch_size = int(payload.get("batch_size", 1))
    except (TypeError, ValueError):
        raise ValueError("宽度、高度和批量大小必须是数字")
    if width < 64 or width > 2048 or height < 64 or height > 2048:
        raise ValueError("宽度和高度必须在 64 到 2048 之间")
    if width % 8 or height % 8:
        raise ValueError("宽度和高度必须是 8 的倍数")
    if batch_size < 1 or batch_size > 8:
        raise ValueError("批量大小必须在 1 到 8 之间")
    return width, height, batch_size


def create_generation_task(payload, prompt, width, height, batch_size):
    task_id = str(uuid.uuid4())
    requested_seed = payload.get("seed")
    seed = secrets.randbelow(2**32) if requested_seed in (None, "") else int(requested_seed)
    workflow_payload = {**payload, "prompt": prompt, "seed": seed}
    task = {
        "id": task_id,
        "status": "queued",
        "progress": 0,
        "message": "等待执行",
        "prompt": prompt,
        "negative_prompt": payload.get("negative_prompt", "blurry ugly bad"),
        "width": width,
        "height": height,
        "batch_size": batch_size,
        "seed": seed,
        "filename_prefix": payload.get("filename_prefix", "result"),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        "created_at": now(),
        "updated_at": now(),
        "workflow": make_workflow(workflow_payload),
        "outputs": [],
        "cancel_requested": False,
    }
    return task


@app.post("/api/generate")
def generate():
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        return jsonify({"error": "请输入正向提示词"}), 400
    try:
        width, height, batch_size = generation_parameters(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    task = create_generation_task(payload, prompt, width, height, batch_size)
    with lock:
        tasks[task["id"]] = task
        queue.append(task["id"])
        save_tasks()
    worker_wakeup.set()
    return jsonify(public_task(task)), 202


@app.post("/api/generate/batch")
def generate_batch():
    payload = request.get_json(silent=True) or {}
    prompts = payload.get("prompts")
    if not isinstance(prompts, list):
        return jsonify({"error": "批量提示词必须一行一条"}), 400
    prompts = [str(prompt).strip() for prompt in prompts if str(prompt).strip()]
    if not prompts:
        return jsonify({"error": "请输入至少一条提示词"}), 400
    if len(prompts) > 100:
        return jsonify({"error": "单次最多提交 100 条提示词"}), 400
    try:
        width, height, batch_size = generation_parameters(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    new_tasks = [create_generation_task(payload, prompt, width, height, batch_size) for prompt in prompts]
    with lock:
        for task in new_tasks:
            tasks[task["id"]] = task
            queue.append(task["id"])
        save_tasks()
    worker_wakeup.set()
    return jsonify({"created": len(new_tasks), "items": [public_task(task) for task in new_tasks]}), 202


@app.post("/api/tasks/<task_id>/cancel")
def cancel_task(task_id):
    with lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404
        if task.get("status") in {"success", "error", "cancelled"}:
            return jsonify(public_task(task))
        task["cancel_requested"] = True
        if task.get("status") == "queued" and task_id in queue:
            queue.remove(task_id)
            task.update(status="cancelled", progress=0, message="任务已取消", updated_at=now())
        save_tasks()
    worker_wakeup.set()
    return jsonify(public_task(task))


@app.get("/api/tasks/<task_id>/image")
def task_image(task_id):
    filename = request.args.get("filename", "")
    with lock:
        task = tasks.get(task_id)
        images = task.get("outputs", []) if task else []
    image = next((item for item in images if item.get("filename") == filename), None)
    if not image:
        return jsonify({"error": "图片不存在"}), 404
    local = local_image_path(task_id, image)
    if local:
        return send_file(local, mimetype="image/png", max_age=0)
    try:
        archived = archive_images(task_id, [image])
        archived_image = archived[0]
        update_task(task_id, outputs=[
            archived_image if item.get("filename") == filename else item
            for item in images
        ])
        local = local_image_path(task_id, archived[0])
        return send_file(local, mimetype="image/png", max_age=0)
    except requests.RequestException:
        return jsonify({"error": "图片未归档且 ComfyUI 当前不可达"}), 503


@app.get("/api/library-image/<path:relative_path>")
def library_image(relative_path):
    requested = (OUTPUTS_DIR / relative_path).resolve()
    if OUTPUTS_DIR.resolve() not in requested.parents or not requested.is_file():
        return jsonify({"error": "图片不存在"}), 404
    return send_from_directory(OUTPUTS_DIR, relative_path, max_age=3600)


@app.get("/api/review/items")
def get_review_items():
    with lock:
        items = review_items()
    summary = {
        "total": len(items),
        "liked": sum(item.get("label") == "like" for item in items),
        "unliked": sum(item.get("label") == "unlike" for item in items),
        "unlabeled": sum(not item.get("label") for item in items),
        "queue_count": sum(task.get("status") in {"queued", "running"} for task in tasks.values()),
    }
    return jsonify({"items": items, "summary": summary})


@app.post("/api/review/label")
def set_review_label():
    payload = request.get_json(silent=True) or {}
    image_id = str(payload.get("image_id", ""))
    value = payload.get("value")
    if value not in {"like", "unlike", None} or not image_id:
        return jsonify({"error": "标注值必须为 like、unlike 或 null"}), 400
    with lock:
        known = {item["id"] for item in review_items()}
        if image_id not in known:
            return jsonify({"error": "图片不存在"}), 404
        if value is None:
            labels.pop(image_id, None)
        else:
            labels[image_id] = {"value": value, "updated_at": now()}
        save_labels()
    return jsonify({"image_id": image_id, "value": value})


@app.delete("/api/tasks/<task_id>/images/<path:filename>")
def delete_task_image(task_id, filename):
    with lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404
        if task.get("status") in {"queued", "running"}:
            return jsonify({"error": "进行中的任务不能删除，请先取消"}), 409

        output_filename = Path(filename).name
        outputs = task.get("outputs", [])
        if not any(item.get("filename") == output_filename for item in outputs):
            return jsonify({"error": "图片不存在"}), 404
        remaining = [item for item in outputs if item.get("filename") != output_filename]

        archive = (ARCHIVE_DIR / task_id / output_filename).resolve()
        if ARCHIVE_DIR.resolve() in archive.parents and archive.is_file():
            archive.unlink()
        labels.pop(f"task:{task_id}:{output_filename}", None)
        if remaining:
            task["outputs"] = remaining
            task["updated_at"] = now()
        else:
            tasks.pop(task_id)
            legacy = DATA_DIR / f"{task_id}.png"
            if legacy.is_file():
                legacy.unlink()
            task_archive = ARCHIVE_DIR / task_id
            if task_archive.is_dir() and not any(task_archive.iterdir()):
                task_archive.rmdir()
        save_tasks()
        save_labels()
    return jsonify({"task_id": task_id, "filename": output_filename, "deleted": True})


@app.delete("/api/tasks/history")
def clear_history():
    with lock:
        finished = [task_id for task_id, item in tasks.items() if item.get("status") in {"success", "error", "cancelled"}]
        for task_id in finished:
            tasks.pop(task_id, None)
        save_tasks()
    return jsonify({"removed": len(finished)})


load_tasks()
load_labels()
threading.Thread(target=worker, daemon=True, name="generation-worker").start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "4173")), debug=False)
