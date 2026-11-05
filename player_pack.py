"""把单个选手的本地写真目录打包成 manifest、懒加载画廊和合订 PDF。

目录约定：``~/Movies/写真/<选手名>/<作品code>/page_*.jpg``，对开图在
``<作品code>/spreads/spread_*.jpg``（可有可无）。只依赖标准库和 Pillow。
"""

from __future__ import annotations

import html
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from PIL import Image

LAYOUTS = ("auto", "spread", "page")
_PAGE_PATTERN = "page_*.jpg"
_SPREAD_PATTERN = "spread_*.jpg"


# ---------------------------------------------------------------- 路径安全

def _is_within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _file_inside(base: Path, path: Path) -> Path | None:
    """解析后的文件必须仍在 base 内，否则视为越界。"""
    try:
        target = Path(path).resolve()
    except OSError:
        return None
    if not _is_within(target, base) or not target.is_file():
        return None
    return target


def _safe_child(base: Path, value: str | Path) -> Path | None:
    """把书名/相对路径拼到 base 下，拒绝绝对路径和 ``..`` 越界。"""
    candidate = Path(value)
    if candidate.is_absolute():
        return None
    try:
        target = (base / candidate).resolve()
    except OSError:
        return None
    if not _is_within(target, base):
        return None
    return target


def _safe_filename(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch not in "/\\" and ord(ch) >= 32)
    cleaned = cleaned.strip().strip(".")
    return (cleaned or "player")[:80]


def _rel(base: Path, path: Path) -> str:
    return path.relative_to(base).as_posix()


# ---------------------------------------------------------------- 扫描

def _glob_images(base: Path, folder: Path, pattern: str, probe: bool = False) -> list[Path]:
    if not folder.is_dir():
        return []
    try:
        found = sorted(folder.glob(pattern))
    except OSError:
        return []
    files: list[Path] = []
    for item in found:
        target = _file_inside(base, item)
        if target is None:
            continue
        if probe and _probe_image(target)[0] is None:
            continue
        files.append(target)
    return files


def _probe_image(path: Path) -> tuple[tuple[int, int] | None, str | None]:
    try:
        with Image.open(path) as image:
            size = image.size
            image.verify()
        width, height = int(size[0]), int(size[1])
        if width <= 0 or height <= 0:
            return None, "empty image"
        return (width, height), None
    except Exception as exc:  # noqa: BLE001 - 坏图只记录，不影响整包
        return None, f"{type(exc).__name__}: {exc}"[:200]


def _scan_book(base: Path, folder: Path, label: str) -> dict | None:
    page_candidates = _glob_images(base, folder, _PAGE_PATTERN)
    spread_candidates = _glob_images(base, folder / "spreads", _SPREAD_PATTERN)
    if not page_candidates and not spread_candidates:
        return None

    skipped: list[dict] = []
    sizes: dict[Path, tuple[int, int]] = {}

    def valid(paths: list[Path]) -> list[Path]:
        kept: list[Path] = []
        for path in paths:
            size, error = _probe_image(path)
            if size is None:
                skipped.append({"file": _rel(base, path), "error": error or "unreadable"})
            else:
                kept.append(path)
                sizes[path] = size
        return kept

    page_files = valid(page_candidates)
    spread_files = valid(spread_candidates)
    first = (page_files or spread_files or [None])[0]
    resolution = None
    if first is not None and first in sizes:
        width, height = sizes[first]
        resolution = f"{width}x{height}"

    return {
        "code": label,
        "dir": label,
        "pages": len(page_files),
        "spreads": len(spread_files),
        "resolution": resolution,
        "downloaded": (folder / ".done").is_file(),
        "page_files": page_files,
        "spread_files": spread_files,
        "skipped": skipped,
        "sizes": sizes,
    }


def _scan_books(base: Path) -> tuple[list[dict], list[dict]]:
    books: list[dict] = []
    skipped: list[dict] = []
    try:
        entries = sorted(base.iterdir(), key=lambda item: item.name)
    except OSError:
        return books, skipped
    for entry in entries:
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        try:
            resolved = entry.resolve()
        except OSError:
            resolved = entry
        if not _is_within(resolved, base):
            skipped.append({"file": entry.name, "error": "outside player_dir"})
            continue
        book = _scan_book(base, entry, entry.name)
        if book is None:
            continue
        if book["pages"] or book["spreads"]:
            books.append(book)
        else:
            skipped.append({"file": entry.name, "error": "no readable images"})
            skipped.extend(book["skipped"])
    return books, skipped


# ---------------------------------------------------------------- PDF

def _write_pdf(items: list[tuple[str, Path]], pdf_path: Path, max_height: int) -> tuple[int, list[dict]]:
    """把 (相对路径, 绝对路径) 依次缩放到 max_height 并合成 PDF。"""
    skipped: list[dict] = []
    scaled: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="player-pack-") as tmp:
        for index, (rel_path, source) in enumerate(items):
            try:
                with Image.open(source) as raw:
                    raw.load()
                    width, height = raw.size
                    image = raw.convert("RGB")
                try:
                    if height > max_height:
                        width = max(1, int(round(width * max_height / height)))
                        image = image.resize((width, max_height), Image.LANCZOS)
                    target = Path(tmp) / f"{index:05d}.jpg"
                    image.save(target, "JPEG", quality=90)
                    scaled.append(target)
                finally:
                    image.close()
            except Exception as exc:  # noqa: BLE001 - 单张坏图跳过
                skipped.append({"file": rel_path, "error": f"{type(exc).__name__}: {exc}"[:200]})

        if not scaled:
            return 0, skipped

        opened: list[Image.Image] = []
        try:
            for target in scaled:
                opened.append(Image.open(target))
            opened[0].save(
                str(pdf_path), "PDF", save_all=True,
                append_images=opened[1:], resolution=72.0,
            )
        finally:
            for image in opened:
                image.close()
    return len(scaled), skipped


# ---------------------------------------------------------------- 画廊

def _book_folder(player_dir: Path, book: dict) -> Path | None:
    name = book.get("dir") or book.get("code")
    if not isinstance(name, str) or not name:
        return None
    folder = _safe_child(player_dir, name)
    if folder is None or not folder.is_dir():
        return None
    return folder


def _book_images(player_dir: Path, book: dict, layout: str) -> list[Path]:
    if book.get("images") is not None:
        images: list[Path] = []
        for value in book.get("images") or []:
            path = _file_inside(player_dir, Path(value) if Path(value).is_absolute() else player_dir / value)
            if path is not None:
                images.append(path)
        return images

    folder = _book_folder(player_dir, book)
    if folder is None:
        return []
    if layout == "page":
        return _glob_images(player_dir, folder, _PAGE_PATTERN, probe=True)
    spreads = _glob_images(player_dir, folder / "spreads", _SPREAD_PATTERN, probe=True)
    if spreads:
        return spreads
    return _glob_images(player_dir, folder, _PAGE_PATTERN, probe=True)


def _href(base_dir: Path, target: Path) -> str:
    relative = os.path.relpath(str(target), str(base_dir))
    return "/".join(quote(part, safe="") for part in Path(relative).as_posix().split("/"))


_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0e1014;color:#e8eaed;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif}
header{position:sticky;top:0;z-index:2;padding:14px 20px;background:rgba(14,16,20,.92);border-bottom:1px solid #232830;backdrop-filter:blur(8px)}
header h1{margin:0;font-size:18px;font-weight:600}
header p{margin:4px 0 0;color:#8b95a3;font-size:12px}
.gallery{max-width:1680px;margin:0 auto;padding:8px 16px 48px}
.book{margin:28px 0}
.book h2{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 12px;font-size:14px;font-weight:600}
.book h2 .code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:15px;color:#f3f4f6}
.badge{color:#9aa4b2;font-size:12px;font-weight:400}
.badge.done{color:#6ee7a8}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
figure{margin:0;background:#171b21;border:1px solid #232830;border-radius:8px;overflow:hidden}
figure a{display:block;color:inherit;text-decoration:none}
figure img{display:block;width:100%;height:auto;min-height:120px;object-fit:cover;background:#11151a}
figcaption{padding:6px 9px;color:#7d8795;font-size:11px}
.empty{color:#8b95a3;padding:48px 8px;text-align:center}
"""


def _render_index(player_dir: Path, books: list[dict], layout: str, base_dir: Path) -> str:
    player_name = html.escape(player_dir.name or "写真")
    sections: list[str] = []
    total = 0
    for position, book in enumerate(books, start=1):
        images = _book_images(player_dir, book, layout)
        if not images:
            continue
        total += len(images)
        raw_code = str(book.get("code") or book.get("dir") or "")
        code = html.escape(raw_code)
        pages = int(book.get("pages") or 0)
        spreads = int(book.get("spreads") or 0)
        done = " · 已下载" if book.get("downloaded") else ""
        source = "对开" if book.get("images") is None and layout != "page" and spreads else "页面"
        if book.get("images") is not None:
            source = "对开" if book.get("layout") == "spread" else "页面"
        rows = []
        for index, image in enumerate(images, start=1):
            href = _href(base_dir, image)
            alt = html.escape(f"{raw_code} {source} {index:03d}")
            rows.append(
                f'<figure><a href="{href}" target="_blank" rel="noopener">'
                f'<img src="{href}" alt="{alt}" loading="lazy" decoding="async"></a>'
                f"<figcaption>{index:03d}</figcaption></figure>"
            )
        sections.append(
            f'<section class="book" id="book-{position}">'
            f'<h2><span class="code">{code}</span>'
            f'<span class="badge">{pages} 页 · {spreads} 对开 · 展示 {len(images)} 张{html.escape(done)}</span></h2>'
            f'<div class="grid">{"".join(rows)}</div></section>'
        )

    if sections:
        body = "".join(sections)
    else:
        body = '<p class="empty">没有可展示的图片。先把 page_*.jpg 下载到该目录。</p>'
    layout_label = "対開 PDF" if layout == "spread" else "单页 PDF"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{player_name} · 写真</title>\n<style>{_CSS}</style>\n</head>\n<body>\n"
        f'<header><h1>{player_name}</h1><p>{len(sections)} 本 · {total} 张 · {layout_label}</p></header>\n'
        f'<main class="gallery" id="gallery">{body}</main>\n'
        "</body>\n</html>\n"
    )


def build_index(player_dir: Path, books: list[dict], layout: str) -> str:
    """返回画廊 HTML（不写文件），便于单独测试。"""
    base = Path(player_dir).expanduser().resolve()
    mode = layout if layout in LAYOUTS else "auto"
    return _render_index(base, books or [], mode, base)


# ---------------------------------------------------------------- 打包

def _empty_result(layout: str) -> dict:
    return {
        "books": 0,
        "pages": 0,
        "layout": layout,
        "pdf": None,
        "pdf_path": None,
        "pdf_bytes": 0,
        "manifest": None,
        "index": None,
        "skipped": [],
    }


def pack_player(
    player_dir: Path,
    out_dir: Path | None = None,
    layout: str = "auto",
    max_height: int = 1600,
) -> dict:
    """打包单个选手目录，返回统计。

    layout: auto 优先 spreads；spread 强制 spreads（缺失回退 pages）；
    page 强制 pages。所有源文件必须位于 player_dir 内。
    """
    base = Path(player_dir).expanduser().resolve()
    requested = layout if layout in LAYOUTS else "auto"
    try:
        max_height = int(max_height)
    except (TypeError, ValueError):
        max_height = 1600
    if max_height < 1:
        max_height = 1600

    if not base.is_dir():
        return _empty_result("page")

    out = Path(out_dir).expanduser().resolve() if out_dir is not None else base
    out.mkdir(parents=True, exist_ok=True)

    books, skipped = _scan_books(base)
    skipped = [entry for book in books for entry in book["skipped"]] + skipped
    has_spreads = any(book["spread_files"] for book in books)
    effective = "spread" if requested != "page" and has_spreads else "page"

    for book in books:
        if effective == "spread" and book["spread_files"]:
            images, source = book["spread_files"], "spread"
        elif book["page_files"]:
            images, source = book["page_files"], "page"
        else:
            images, source = [], None
        book["images"] = images
        book["layout"] = source
        if images:
            size = book["sizes"].get(images[0])
            if size:
                book["resolution"] = f"{size[0]}x{size[1]}"

    selected: list[tuple[str, Path]] = []
    for book in books:
        for image in book["images"]:
            selected.append((_rel(base, image), image))

    safe_name = _safe_filename(base.name)
    pdf_name = f"00_{safe_name}{' 対開' if effective == 'spread' else ''}.pdf"
    pdf_path = out / pdf_name
    pdf_pages = 0
    pdf_error: dict | None = None
    if selected:
        try:
            pdf_pages, pdf_skipped = _write_pdf(selected, pdf_path, max_height)
        except Exception as exc:  # noqa: BLE001 - PDF 写失败也不应炸调用方
            pdf_pages = 0
            pdf_skipped = []
            pdf_error = {"file": pdf_name, "error": f"{type(exc).__name__}: {exc}"[:200]}
            try:
                pdf_path.unlink()
            except OSError:
                pass
        if pdf_skipped:
            skipped.extend(pdf_skipped)
            failed = {entry["file"] for entry in pdf_skipped}
            for book in books:
                book["images"] = [image for image in book["images"] if _rel(base, image) not in failed]
                if not book["images"]:
                    book["layout"] = None
            if pdf_error is None and not any(book["images"] for book in books):
                pdf_pages = 0
                try:
                    pdf_path.unlink()
                except OSError:
                    pass
    if pdf_error is not None:
        skipped.append(pdf_error)

    pdf_ok = pdf_pages > 0 and pdf_path.is_file() and pdf_path.stat().st_size > 0
    pdf_bytes = pdf_path.stat().st_size if pdf_ok else 0

    manifest_path = out / "manifest.json"
    manifest = {
        "player": base.name,
        "layout": effective,
        "requested_layout": requested,
        "max_height": max_height,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "books": [
            {
                "code": book["code"],
                "dir": book["dir"],
                "pages": book["pages"],
                "spreads": book["spreads"],
                "resolution": book["resolution"],
                "downloaded": book["downloaded"],
                "layout": book["layout"],
                **({"skipped": book["skipped"]} if book["skipped"] else {}),
            }
            for book in books
        ],
        "skipped": skipped,
        "pdf": pdf_name if pdf_ok else None,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    index_path = out / "index.html"
    index_path.write_text(_render_index(base, books, effective, out), encoding="utf-8")

    pdf_value = str(pdf_path) if pdf_ok else None
    return {
        "books": len(books),
        "pages": pdf_pages,
        "layout": effective,
        "pdf": pdf_value,
        "pdf_path": pdf_value,
        "pdf_bytes": pdf_bytes,
        "manifest": str(manifest_path),
        "index": str(index_path),
        "skipped": skipped,
    }
