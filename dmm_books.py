"""DMM/FANZA 写真集「試し読み」下载与 Publus 解码。

只处理试读页（`*_sample/`）；商品页 → 試し読み链接 → viewerapi/auth →
configuration_pack.json → 逐页 JPEG → 64×64 瓦片还原。
"""

from __future__ import annotations

import json
import os
import re
import ssl
import time
import concurrent.futures as futures
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image


class DownloadCancelled(Exception):
    """用户取消下载。"""


TS = 64
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
DEFAULT_PROXY = "http://127.0.0.1:7897"


def proxy_candidates() -> list[str]:
    """DMM_PROXY 优先，其次 NYAA_PROXY，最后本机 7897；去重保序。"""
    values = (os.environ.get("DMM_PROXY"), os.environ.get("NYAA_PROXY"), DEFAULT_PROXY)
    return [item for item in dict.fromkeys(value.strip() for value in values if value) if item]
BOOK_URL = "https://book.dmm.co.jp/product/{series}/{code}/"
MAX_PAGES = 30
MAX_BOOK_PAGES = 500

_OPENERS: dict[str, urllib.request.OpenerDirector] = {}


def _opener(proxy: str | None) -> urllib.request.OpenerDirector:
    key = proxy or ""
    opener = _OPENERS.get(key)
    if opener is not None:
        return opener
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    handlers: list[urllib.request.BaseHandler] = [urllib.request.HTTPSHandler(context=context)]
    if proxy:
        handlers.insert(0, urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    _OPENERS[key] = opener
    return opener


def get(url: str, referer: str = "https://book.dmm.co.jp/", timeout: int = 60,
        retries: int = 3) -> bytes:
    """带年龄 cookie、代理与重试的 GET；非 ASCII URL 先编码。"""
    target = urllib.parse.quote(url, safe=":/?&=%#+,;@!$'()*[]~")
    request = urllib.request.Request(target, headers={
        "User-Agent": UA,
        "Referer": referer,
        "Cookie": "age_check_done=1",
        "Accept": "*/*",
    })
    last: Exception | None = None
    for attempt in range(retries):
        blocked = False
        for proxy in proxy_candidates():
            try:
                with _opener(proxy).open(request, timeout=timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (403, 429):
                    blocked = True
                    break
            except Exception as exc:  # noqa: BLE001
                last = exc
        if attempt + 1 < retries:
            time.sleep((3.0 if blocked else 1.0) * (attempt + 1))
    raise RuntimeError(f"抓取失败：{last}") from last


def _decode(url: str, referer: str = "https://book.dmm.co.jp/") -> str:
    return get(url, referer=referer).decode("utf-8", "replace")


def normalize_proxy(value: str) -> str:
    """规范化代理地址；空串表示清空，交由 NYAA_PROXY/7897 回退。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("代理地址需为 http://host:port 或 https://host:port")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("代理地址不能包含路径、查询或片段")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("代理端口不合法") from exc
    return text


def _probe(proxy: str, url: str, timeout: int, read_limit: int = 0) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Cookie": "age_check_done=1",
    })
    with _opener(proxy).open(request, timeout=timeout) as response:
        data = response.read(read_limit) if read_limit else response.read()
        return response.status, data


def check_proxy(proxy: str, timeout: int = 8) -> dict:
    """检查代理出口地区与 DMM 可达性；供设置页“检测代理”使用。"""
    result = {"proxy": proxy, "ok": False, "country": "", "city": "", "ip": "",
              "latency_ms": None, "dmm_ok": False, "dmm_status": None, "error": ""}
    started = time.time()
    try:
        status, body = _probe(proxy, "https://ipinfo.io/json", timeout)
        info = json.loads(body.decode("utf-8", "replace"))
        result.update(country=str(info.get("country") or ""), city=str(info.get("city") or ""),
                      ip=str(info.get("ip") or ""))
        result["latency_ms"] = int((time.time() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"出口检测失败：{str(exc)[:150]}"
    try:
        status, _ = _probe(proxy, "https://book.dmm.co.jp/", timeout, read_limit=512)
        result["dmm_status"] = status
        result["dmm_ok"] = 200 <= status < 400
        if result["latency_ms"] is None:
            result["latency_ms"] = int((time.time() - started) * 1000)
    except urllib.error.HTTPError as exc:
        result["dmm_status"] = exc.code
        result["dmm_ok"] = exc.code not in (403, 451)
        result["error"] = f"DMM 返回 HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"DMM 检测失败：{str(exc)[:150]}"
    result["ok"] = bool(result["dmm_ok"] or result["country"])
    return result


def check_proxies(timeout: int = 8) -> list[dict]:
    candidates = proxy_candidates()
    if not candidates:
        return []
    with futures.ThreadPoolExecutor(max_workers=len(candidates)) as pool:
        return list(pool.map(lambda item: check_proxy(item, timeout), candidates))


def _products(html: str) -> list[tuple[str, str]]:
    return re.findall(r"/product/([a-z0-9]+)/([a-z0-9]+)/", html)


def list_books(dmm_id: str, max_pages: int = MAX_PAGES, on_progress=None) -> list[dict[str, str]]:
    """DMM 女优页的全部作品（按 code 去重）；后续页并发抓取。"""
    dmm_id = str(dmm_id or "").strip()
    if not re.fullmatch(r"\d{1,12}", dmm_id):
        return []
    first_url = f"https://book.dmm.co.jp/list/?actress={dmm_id}"
    html = _decode(first_url)
    total = re.search(r'data-total="(\d+)"', html)
    pages = max(1, (int(total.group(1)) + 119) // 120) if total else 1
    pages = min(pages, max_pages)
    found: dict[str, str] = {}
    for series, code in _products(html):
        found.setdefault(code, series)
    if on_progress is not None:
        on_progress(1, pages)
    if pages > 1:
        with futures.ThreadPoolExecutor(max_workers=3) as pool:
            tasks = {pool.submit(_decode, f"{first_url}&page={page}"): page
                     for page in range(2, pages + 1)}
            for future in futures.as_completed(tasks):
                page = tasks[future]
                try:
                    body = future.result()
                except Exception:  # noqa: BLE001
                    body = ""
                for series, code in _products(body):
                    found.setdefault(code, series)
                if on_progress is not None:
                    on_progress(page, pages)
    return [{"series": series, "code": code} for code, series in found.items()]


def search_books(name: str, max_pages: int = 5, on_progress=None) -> list[dict[str, str]]:
    """没有 DMM id 时按名字搜索（可能混入收录该女优的杂志）。"""
    query = urllib.parse.quote(str(name or "").strip())
    if not query:
        return []
    found: dict[str, str] = {}
    for page in range(1, max_pages + 1):
        url = f"https://book.dmm.co.jp/search/?searchstr={query}"
        if page > 1:
            url += f"&page={page}"
        try:
            html = _decode(url)
        except Exception:  # noqa: BLE001
            break
        products = _products(html)
        if not products:
            break
        before = len(found)
        for series, code in products:
            found.setdefault(code, series)
        if on_progress is not None:
            on_progress(page, max_pages)
        if len(found) == before:
            break
    return [{"series": series, "code": code} for code, series in found.items()]


# --------------------------------------------------------------------------
# Publus 置换（与 publus-viewer.js 的 Wu() 一致）
# --------------------------------------------------------------------------
def _vn(n: int, e: int, t: int, r: int) -> int:
    return n * r + (t if n >= e else 0)


def _qi(n: int, e: int, t: int, r: int, i: int) -> int:
    odd = (i % 2 == 1)
    use = odd if n < e else (not odd)
    length, offset = (t, 0) if use else (r - t, t)
    return (n + 53 * i + 59 * t) % length + offset


def _es(n: int, e: int, t: int, r: int, i: int) -> int:
    odd = (i % 2 == 1)
    use = odd if n < t else (not odd)
    length, offset = (r - e, e) if use else (e, 0)
    return (n + 67 * i + e + 71) % length + offset


def wu(width: int, height: int, pattern: int, ts: int = TS) -> list[tuple[int, int, int, int, int, int]]:
    """返回 [(realX, realY, scrambledX, scrambledY, w, h), ...]。"""
    u, c = width // ts, height // ts
    d, h = width % ts, height % ts
    if u < 1 or c < 1:
        return []
    ops: list[tuple[int, int, int, int, int, int]] = []

    f = u - (43 * pattern) % u
    if f % u == 0:
        f = (u - 4) % u
    if f == 0:
        f = u - 1
    g = c - (47 * pattern) % c
    if g % c == 0:
        g = (c - 4) % c
    if g == 0:
        g = c - 1

    if d > 0 and h > 0:
        ops.append((f * ts, g * ts, f * ts, g * ts, d, h))

    if h > 0:
        for index in range(u):
            z = (index + 61 * pattern) % u
            j = _qi(z, f, g, c, pattern)
            ops.append((_vn(index, f, d, ts), g * ts, _vn(z, f, d, ts), j * ts, ts, h))

    if d > 0:
        for index in range(c):
            j = (index + 73 * pattern) % c
            z = _es(j, f, g, u, pattern)
            ops.append((f * ts, _vn(index, g, h, ts), z * ts, _vn(j, g, h, ts), d, ts))

    for index in range(u):
        for s in range(c):
            z = (index + 29 * pattern + 31 * s) % u
            j = (s + 37 * pattern + 41 * z) % c
            extra_x = d if z >= _es(j, f, g, u, pattern) else 0
            extra_y = h if j >= _qi(z, f, g, c, pattern) else 0
            ops.append((index * ts + (d if index >= f else 0),
                        s * ts + (h if s >= g else 0),
                        z * ts + extra_x, j * ts + extra_y, ts, ts))
    return ops


def pattern_for(key: str) -> int:
    """key = '<file>/<pageNo>'，例如 'item/xhtml/p-0001.xhtml/0' -> 1..4。"""
    return sum(ord(ch) for ch in key) % 4 + 1


def unscramble(data: bytes, key: str, dummy_w: int = 0, dummy_h: int = 0) -> Image.Image:
    source = Image.open(BytesIO(data)).convert("RGB")
    width, height = source.size
    canvas = Image.new("RGB", (width, height))
    for real_x, real_y, source_x, source_y, tile_w, tile_h in wu(width, height, pattern_for(key)):
        if tile_w > 0 and tile_h > 0:
            canvas.paste(source.crop((source_x, source_y, source_x + tile_w, source_y + tile_h)),
                         (real_x, real_y))
    if dummy_w or dummy_h:
        canvas = canvas.crop((0, 0, width - dummy_w, height - dummy_h))
    return canvas


# --------------------------------------------------------------------------
# 单本下载
# --------------------------------------------------------------------------
def _trial_url(series: str, code: str) -> str:
    page = _decode(BOOK_URL.format(series=series, code=code))
    match = re.search(r'href="(https?://book\.dmm\.co\.jp/product/[^"]+/tachiyomi/[^"]+)"', page)
    if not match:
        match = re.search(r'href="(/product/[^"]+/tachiyomi/[^"]+)"', page)
        if not match:
            raise RuntimeError("这本书没有試し読み")
        return "https://book.dmm.co.jp" + match.group(1).replace("&amp;", "&")
    return match.group(1).replace("&amp;", "&")


def download_book(series: str, code: str, outdir: Path, on_page=None, should_stop=None) -> int:
    """下载并还原一本书，返回页数；失败抛异常。"""
    def check_stop() -> None:
        if should_stop is not None and should_stop():
            raise DownloadCancelled("已取消")

    check_stop()
    if not re.fullmatch(r"[a-z0-9]+", series or "") or not re.fullmatch(r"[a-z0-9]+", code or ""):
        raise ValueError("非法作品编号")
    check_stop()
    trial = _trial_url(series, code)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(trial).query)
    if "cid" not in query:
        raise RuntimeError("試し読み链接缺少 cid")
    cid = query["cid"][0]
    lin = query.get("lin", ["1"])[0]

    check_stop()
    auth = json.loads(get(f"https://book.dmm.co.jp/viewerapi/auth/?cid={urllib.parse.quote(cid)}&lin={lin}",
                          referer=trial))
    base = auth["url"]
    info = auth["auth_info"]
    qs = ("Policy=" + urllib.parse.quote(info["Policy"], safe="") +
          "&Signature=" + urllib.parse.quote(info["Signature"], safe="") +
          "&Key-Pair-Id=" + (info.get("Key-Pair-Id") or info.get("key-pair-id") or ""))
    check_stop()
    pack = json.loads(get(f"{base}configuration_pack.json?{qs}"))
    contents = (pack.get("configuration") or {}).get("contents") or []
    if not contents:
        raise RuntimeError("试读清单为空")

    total_pages = 0
    for item in contents:
        file_key = str(item.get("file") or "")
        links = (pack.get(file_key) or {}).get("FileLinkInfo") or {}
        total_pages += int(links.get("PageCount") or 0)

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    count = 0
    for item in contents:
        file_key = str(item.get("file") or "")
        if not file_key:
            continue
        kind = "jpeg" if item.get("type") in ("jpeg", "bmp") else (item.get("type") or "jpeg")
        links = (pack.get(file_key) or {}).get("FileLinkInfo") or {}
        for index in range(int(links.get("PageCount") or 1)):
            page_list = links.get("PageLinkInfoList") or []
            if index >= len(page_list):
                break
            check_stop()
            page = page_list[index].get("Page") or {}
            key = f"{file_key}/{page.get('No', 0)}"
            data = get(f"{base}{key}.{kind}?{qs}")
            image = unscramble(data, key,
                               int(page.get("DummyWidth") or 0),
                               int(page.get("DummyHeight") or 0))
            count += 1
            check_stop()
            image.save(outdir / f"page_{count:03d}.jpg", quality=95)
            if on_page is not None:
                on_page(count, total_pages)
            if count >= MAX_BOOK_PAGES:
                return count
    if not count:
        raise RuntimeError("试读没有下载到任何页面")
    try:
        _write_spreads(outdir)
    except Exception as exc:  # noqa: BLE001
        print(f"[dmm] spread failed {code}: {exc}", flush=True)
    return count


def _write_spreads(outdir: Path) -> None:
    """试读按对开页左右半分发：1 单独，其后 [左=奇数页, 右=偶数页]。"""
    pages = sorted(outdir.glob("page_*.jpg"))
    if not pages:
        return
    folder = outdir / "spreads"
    folder.mkdir(exist_ok=True)
    with Image.open(pages[0]) as cover:
        cover.convert("RGB").save(folder / "spread_001.jpg", quality=88)
    index = 1
    seq = 1
    while index < len(pages):
        right = Image.open(pages[index]).convert("RGB")
        try:
            left = None
            if index + 1 < len(pages):
                with Image.open(pages[index + 1]) as left_source:
                    left = left_source.convert("RGB")
            seq += 1
            if left is None:
                right.save(folder / f"spread_{seq:03d}.jpg", quality=88)
            else:
                height = max(left.height, right.height)
                canvas = Image.new("RGB", (left.width + right.width, height), (0, 0, 0))
                canvas.paste(left, (0, 0))
                canvas.paste(right, (left.width, 0))
                canvas.save(folder / f"spread_{seq:03d}.jpg", quality=88)
                canvas.close()
        finally:
            right.close()
            if left is not None:
                left.close()
        index += 2
