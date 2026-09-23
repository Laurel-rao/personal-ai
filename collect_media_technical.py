from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

from media_catalog import CATALOG_DIR, read_records
from server import MOVIES_DIR, PLAYER_EXTENSIONS


def main():
    executable = shutil.which("ffprobe")
    if not executable:
        raise SystemExit("未安装 ffprobe，无法读取本地技术参数")
    records, warning = read_records("technical.json")
    if warning:
        raise SystemExit(warning)
    paths = sorted(
        (path for path in MOVIES_DIR.rglob("*") if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in PLAYER_EXTENSIONS),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    for index, path in enumerate(paths, 1):
        relative = path.relative_to(MOVIES_DIR).as_posix()
        before = path.stat()
        previous = records.get(relative, {})
        previous = previous if isinstance(previous, dict) else {}
        if previous.get("size") == before.st_size and previous.get("mtime_ns") == before.st_mtime_ns and "duration" in previous:
            continue
        record = {"size": before.st_size, "mtime_ns": before.st_mtime_ns, "checked_at": datetime.now(timezone.utc).isoformat()}
        try:
            result = subprocess.run(
                [executable, "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=30, check=True,
            )
            payload = json.loads(result.stdout)
            duration = float(payload.get("format", {}).get("duration", 0))
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("无法读取有效时长")
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("文件在读取期间发生变化")
            streams = payload.get("streams", [])
            video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
            audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
            record.update(duration=duration, width=video.get("width", 0), height=video.get("height", 0), video_codec=video.get("codec_name", ""), audio_codec=audio.get("codec_name", ""))
        except (OSError, ValueError, subprocess.SubprocessError):
            record["error"] = "本地参数读取失败，可重新采集"
        records[relative] = record
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CATALOG_DIR, delete=False) as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            temporary = handle.name
        os.replace(temporary, CATALOG_DIR / "technical.json")
        print(f"{index}/{len(paths)} {'读取失败' if 'error' in record else '已采集'}", flush=True)


if __name__ == "__main__":
    main()
