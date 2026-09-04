#!/usr/bin/env python3
"""Run a bundled ComfyUI API workflow and download its outputs."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW = SKILL_DIR / "assets" / "minimax-h3-workflow-api.json"
DEFAULT_URL = "https://u288331-78711d14f731.bjb2.seetacloud.com:8443"
REQUIRED_NODES = (
    "MiniMaxH3ReferenceToVideo",
    "UniBlockSwap",
    "EasyCache",
    "PathchSageAttentionKJ",
    "ModelPatchTorchSettings",
    "SaveVideo",
)
MEDIA_EXTENSIONS = {
    ".mp4", ".webm", ".mov", ".m4v", ".png", ".jpg", ".jpeg",
    ".webp", ".gif", ".wav", ".mp3", ".flac", ".ogg",
}


class WorkflowError(RuntimeError):
    """Raised when ComfyUI rejects or fails the workflow."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WorkflowError("--url must be a valid HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise WorkflowError("Do not embed credentials in --url")
    return url


def request(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60,
) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(
            req, timeout=timeout, context=ssl.create_default_context()
        ) as response:
            return (
                response.status,
                response.read(),
                response.headers.get("Content-Type", "application/octet-stream"),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            error.read(),
            error.headers.get("Content-Type", "application/octet-stream"),
        )
    except urllib.error.URLError as error:
        raise WorkflowError(f"Request failed: {error.reason}") from error


def decode_json(payload: bytes, *, context: str) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        preview = payload.decode("utf-8", errors="replace")[:300].strip()
        raise WorkflowError(f"{context} did not return JSON: {preview or '<empty>'}") from error


def request_json(
    method: str,
    url: str,
    *,
    data: Any | None = None,
    timeout: float = 60,
) -> tuple[int, Any]:
    body = None
    headers: dict[str, str] = {}
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    status, payload, _ = request(method, url, body=body, headers=headers, timeout=timeout)
    try:
        data = decode_json(payload, context=url)
    except WorkflowError as error:
        if status >= 400:
            raise WorkflowError(f"{url} returned HTTP {status} with a non-JSON body") from error
        raise
    return status, data


def load_workflow(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise WorkflowError(f"Cannot read workflow: {path}") from error
    except json.JSONDecodeError as error:
        raise WorkflowError(f"Invalid workflow JSON: {error}") from error
    if not isinstance(data, dict) or not data:
        raise WorkflowError("Workflow JSON must be a non-empty object")
    for node_id, node in data.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str):
            raise WorkflowError(f"Node {node_id} is not in ComfyUI API format")
        if not isinstance(node.get("inputs"), dict):
            raise WorkflowError(f"Node {node_id} has no inputs object")
    return data


def parse_override(raw: str) -> tuple[str, str, Any]:
    if "=" not in raw or "." not in raw.split("=", 1)[0]:
        raise WorkflowError(f"Invalid --set value: {raw}; expected NODE.INPUT=VALUE")
    target, raw_value = raw.split("=", 1)
    node_id, input_name = target.split(".", 1)
    if not node_id or not input_name:
        raise WorkflowError(f"Invalid --set target: {target}")
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    return node_id, input_name, value


def apply_override(workflow: dict[str, Any], raw: str) -> None:
    node_id, input_name, value = parse_override(raw)
    if node_id not in workflow:
        raise WorkflowError(f"Unknown workflow node: {node_id}")
    workflow[node_id]["inputs"][input_name] = value


def multipart_body(fields: dict[str, str], file_field: str, path: Path) -> tuple[bytes, str]:
    boundary = f"----codex-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{path.name}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_image(base_url: str, path: Path) -> str:
    if not path.is_file():
        raise WorkflowError(f"Image does not exist: {path}")
    body, content_type = multipart_body(
        {"overwrite": "true", "type": "input"}, "image", path
    )
    status, payload, _ = request(
        "POST",
        f"{base_url}/upload/image",
        body=body,
        headers={"Content-Type": content_type},
        timeout=180,
    )
    data = decode_json(payload, context="image upload")
    if status >= 400 or not isinstance(data, dict) or not data.get("name"):
        raise WorkflowError(f"Image upload failed ({status}): {data}")
    subfolder = str(data.get("subfolder") or "").strip("/")
    return f"{subfolder}/{data['name']}" if subfolder else str(data["name"])


def apply_images(
    workflow: dict[str, Any], base_url: str, values: list[str]
) -> list[dict[str, str]]:
    uploads: list[dict[str, str]] = []
    for raw in values:
        if "=" not in raw:
            raise WorkflowError(f"Invalid --image value: {raw}; expected NODE=PATH")
        node_id, raw_path = raw.split("=", 1)
        if node_id not in workflow:
            raise WorkflowError(f"Unknown image node: {node_id}")
        if workflow[node_id].get("class_type") != "LoadImage":
            raise WorkflowError(f"Node {node_id} is not a LoadImage node")
        path = Path(raw_path).expanduser().resolve()
        remote_name = upload_image(base_url, path)
        workflow[node_id]["inputs"]["image"] = remote_name
        uploads.append(
            {"node_id": node_id, "local_path": str(path), "remote_name": remote_name}
        )
        print(f"[upload] node={node_id} name={remote_name}", flush=True)
    return uploads


def validate_image_overrides(
    workflow: dict[str, Any], values: list[str]
) -> list[dict[str, str]]:
    validated: list[dict[str, str]] = []
    for raw in values:
        if "=" not in raw:
            raise WorkflowError(f"Invalid --image value: {raw}; expected NODE=PATH")
        node_id, raw_path = raw.split("=", 1)
        if node_id not in workflow:
            raise WorkflowError(f"Unknown image node: {node_id}")
        if workflow[node_id].get("class_type") != "LoadImage":
            raise WorkflowError(f"Node {node_id} is not a LoadImage node")
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise WorkflowError(f"Image does not exist: {path}")
        validated.append({"node_id": node_id, "local_path": str(path)})
    return validated


def check_service(base_url: str) -> dict[str, Any]:
    status, prompt_state = request_json("GET", f"{base_url}/prompt", timeout=20)
    if status >= 400 or not isinstance(prompt_state, dict):
        raise WorkflowError(f"ComfyUI /prompt check failed ({status}): {prompt_state}")
    status, system_stats = request_json("GET", f"{base_url}/system_stats", timeout=30)
    if status >= 400 or not isinstance(system_stats, dict):
        raise WorkflowError(
            f"ComfyUI /system_stats check failed ({status}): {system_stats}"
        )
    missing: list[str] = []
    for node in REQUIRED_NODES:
        node_status, data = request_json(
            "GET", f"{base_url}/object_info/{node}", timeout=30
        )
        if node_status >= 400 or not isinstance(data, dict) or node not in data:
            missing.append(node)
    if missing:
        raise WorkflowError(f"Missing required ComfyUI nodes: {', '.join(missing)}")
    devices = system_stats.get("devices")
    if not isinstance(devices, list):
        devices = []
    return {
        "url": base_url,
        "queue_remaining": (prompt_state.get("exec_info") or {}).get("queue_remaining"),
        "comfyui_version": (system_stats.get("system") or {}).get("comfyui_version"),
        "devices": [
            device.get("name") for device in devices if isinstance(device, dict)
        ],
        "required_nodes": list(REQUIRED_NODES),
    }


def submit_workflow(base_url: str, workflow: dict[str, Any]) -> dict[str, Any]:
    client_id = str(uuid.uuid4())
    status, data = request_json(
        "POST",
        f"{base_url}/prompt",
        data={"prompt": workflow, "client_id": client_id},
        timeout=120,
    )
    if status >= 400 or not isinstance(data, dict) or not data.get("prompt_id"):
        raise WorkflowError(f"Workflow submission failed ({status}): {data}")
    node_errors = data.get("node_errors")
    if isinstance(node_errors, dict) and node_errors:
        raise WorkflowError(f"Workflow validation failed: {node_errors}")
    return {**data, "client_id": client_id}


def history_entry(base_url: str, prompt_id: str) -> dict[str, Any] | None:
    path_id = urllib.parse.quote(prompt_id)
    status, data = request_json("GET", f"{base_url}/history/{path_id}", timeout=30)
    if status >= 400 or not isinstance(data, dict):
        raise WorkflowError(f"History request failed ({status}): {data}")
    entry = data.get(prompt_id)
    return entry if isinstance(entry, dict) else None


def execution_error(entry: dict[str, Any]) -> str:
    status = entry.get("status")
    if isinstance(status, dict) and status.get("status_str") == "error":
        messages = status.get("messages")
        if isinstance(messages, list):
            for item in reversed(messages):
                if (
                    isinstance(item, list)
                    and len(item) > 1
                    and item[0] == "execution_error"
                ):
                    detail = item[1]
                    if isinstance(detail, dict):
                        return str(detail.get("exception_message") or detail)
                    return str(detail)
        return "ComfyUI execution failed"
    return ""


def wait_for_history(
    base_url: str, prompt_id: str, timeout: int, poll_interval: float
) -> dict[str, Any]:
    started = time.monotonic()
    attempt = 0
    last_error = ""
    while time.monotonic() - started < timeout:
        attempt += 1
        try:
            entry = history_entry(base_url, prompt_id)
            last_error = ""
        except WorkflowError as error:
            entry = None
            last_error = str(error)
            if attempt == 1 or attempt % 6 == 0:
                print(f"[poll] transient_error={last_error}", flush=True)
        if entry is not None:
            error = execution_error(entry)
            if error:
                raise WorkflowError(error)
            print(f"[complete] prompt_id={prompt_id} polls={attempt}", flush=True)
            return entry
        if attempt == 1 or attempt % 6 == 0:
            running = False
            pending = False
            try:
                _, queue = request_json("GET", f"{base_url}/queue", timeout=30)
                if isinstance(queue, dict):
                    running = any(
                        isinstance(item, list) and len(item) > 1 and item[1] == prompt_id
                        for item in queue.get("queue_running", [])
                    )
                    pending = any(
                        isinstance(item, list) and len(item) > 1 and item[1] == prompt_id
                        for item in queue.get("queue_pending", [])
                    )
            except WorkflowError as error:
                last_error = str(error)
            print(
                f"[poll] attempt={attempt} running={running} pending={pending}",
                flush=True,
            )
        time.sleep(poll_interval)
    detail = f"; last error: {last_error}" if last_error else ""
    raise WorkflowError(
        f"Timed out after {timeout}s waiting for prompt_id={prompt_id}{detail}"
    )


def output_files(value: Any, found: list[dict[str, str]]) -> None:
    if isinstance(value, list):
        for item in value:
            output_files(item, found)
        return
    if not isinstance(value, dict):
        return
    filename = value.get("filename")
    if isinstance(filename, str) and Path(filename).suffix.lower() in MEDIA_EXTENSIONS:
        item = {
            "filename": filename,
            "subfolder": str(value.get("subfolder") or ""),
            "type": str(value.get("type") or "output"),
        }
        if item not in found:
            found.append(item)
    for child in value.values():
        output_files(child, found)


def safe_local_name(item: dict[str, str], used: set[str]) -> str:
    original = Path(item["filename"]).name
    stem = Path(original).stem
    suffix = Path(original).suffix
    candidate = original
    index = 2
    while candidate in used:
        candidate = f"{stem}-{index}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def download_outputs(
    base_url: str, entry: dict[str, Any], output_dir: Path
) -> list[dict[str, Any]]:
    items: list[dict[str, str]] = []
    output_files(entry.get("outputs"), items)
    if not items:
        raise WorkflowError("ComfyUI history completed without downloadable media outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict[str, Any]] = []
    used: set[str] = set()
    for item in items:
        query = urllib.parse.urlencode(item)
        status, payload, content_type = request(
            "GET", f"{base_url}/view?{query}", timeout=300
        )
        if status >= 400:
            raise WorkflowError(
                f"Output download failed ({status}): {item['filename']}"
            )
        local_path = output_dir / safe_local_name(item, used)
        local_path.write_bytes(payload)
        record = {
            **item,
            "local_path": str(local_path.resolve()),
            "bytes": len(payload),
            "content_type": content_type,
        }
        downloaded.append(record)
        print(f"[download] {local_path} bytes={len(payload)}", flush=True)
    return downloaded


def write_receipt(output_dir: Path, receipt: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "run-receipt.json"
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("COMFYUI_BASE_URL", DEFAULT_URL))
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/minimax-h3-comfyui")
    )
    parser.add_argument("--prompt-id", help="Monitor an existing prompt instead of submitting")
    parser.add_argument("--prompt-node", default="138")
    prompt_group = parser.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt-file", type=Path)
    prompt_group.add_argument("--prompt-text")
    parser.add_argument("--image", action="append", default=[], metavar="NODE=PATH")
    parser.add_argument(
        "--set", dest="overrides", action="append", default=[], metavar="NODE.INPUT=VALUE"
    )
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--poll-interval", type=float, default=10.0)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-wait", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.prompt_id and (
            args.image
            or args.overrides
            or args.prompt_file
            or args.prompt_text is not None
        ):
            raise WorkflowError(
                "--prompt-id cannot be combined with prompt, image, or node overrides"
            )
        base_url = normalize_url(args.url)
        output_dir = args.output_dir.expanduser().resolve()
        workflow_path = args.workflow.expanduser().resolve()
        if args.dry_run:
            workflow = load_workflow(workflow_path)
            for raw in args.overrides:
                apply_override(workflow, raw)
            image_overrides = validate_image_overrides(workflow, args.image)
            if args.prompt_file or args.prompt_text is not None:
                if args.prompt_node not in workflow:
                    raise WorkflowError(f"Unknown prompt node: {args.prompt_node}")
                prompt = (
                    args.prompt_file.expanduser().read_text(encoding="utf-8")
                    if args.prompt_file
                    else args.prompt_text
                )
                workflow[args.prompt_node]["inputs"]["value"] = prompt
            summary = {
                "workflow": str(workflow_path),
                "node_count": len(workflow),
                "url": base_url,
                "image_overrides": image_overrides,
                "input_overrides": args.overrides,
                "will_submit": False,
            }
            print(json.dumps({"dry_run": summary}, ensure_ascii=False, indent=2))
            return 0

        check = check_service(base_url)
        print(json.dumps({"check": check}, ensure_ascii=False), flush=True)
        if args.check:
            return 0

        started_at = utc_now()
        submission: dict[str, Any]
        if args.prompt_id:
            uploads: list[dict[str, str]] = []
            submission = {"prompt_id": args.prompt_id, "resumed": True}
        else:
            workflow = load_workflow(workflow_path)
            for raw in args.overrides:
                apply_override(workflow, raw)
            if args.prompt_file or args.prompt_text is not None:
                if args.prompt_node not in workflow:
                    raise WorkflowError(f"Unknown prompt node: {args.prompt_node}")
                prompt = (
                    args.prompt_file.expanduser().read_text(encoding="utf-8")
                    if args.prompt_file
                    else args.prompt_text
                )
                workflow[args.prompt_node]["inputs"]["value"] = prompt
            uploads = apply_images(workflow, base_url, args.image)
            submission = submit_workflow(base_url, workflow)
            print(
                f"[submit] prompt_id={submission['prompt_id']} "
                f"number={submission.get('number')}",
                flush=True,
            )

        prompt_id = str(submission["prompt_id"])
        receipt: dict[str, Any] = {
            "prompt_id": prompt_id,
            "url": base_url,
            "workflow": str(workflow_path),
            "started_at": started_at,
            "submission": submission,
            "uploads": uploads,
            "status": "submitted",
            "outputs": [],
        }
        if args.no_wait:
            receipt_path = write_receipt(output_dir, receipt)
            print(f"[receipt] {receipt_path}")
            return 0

        entry = wait_for_history(
            base_url, prompt_id, args.timeout, args.poll_interval
        )
        outputs = download_outputs(base_url, entry, output_dir)
        receipt.update(
            {
                "status": "completed",
                "completed_at": utc_now(),
                "outputs": outputs,
                "history_status": entry.get("status"),
            }
        )
        receipt_path = write_receipt(output_dir, receipt)
        print(f"[receipt] {receipt_path}")
        return 0
    except (WorkflowError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
