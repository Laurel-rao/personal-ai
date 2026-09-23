from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path


CATALOG_DIR = Path(__file__).resolve().parent / "data" / "player"
CODE_PATTERN = re.compile(r"(?<![A-Z0-9])([A-Z]{2,6})[-_]?([0-9]{3,7})(?![0-9])", re.I)


def video_code(filename: str) -> str:
    fc2 = re.search(r"FC2[-_ ]?PPV[-_ ]?([0-9]{5,8})(?![0-9])", filename, re.I)
    if fc2:
        return f"FC2-PPV-{fc2.group(1)}"
    for match in CODE_PATTERN.finditer(filename):
        prefix, digits = match.groups()
        if prefix.upper() not in {"HHD", "KLING", "JK"}:
            return f"{prefix.upper()}-{digits}"
    return ""


def read_records(name: str) -> tuple[dict, str]:
    path = CATALOG_DIR / name
    if not path.exists():
        return {}, ""
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, dict):
            raise ValueError("资料必须为对象")
        return records, ""
    except (OSError, ValueError):
        return {}, f"无法读取 {name}，已保留本地文件列表"


def approved_cover(record: dict) -> Path | None:
    cover = record.get("cover")
    if not isinstance(cover, dict) or cover.get("reviewed_safe") is not True:
        return None
    filename = cover.get("file")
    if not isinstance(filename, str):
        return None
    root = (CATALOG_DIR / "covers").resolve()
    target = (root / filename).resolve()
    if root not in target.parents or target.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None
    return target if target.is_file() else None


def item_metadata(item: dict, records: dict, technical: dict, file_stat) -> dict:
    code = video_code(item["filename"])
    record = records.get(code, {})
    record = record if isinstance(record, dict) else {}
    status = record.get("status", "pending" if code else "unidentified")
    if not isinstance(status, str) or status not in {"verified", "partial", "not_found", "pending", "unidentified"}:
        status = "pending"
    text = lambda key: record.get(key, "") if isinstance(record.get(key, ""), str) else ""
    names = lambda key: [value for value in record.get(key, []) if isinstance(value, str)] if isinstance(record.get(key), list) else []
    sources = record.get("sources", [])
    sources = [source for source in sources if isinstance(source, dict)] if isinstance(sources, list) else []
    probe = technical.get(item["id"], {})
    if not isinstance(probe, dict) or probe.get("size") != file_stat.st_size or probe.get("mtime_ns") != file_stat.st_mtime_ns:
        probe = {}
    return {
        "code": code,
        "status": status,
        "full_title": text("full_title"),
        "actors": names("actors"),
        "publisher": text("publisher"),
        "genres": names("genres"),
        "release_date": text("release_date"),
        "checked_at": text("checked_at"),
        "note": text("note"),
        "sources": [{"name": str(source.get("name", "")), "level": str(source.get("level", ""))} for source in sources],
        "cover_url": f"/api/player/cover?code={urllib.parse.quote(code)}" if approved_cover(record) else "",
        "technical": probe,
    }


def catalog_summary(items: list[dict]) -> dict:
    counts = {status: 0 for status in ("verified", "partial", "not_found", "pending", "unidentified")}
    for item in items:
        counts[item["metadata"]["status"]] += 1
    return {
        **counts,
        "total": len(items),
        "checked": counts["verified"] + counts["partial"] + counts["not_found"],
        "covers": sum(bool(item["metadata"]["cover_url"]) for item in items),
        "technical": sum("duration" in item["metadata"]["technical"] for item in items),
    }
