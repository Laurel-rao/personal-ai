"""Pre-cache DMM official covers (and frame fallbacks) for every local video.

Run with: .venv/bin/python tools/warm_video_covers.py
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


def warm(item: dict) -> tuple[str, str]:
    code = str((item.get("metadata") or {}).get("code") or "")
    if code:
        try:
            data = server._nya_cover_bytes(code, full=False)
            if data:
                server._official_thumb_bytes(code, data)
                return code, "official"
        except Exception:  # noqa: BLE001
            pass
    try:
        thumb = server._video_thumb(item["id"])
        return code or item["id"], "frame" if thumb else "missing"
    except Exception:  # noqa: BLE001
        return code or item["id"], "missing"


def main() -> None:
    items, warning = server._all_videos()
    if warning:
        print("warning:", warning)
    print("videos:", len(items))
    counts = {"official": 0, "frame": 0, "missing": 0}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(warm, item) for item in items]
        for index, future in enumerate(as_completed(futures), 1):
            key, kind = future.result()
            counts[kind] += 1
            if index % 10 == 0 or index == len(items):
                print(f"{index}/{len(items)} official={counts['official']} frame={counts['frame']} missing={counts['missing']} last={key}", flush=True)
    print("done:", counts)


if __name__ == "__main__":
    main()
