#!/usr/bin/env python3
"""Restore Photo Lab's historical outputs from the configured ComfyUI /view API."""

import argparse
import json
import os
import sys
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TASKS_FILE = DATA_DIR / "tasks.json"
ARCHIVE_DIR = DATA_DIR / "images"
DEFAULT_COMFY_URL = "https://u288331-788499bf7eab.bjb1.seetacloud.com:8443"


def save_tasks(tasks):
    temporary = TASKS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(TASKS_FILE)


def image_target(task_id, image):
    filename = Path(str(image.get("filename") or "")).name
    if not filename:
        raise ValueError("历史记录缺少输出文件名")
    return ARCHIVE_DIR / task_id / filename


def restore(tasks, comfy_url, timeout, dry_run):
    session = requests.Session()
    counters = {"restored": 0, "skipped": 0, "unavailable": 0, "failed": 0}
    changed = False

    for task_id, task in tasks.items():
        if task.get("status") != "success":
            continue
        for image in task.get("outputs", []):
            try:
                target = image_target(task_id, image)
            except ValueError as error:
                counters["failed"] += 1
                print(f"FAILED {task_id}: {error}", file=sys.stderr)
                continue

            if target.is_file() and target.stat().st_size > 0:
                counters["skipped"] += 1
                if image.get("local_filename") != target.name:
                    image["local_filename"] = target.name
                    changed = True
                continue

            if dry_run:
                counters["restored"] += 1
                continue

            params = {
                key: image[key]
                for key in ("filename", "subfolder", "type")
                if image.get(key)
            }
            try:
                response = session.get(f"{comfy_url}/view", params=params, timeout=timeout, stream=True)
                if response.status_code == 404:
                    counters["unavailable"] += 1
                    print(f"MISSING {task_id}: {params}", file=sys.stderr)
                    continue
                response.raise_for_status()

                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(f"{target.suffix}.tmp")
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)
                if temporary.stat().st_size == 0:
                    temporary.unlink(missing_ok=True)
                    raise RuntimeError("ComfyUI 返回了空文件")
                temporary.replace(target)
                image["local_filename"] = target.name
                counters["restored"] += 1
                changed = True
                print(f"RESTORED {task_id}/{target.name}")
            except requests.RequestException as error:
                counters["failed"] += 1
                print(f"FAILED {task_id}: {error}", file=sys.stderr)

    if changed and not dry_run:
        save_tasks(tasks)
    return counters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("COMFY_URL", DEFAULT_COMFY_URL))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    counters = restore(tasks, args.url.rstrip("/"), args.timeout, args.dry_run)
    print(json.dumps(counters, ensure_ascii=False))
    if counters["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
