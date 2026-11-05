"""Run with: .venv/bin/python test_player_pack.py

Offline checks for player_pack: only temporary directories are written, no
real ~/Movies data is read.
"""

import json
import shutil
import tempfile
from pathlib import Path

from PIL import Image

import player_pack


def save_jpeg(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG", quality=85)


tmp = Path(tempfile.mkdtemp(prefix="player-pack-test-"))
try:
    player = tmp / "写真" / "测试选手"
    book_one = player / "b001"
    book_two = player / "b002"

    # 书 1：pages + spreads
    for index in range(1, 5):
        save_jpeg(book_one / f"page_{index:03d}.jpg", (900, 1200), (30 * index, 60, 90))
    for index in range(1, 3):
        save_jpeg(book_one / "spreads" / f"spread_{index:03d}.jpg", (1800, 1200), (90, 30 * index, 60))
    (book_one / ".done").write_text("done", encoding="utf-8")

    # 书 2：只有 pages，外加一张坏图和一个越界符号链接
    for index in range(1, 4):
        save_jpeg(book_two / f"page_{index:03d}.jpg", (800, 1200), (40, 30 * index, 120))
    (book_two / ".done").write_text("done", encoding="utf-8")
    (book_two / "page_999.jpg").write_bytes(b"not a jpeg")
    outside = tmp / "outside.jpg"
    save_jpeg(outside, (100, 100), (20, 20, 20))
    try:
        (book_two / "page_004.jpg").symlink_to(outside)
    except OSError:
        pass

    # 越界目录：整个书目录是符号链接
    outside_book = tmp / "outside-book"
    save_jpeg(outside_book / "page_001.jpg", (300, 300), (50, 50, 50))
    try:
        (player / "escape").symlink_to(outside_book, target_is_directory=True)
    except OSError:
        pass

    result = player_pack.pack_player(player)
    assert result["books"] == 2, result
    assert result["layout"] == "spread", result
    assert result["pages"] == 5, result
    assert result["skipped"], result

    manifest_file = player / "manifest.json"
    index_file = player / "index.html"
    pdf_file = Path(result["pdf"])
    assert manifest_file.is_file() and index_file.is_file(), result
    assert pdf_file.is_file() and pdf_file.stat().st_size > 0, result
    assert result["pdf_bytes"] == pdf_file.stat().st_size, result
    assert pdf_file.name == "00_测试选手 対開.pdf", pdf_file

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["layout"] == "spread", manifest
    books = {book["code"]: book for book in manifest["books"]}
    assert set(books) == {"b001", "b002"}, books
    assert books["b001"]["pages"] == 4 and books["b001"]["spreads"] == 2, books["b001"]
    assert books["b001"]["downloaded"] is True and books["b001"]["layout"] == "spread"
    assert books["b001"]["resolution"], books["b001"]
    assert books["b002"]["pages"] == 3 and books["b002"]["spreads"] == 0, books["b002"]
    assert books["b002"]["downloaded"] is True and books["b002"]["layout"] == "page"
    assert any("page_999.jpg" in item["file"] for item in manifest["skipped"]), manifest["skipped"]

    gallery = index_file.read_text(encoding="utf-8")
    assert 'class="gallery"' in gallery, gallery[:200]
    assert 'loading="lazy"' in gallery, gallery[:200]
    assert "b001/spreads/spread_001.jpg" in gallery
    assert "b002/page_001.jpg" in gallery
    assert "page_999.jpg" not in gallery and "page_004.jpg" not in gallery

    # build_index 可独立用 manifest 的 books 调用
    standalone = player_pack.build_index(player, manifest["books"], "auto")
    assert 'class="gallery"' in standalone and 'loading="lazy"' in standalone
    assert "b001/spreads/spread_001.jpg" in standalone
    assert "b002/page_001.jpg" in standalone and "page_999.jpg" not in standalone

    # 强制 page：忽略 spreads，输出到另一个目录
    page_out = tmp / "pack-pages"
    page_result = player_pack.pack_player(player, out_dir=page_out, layout="page")
    assert page_result["layout"] == "page", page_result
    assert page_result["pages"] == 7, page_result
    assert Path(page_result["pdf"]).name == "00_测试选手.pdf", page_result
    page_html = Path(page_result["index"]).read_text(encoding="utf-8")
    assert "b001/page_001.jpg" in page_html and "b001/spreads/" not in page_html
    page_manifest = json.loads((page_out / "manifest.json").read_text(encoding="utf-8"))
    assert page_manifest["layout"] == "page"
    assert {book["code"]: book["layout"] for book in page_manifest["books"]}["b001"] == "page"

    # 强制 spread 但没有 spreads：回退 pages
    pages_only = tmp / "写真" / "只有页面"
    save_jpeg(pages_only / "b101" / "page_001.jpg", (600, 900), (10, 20, 30))
    save_jpeg(pages_only / "b101" / "page_002.jpg", (600, 900), (40, 50, 60))
    fallback = player_pack.pack_player(pages_only, layout="spread")
    assert fallback["layout"] == "page", fallback
    assert fallback["pages"] == 2, fallback
    assert Path(fallback["pdf"]).name == "00_只有页面.pdf", fallback

    # 空目录 / 不存在的目录都不抛异常
    empty = tmp / "empty-player"
    empty.mkdir()
    empty_result = player_pack.pack_player(empty)
    assert empty_result["books"] == 0 and empty_result["pages"] == 0, empty_result
    assert empty_result["pdf"] is None and empty_result["pdf_bytes"] == 0, empty_result
    assert (empty / "manifest.json").is_file() and (empty / "index.html").is_file()
    missing = player_pack.pack_player(tmp / "does-not-exist")
    assert missing["books"] == 0 and missing["pages"] == 0, missing

    # 尺寸缩放分支仍能产出 PDF
    small = player_pack.pack_player(pages_only, out_dir=tmp / "pack-small", max_height=300)
    assert small["pages"] == 2 and Path(small["pdf"]).stat().st_size > 0, small
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("Player pack checks passed")
