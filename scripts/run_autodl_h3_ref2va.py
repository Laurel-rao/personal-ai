#!/usr/bin/env python3
"""Submit, monitor, download, and receipt an AutoDL H3 Ref2VA task."""

import argparse
import base64
import getpass
import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


DEFAULT_WORKFLOW = "minimax_h3_lightx2v_v5"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_json(url: str, token: str, method="GET", payload=None, timeout=120):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Authorization": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:2000]}") from exc


def download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "media_creator/1.0"})
    with urllib.request.urlopen(request, timeout=600) as response, path.open("wb") as output:
        expected = response.headers.get("Content-Length")
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            output.write(chunk)
    if expected is not None and path.stat().st_size != int(expected):
        raise RuntimeError(
            f"truncated download: expected {expected} bytes, received {path.stat().st_size}"
        )


def write_receipt(output_dir: Path, receipt: dict) -> None:
    (output_dir / "run-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def reference_metadata(index: int, path: Path) -> dict:
    with Image.open(path) as image:
        width, height = image.size
    ratio = width / height
    return {
        "field": f"ref_image_{index}",
        "picture": index + 1,
        "path": str(path.resolve()),
        "width": width,
        "height": height,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "checks": {
            "dimensions_256_to_5760": 256 <= width <= 5760 and 256 <= height <= 5760,
            "ratio_5_2_to_2_5": 0.4 <= ratio <= 2.5,
            "under_30mb": path.stat().st_size < 30 * 1024 * 1024,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-stem", required=True)
    parser.add_argument("--reference", type=Path, action="append", required=True)
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--resolution", default="768p横")
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--poll-timeout", type=int, default=2700)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not 1 <= len(args.reference) <= 9:
        raise ValueError("reference count must be between 1 and 9")
    if not 1 <= args.duration <= 10:
        raise ValueError("this AutoDL workflow supports duration 1-10 seconds")
    for path in [args.prompt, *args.reference]:
        if not path.is_file():
            raise FileNotFoundError(path)

    submit_url = f"https://www.autodl.art/api/v1/comfyui/comfyui_workflow/{args.workflow}"
    result_url = "https://www.autodl.art/api/v1/comfyui/comfyui_workflow/result/{task_id}"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prompt = args.prompt.read_text(encoding="utf-8").strip()
    if len(prompt) > 7000:
        raise ValueError(f"prompt exceeds H3 limit: {len(prompt)} characters")

    payload = {"prompt": prompt, "duration": args.duration, "resolution": args.resolution}
    for index, path in enumerate(args.reference):
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        payload[f"ref_image_{index}"] = f"data:{mime};base64,{encoded}"

    references = [reference_metadata(index, path) for index, path in enumerate(args.reference)]
    failed_checks = [
        f"Picture {item['picture']}: {name}"
        for item in references
        for name, passed in item["checks"].items()
        if not passed
    ]
    if failed_checks:
        raise ValueError("reference preflight failed: " + ", ".join(failed_checks))

    if args.dry_run:
        dry_run = {
            "mode": "Ref2VA",
            "workflow_id": args.workflow,
            "duration": args.duration,
            "resolution": args.resolution,
            "prompt_path": str(args.prompt.resolve()),
            "prompt_characters": len(prompt),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "references": references,
            "request_bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
            "network_submitted": False,
        }
        (args.output_dir / "dry-run.json").write_text(
            json.dumps(dry_run, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(dry_run, ensure_ascii=False, indent=2))
        return

    token = os.environ.get("AUTODL_ART_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("AutoDL Token: ").strip()
    if not token:
        raise RuntimeError("empty AutoDL token")

    receipt = {
        "provider": "AutoDL.Art",
        "workflow_id": args.workflow,
        "submitted_at": now_iso(),
        "request": {
            "mode": "Ref2VA",
            "prompt_path": str(args.prompt.resolve()),
            "prompt_characters": len(prompt),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "duration": args.duration,
            "resolution": args.resolution,
            "references": references,
        },
        "polls": [],
    }

    print("Submitting...", flush=True)
    submission = request_json(submit_url, token, "POST", payload)
    receipt["submission"] = submission
    task_id = (submission.get("data") or {}).get("task_id")
    if not task_id:
        receipt.update(status="submission_failed", finished_at=now_iso())
        write_receipt(args.output_dir, receipt)
        raise RuntimeError("submission returned no task_id")
    receipt["task_id"] = task_id
    write_receipt(args.output_dir, receipt)
    print(f"Submitted task_id={task_id}", flush=True)

    deadline = time.monotonic() + args.poll_timeout
    last_status = None
    final_data = None
    while time.monotonic() < deadline:
        response = request_json(result_url.format(task_id=task_id), token)
        data = response.get("data") or {}
        status = str(data.get("status") or "UNKNOWN")
        normalized = status.upper()
        receipt["polls"].append(
            {
                "checked_at": now_iso(),
                "status": status,
                "duration": data.get("duration"),
                "result_count": len(data.get("results") or []),
            }
        )
        if status != last_status:
            print(f"Status={status}", flush=True)
            last_status = status
        write_receipt(args.output_dir, receipt)
        if normalized in {"SUCCESS", "COMPLETED"}:
            final_data = data
            break
        if normalized in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            receipt.update(status=normalized.lower(), finished_at=now_iso(), final_response=response)
            write_receipt(args.output_dir, receipt)
            raise RuntimeError(f"task ended with {status}")
        time.sleep(5)

    if final_data is None:
        receipt.update(status="poll_timeout", finished_at=now_iso())
        write_receipt(args.output_dir, receipt)
        raise RuntimeError("poll timeout")

    downloads = []
    for index, item in enumerate(final_data.get("results") or [], start=1):
        url = item.get("url")
        if not url:
            continue
        extension = (
            item.get("file_type")
            or Path(urllib.parse.urlparse(url).path).suffix.lstrip(".")
            or "bin"
        )
        output_path = args.output_dir / f"{args.output_stem}_{index:02d}.{extension}"
        download(url, output_path)
        downloads.append(
            {
                "source_url": url,
                "type": item.get("type"),
                "file_type": item.get("file_type"),
                "output_type": item.get("output_type"),
                "local_path": str(output_path.resolve()),
                "bytes": output_path.stat().st_size,
                "sha256": sha256(output_path),
            }
        )
        print(f"Downloaded {output_path.name} ({output_path.stat().st_size} bytes)", flush=True)

    receipt.update(
        status="completed",
        finished_at=now_iso(),
        results=final_data.get("results") or [],
        downloads=downloads,
    )
    write_receipt(args.output_dir, receipt)
    if not downloads:
        raise RuntimeError("completed without downloadable result")
    print("Done", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
