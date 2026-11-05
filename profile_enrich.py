"""从 theidolbase / theactorbase / javdatabase 补全选手基础资料。

只用 stdlib（urllib + re），供后端 refresh 接口调用；导入本模块不会发起
任何网络请求。所有抓取失败都降级为空字符串 / 空字典，由调用方决定是否提示。
"""

from __future__ import annotations

import datetime as _datetime
import html as _html
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

PROXY = (os.environ.get("PROFILE_PROXY")
         or os.environ.get("NYAA_PROXY")
         or "http://127.0.0.1:7897")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TIMEOUT = 20
RETRIES = 2

THEIDOLBASE_URL = "https://www.theidolbase.com/actress/{slug}"
ACTORBASE_URL = "https://www.theactorbase.com/people/{slug}"
JAVDATABASE_URL = "https://www.javdatabase.com/idols/{slug}"

_OPENERS: dict[str, urllib.request.OpenerDirector] = {}

_ENRICH_FIELDS = ("birthday", "height", "measurements", "agency", "debut",
                  "chinese_name", "blood_type")


# --------------------------------------------------------------------------
# 抓取
# --------------------------------------------------------------------------
def _effective_proxy(proxy: str | None) -> str:
    return PROXY if proxy is None else str(proxy).strip()


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    """按代理复用 opener；不校验证书（与 dmm_books 一致）。"""
    opener = _OPENERS.get(proxy)
    if opener is not None:
        return opener
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    handlers: list[urllib.request.BaseHandler] = [
        urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {}),
        urllib.request.HTTPSHandler(context=context),
    ]
    opener = urllib.request.build_opener(*handlers)
    _OPENERS[proxy] = opener
    return opener


def fetch_html(url: str, proxy: str | None = None) -> str:
    """经代理抓取 HTML；失败返回 ""（重试 RETRIES 次）。"""
    target = str(url or "").strip()
    if not target:
        return ""
    target = urllib.parse.quote(target, safe=":/?&=%#+,;@!$'()*[]~")
    request = urllib.request.Request(target, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
    })
    effective = _effective_proxy(proxy)
    for attempt in range(RETRIES):
        try:
            with _opener(effective).open(request, timeout=TIMEOUT) as response:
                return response.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - 网络异常一律视为无资料
            if attempt + 1 < RETRIES:
                time.sleep(1.0 * (attempt + 1))
    return ""


# --------------------------------------------------------------------------
# 文本与字段解析
# --------------------------------------------------------------------------
_SCRIPT_RE = re.compile(r"<script\b.*?</script\s*>", re.I | re.S)
_STYLE_RE = re.compile(r"<style\b.*?</style\s*>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")

_DATE_RE = re.compile(
    r"(?<!\d)(\d{4})\s*[年./\-]\s*(\d{1,2})\s*[月./\-]\s*(\d{1,2})(?!\d)")
_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_MONTH_DAY_DASH_RE = re.compile(r"(\d{1,2})\s*[-/]\s*(\d{1,2})")
_BORN_RE = re.compile(
    r"出生于\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")

_HEIGHT_RE = re.compile(r"(?<!\d)(\d{2,3})\s*(?:cm|厘米|公分)(?![a-z])", re.I)
_BARE_NUMBER_RE = re.compile(r"(?<!\d)(\d{2,3})(?!\d)")

_BWH_RE = re.compile(
    r"B\s*[:：]?\s*(\d{2,3})\s*(?:[（(]\s*([A-Za-z]{1,2})\s*[)）])?"
    r".{0,60}?W\s*[:：]?\s*(\d{2,3}).{0,60}?H\s*[:：]?\s*(\d{2,3})",
    re.I | re.S)
_TRIPLE_RE = re.compile(
    r"(?<!\d)(\d{2,3})\s*[-–—]\s*(\d{2,3})\s*[-–—]\s*(\d{2,3})(?!\d)")
_CUP_DETAIL_RE = re.compile(r"B\s*\d{2,3}\s*[（(]\s*[A-Za-z]{1,2}\s*[)）]")

_CJK_RE = r"[\u3400-\u4dbf\u4e00-\u9fff·]"
_CHINESE_NAME_RE = re.compile(r"中文名\s*[：:]\s*(" + _CJK_RE + r"{2,12})")
_BLOOD_TYPE_RE = re.compile(r"血型\s*[：:]\s*(AB|A|B|O)", re.I)
_SOCIAL_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:x|twitter|instagram)\.com/[^\s\"'<>\\]*", re.I)

# 站点自己的账号 / JSON-LD Organization.sameAs，绝不能当成女优社媒。
_SITE_HANDLES = {
    "wwwtheactorbasecom", "theactorbasecom", "theactorbase",
    "wwwtheidolbasecom", "theidolbasecom", "theidolbase",
    "wwwjavdatabasecom", "javdatabasecom", "javdatabase", "javdb",
    "dmm", "fanza", "avfan",
}
_SITE_NAME_HINTS = ("theactorbase", "theidolbase", "javdatabase", "javdb")

# 人物页里明确的社媒容器；只在这里找链接，不扫整页/页脚。
_SOCIAL_BLOCK_RE = re.compile(
    r'<div\b[^>]*class=["\'][^"\']*\bsocial-links\b[^"\']*["\'][^>]*>.*?</div>',
    re.S | re.I)
_SIDEBAR_RE = re.compile(
    r'<aside\b[^>]*class=["\'][^"\']*\bsidebar\b[^"\']*["\'][^>]*>.*?</aside>',
    re.S | re.I)

_AGENCY_LABELS = ("事务所", "事務所", "经纪公司", "經紀公司", "所属", "所屬",
                  "Agency")
_DEBUT_LABELS = ("出道时间", "出道時間", "出道", "デビュー", "Debut")


def _text_lines(markup: str) -> list[str]:
    """HTML → 去标签的文本行；块级标签一律变行界。"""
    text = _SCRIPT_RE.sub(" ", markup or "")
    text = _STYLE_RE.sub(" ", text)
    text = _TAG_RE.sub("\n", text)
    text = _html.unescape(text)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return [line for line in lines if line]


def _label_candidates(lines: list[str], labels, span: int = 3):
    """产出标签后的候选值：同行剩余部分 + 后续 span 行。

    只认行首标签（可带项目符号），避免正文里“转投某事务所”之类的误命中。
    """
    if isinstance(labels, str):
        labels = (labels,)
    for index, raw in enumerate(lines):
        clean = raw.lstrip("·•*-— \t")
        lowered = clean.lower()
        for label in labels:
            if not lowered.startswith(label.lower()):
                continue
            rest = clean[len(label):]
            if label.isascii() and rest[:1].isalnum():
                continue
            rest = rest.lstrip(" ：:")
            values = [rest] if rest else []
            values.extend(lines[index + 1:index + 1 + span])
            if values:
                yield values


def _first_text(values) -> str:
    for value in values:
        if value:
            return value
    return ""


def _make_birthday(year: str, month: str, day: str) -> str:
    try:
        number = int(year) if year else 2000
        value = _datetime.date(number, int(month), int(day))
    except (TypeError, ValueError):
        return ""
    if year and not 1900 <= int(year) <= 2100:
        return ""
    return value.strftime("%Y-%m-%d") if year else value.strftime("%m-%d")


def _birthday_from_text(text: str) -> str:
    """提取 YYYY-MM-DD；只有月日时返回 MM-DD。"""
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    for match in _DATE_RE.finditer(text):
        value = _make_birthday(match.group(1), match.group(2), match.group(3))
        if value:
            return value
    match = _BORN_RE.search(text)
    if match:
        value = _make_birthday(match.group(1), match.group(2), match.group(3))
        if value:
            return value
    match = _MONTH_DAY_RE.search(text)
    if match:
        value = _make_birthday("", match.group(1), match.group(2))
        if value:
            return value
    match = _MONTH_DAY_DASH_RE.fullmatch(text.strip())
    if match:
        return _make_birthday("", match.group(1), match.group(2))
    return ""


def _height_from_text(text: str) -> str:
    """返回 120—220 之间的纯数字身高字符串。"""
    text = str(text or "")
    match = _HEIGHT_RE.search(text)
    numbers = [match.group(1)] if match else _BARE_NUMBER_RE.findall(text)
    for candidate in numbers:
        number = int(candidate)
        if 120 <= number <= 220:
            return str(number)
    return ""


def _format_measurements(bust: str, waist: str, hip: str, cup: str = "") -> str:
    try:
        b, w, h = int(bust), int(waist), int(hip)
    except (TypeError, ValueError):
        return ""
    if not (50 <= b <= 150 and 40 <= w <= 130 and 60 <= h <= 150):
        return ""
    cup_text = f"({cup.upper()})" if cup and re.fullmatch(r"[A-Za-z]{1,2}", cup) else ""
    return f"B{b}{cup_text}-W{w}-H{h}"


def _measurements_from_text(text: str, bare: bool = False) -> str:
    """B82-W55-H82 / B:80 / W:58 / H:83 / 88-58-90 → 统一格式。"""
    text = str(text or "")
    if not text:
        return ""
    match = _BWH_RE.search(text)
    if match:
        value = _format_measurements(match.group(1), match.group(3),
                                     match.group(4), match.group(2) or "")
        if value:
            return value
    if bare:
        match = _TRIPLE_RE.search(text)
        if match:
            return _format_measurements(match.group(1), match.group(2), match.group(3))
    return ""


def _has_cup_detail(value: str) -> bool:
    return bool(_CUP_DETAIL_RE.search(str(value or "")))


def _chinese_name_from_values(values) -> str:
    for value in values:
        candidate = str(value or "").strip(" ：:·")
        if re.fullmatch(_CJK_RE + r"{2,12}", candidate):
            return candidate
    return ""


def _blood_type_from_values(values) -> str:
    for value in values:
        candidate = str(value or "").replace(" ", "").strip("：:型")
        if re.fullmatch(r"(AB|A|B|O)", candidate, re.I):
            return candidate.upper()
    return ""


def _debut_year(text: str) -> str:
    match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", str(text or ""))
    if match and 1950 <= int(match.group(1)) <= 2035:
        return match.group(1)
    return ""


def _clean_agency(text: str) -> str:
    value = " ".join(str(text or "").split())
    if not value or len(value) > 60 or value in ("?", "-", "—"):
        return ""
    if re.search(r"[。！？；]", value):
        return ""
    return value


def _is_site_handle(handle: str) -> bool:
    """判断 handle 是否属于站点自己（wwwtheactorbasecom 等）。"""
    normalized = re.sub(r"[^a-z0-9]", "", str(handle or "").lower())
    if not normalized:
        return True
    if normalized in _SITE_HANDLES:
        return True
    return any(hint in normalized for hint in _SITE_NAME_HINTS)


def _clean_social_url(url: str) -> str:
    """规范成账号主页：x.com/<user>、instagram.com/<user>。

    站点自有账号一律丢弃；无法确认归属时由调用方决定不写入资料。
    """
    value = _html.unescape(str(url or "")).strip()
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return ""
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    is_x = host in ("x.com", "twitter.com") or host.endswith(".x.com") or host.endswith(".twitter.com")
    is_instagram = host == "instagram.com" or host.endswith(".instagram.com")
    if not (is_x or is_instagram):
        return ""
    segments = [part for part in parsed.path.split("/") if part]
    if not segments:
        return ""
    if is_x:
        if segments[0] in ("intent", "share", "home", "i", "hashtag"):
            return ""
        if "status" in segments:
            segments = segments[:segments.index("status")]
        if not segments or _is_site_handle(segments[0]):
            return ""
        return f"https://x.com/{segments[0]}"
    if segments[0] in ("p", "reel", "reels", "stories", "tv", "explore", "accounts"):
        return ""
    if _is_site_handle(segments[0]):
        return ""
    return f"https://instagram.com/{segments[0]}"


def _social_from_scopes(scopes) -> dict[str, str]:
    social: dict[str, str] = {}
    for scope in scopes:
        for match in _SOCIAL_URL_RE.finditer(scope):
            url = _clean_social_url(match.group(0))
            if not url:
                continue
            key = "instagram" if "instagram.com" in url else "x"
            social.setdefault(key, url)
    return social


def _social_from_html(markup: str, aside: bool = False) -> dict[str, str]:
    """只在人物区容器里找社媒；先剥掉 script/style（JSON-LD 的 sameAs）。"""
    clean = _STYLE_RE.sub(" ", _SCRIPT_RE.sub(" ", markup or ""))
    if aside:
        asides = [match.group(0) for match in _SIDEBAR_RE.finditer(clean)]
        if asides:
            return _social_from_scopes(asides)
    blocks = [match.group(0) for match in _SOCIAL_BLOCK_RE.finditer(clean)]
    return _social_from_scopes(blocks)


# --------------------------------------------------------------------------
# 各站点解析
# --------------------------------------------------------------------------
def parse_theidolbase(html: str) -> dict:
    """人物页文本 → birthday/height/measurements/chinese_name/blood_type。"""
    if not html or not html.strip():
        return {}
    lines = _text_lines(html)
    if not lines:
        return {}
    result: dict = {}

    birthday = _first_text(
        _birthday_from_text(" ".join(values))
        for values in _label_candidates(lines, ("出生日期", "生日")))
    if not birthday:
        # 没有标签时只认明确的“出生于…”，不拿正文里的其他日期凑数
        match = _BORN_RE.search(" ".join(lines))
        if match:
            birthday = _make_birthday(match.group(1), match.group(2), match.group(3))
    if birthday:
        result["birthday"] = birthday

    height = _first_text(
        _height_from_text(" ".join(values))
        for values in _label_candidates(lines, "身高"))
    if height:
        result["height"] = height

    measurements = _first_text(
        _measurements_from_text(" ".join(values), bare=False)
        for values in _label_candidates(lines, ("三围", "三圍", "BWH")))
    if not measurements:
        for values in _label_candidates(lines, ("三围", "三圍", "BWH")):
            measurements = _measurements_from_text(" ".join(values), bare=True)
            if measurements:
                break
    if measurements:
        result["measurements"] = measurements

    chinese_name = _first_text(
        _chinese_name_from_values(values)
        for values in _label_candidates(lines, "中文名"))
    if not chinese_name:
        match = _CHINESE_NAME_RE.search(" ".join(lines))
        if match:
            chinese_name = match.group(1)
    if chinese_name:
        result["chinese_name"] = chinese_name

    blood_type = _first_text(
        _blood_type_from_values(values)
        for values in _label_candidates(lines, "血型"))
    if not blood_type:
        match = _BLOOD_TYPE_RE.search(" ".join(lines))
        if match:
            blood_type = match.group(1).upper()
    if blood_type:
        result["blood_type"] = blood_type

    social = _social_from_html(html, aside=True)
    if social:
        result["social"] = social
    return result


def parse_actorbase(html: str) -> dict:
    """theactorbase 人物页；结构不认识时返回 {}。"""
    if not html or not html.strip():
        return {}
    lines = _text_lines(html)
    if not lines:
        return {}
    result: dict = {}

    birthday = _first_text(
        _birthday_from_text(" ".join(values))
        for values in _label_candidates(lines, ("生日", "出生日期")))
    if birthday:
        result["birthday"] = birthday

    height = _first_text(
        _height_from_text(" ".join(values))
        for values in _label_candidates(lines, "身高"))
    if height:
        result["height"] = height

    measurements = _first_text(
        _measurements_from_text(" ".join(values), bare=True)
        for values in _label_candidates(lines, ("三围", "三圍")))
    if measurements:
        result["measurements"] = measurements

    agency = ""
    for values in _label_candidates(lines, _AGENCY_LABELS, span=2):
        agency = _first_text(_clean_agency(value) for value in values[:1])
        if agency:
            break
    if agency:
        result["agency"] = agency

    debut = _first_text(
        _debut_year(" ".join(values))
        for values in _label_candidates(lines, _DEBUT_LABELS))
    if debut:
        result["debut"] = debut

    chinese_name = _first_text(
        _chinese_name_from_values(values)
        for values in _label_candidates(lines, "中文名"))
    if chinese_name:
        result["chinese_name"] = chinese_name

    blood_type = _first_text(
        _blood_type_from_values(values)
        for values in _label_candidates(lines, "血型"))
    if blood_type:
        result["blood_type"] = blood_type

    social = _social_from_html(html, aside=True)
    if social:
        result["social"] = social
    return result


def parse_javdatabase(html: str) -> dict:
    """javdatabase 人物页（<li>/<b>Label:</b> 表格）；拿不到就返回 {}。"""
    if not html or not html.strip():
        return {}
    lines = _text_lines(html)
    if not lines:
        return {}
    result: dict = {}

    birthday = _first_text(
        _birthday_from_text(" ".join(values))
        for values in _label_candidates(
            lines, ("DOB", "Birthday", "Birthdate", "生日", "出生日期")))
    if birthday:
        result["birthday"] = birthday

    height = _first_text(
        _height_from_text(" ".join(values))
        for values in _label_candidates(lines, ("Height", "身高")))
    if height:
        result["height"] = height

    measurements = _first_text(
        _measurements_from_text(" ".join(values), bare=True)
        for values in _label_candidates(
            lines, ("Measurements", "BWH", "三围", "三圍")))
    if measurements:
        result["measurements"] = measurements

    agency = ""
    for values in _label_candidates(lines, _AGENCY_LABELS, span=2):
        agency = _first_text(_clean_agency(value) for value in values[:1])
        if agency:
            break
    if agency:
        result["agency"] = agency

    debut = _first_text(
        _debut_year(" ".join(values))
        for values in _label_candidates(lines, _DEBUT_LABELS))
    if debut:
        result["debut"] = debut

    return result


# --------------------------------------------------------------------------
# 聚合
# --------------------------------------------------------------------------
_SOURCES = (
    ("theidolbase", THEIDOLBASE_URL, parse_theidolbase),
    ("actorbase", ACTORBASE_URL, parse_actorbase),
    ("javdatabase", JAVDATABASE_URL, parse_javdatabase),
)


def slug_candidates(roman_name: str) -> list[str]:
    """'Akari Tsumugi' → ['akari-tsumugi', 'tsumugi-akari']。"""
    tokens = re.findall(r"[a-z0-9]+", str(roman_name or "").lower())
    if not tokens:
        return []
    forward = "-".join(tokens)
    reverse = "-".join(reversed(tokens))
    return list(dict.fromkeys([forward, reverse]))


def enrich(roman_name: str, japanese_name: str = "", name: str = "") -> dict:
    """依次查三个站点，按 theidolbase > actorbase > javdatabase 合并。

    japanese_name 预留给后续精确检索；roman_name 为空时退回 name 里的
    ASCII 词。返回字段永远是完整集合，找不到就是空值。
    """
    result: dict = {
        "birthday": "", "height": "", "measurements": "", "agency": "",
        "debut": "", "social": {}, "chinese_name": "", "blood_type": "",
        "sources": [],
    }
    slugs = slug_candidates(roman_name) or slug_candidates(name)
    if not slugs:
        return result

    for _source, template, parser in _SOURCES:
        for slug in slugs:
            url = template.format(slug=slug)
            html = fetch_html(url)
            if not html:
                continue
            try:
                data = parser(html)
            except Exception:  # noqa: BLE001 - 单站解析失败不影响其他源
                data = {}
            if not data:
                continue
            for field in _ENRICH_FIELDS:
                if result[field] or not isinstance(data.get(field), str):
                    continue
                value = data[field].strip()
                if not value:
                    continue
                if field == "birthday":
                    value = _birthday_from_text(value)
                elif field == "height":
                    value = _height_from_text(value)
                elif field == "measurements":
                    value = _measurements_from_text(value, bare=True)
                elif field == "debut":
                    value = _debut_year(value)
                elif field == "chinese_name":
                    value = _chinese_name_from_values([value])
                elif field == "blood_type":
                    value = _blood_type_from_values([value])
                elif field == "agency":
                    value = _clean_agency(value)
                if value:
                    result[field] = value
            social = data.get("social")
            if isinstance(social, dict):
                for key in ("x", "instagram"):
                    if result["social"].get(key):
                        continue
                    value = social.get(key)
                    if isinstance(value, str):
                        url_value = _clean_social_url(value)
                        if url_value:
                            result["social"][key] = url_value
            if url not in result["sources"]:
                result["sources"].append(url)
            break
    return result


# --------------------------------------------------------------------------
# 合并进 profile
# --------------------------------------------------------------------------
_PROFILE_FIELDS = {
    "height": ("height",),
    "measurements": ("measurements",),
    "birthday": ("birthday",),
    "agency": ("agency",),
    "debut": ("debutYear", "debut"),
    "chinese_name": ("chineseName", "chinese_name"),
    "blood_type": ("bloodType", "blood_type"),
}

_FIELD_LABELS = (
    ("height", "身高", _height_from_text),
    ("measurements", "三围", lambda value: _measurements_from_text(value, bare=True)),
    ("birthday", "生日", _birthday_from_text),
    ("agency", "事务所", _clean_agency),
    ("debut", "出道", _debut_year),
    ("chinese_name", "中文名", lambda value: _chinese_name_from_values([value])),
    ("blood_type", "血型", lambda value: _blood_type_from_values([value])),
)

_LABEL_ORDER = ("身高", "三围", "生日", "事务所", "出道", "社媒", "中文名", "血型")


def _profile_key(profile: dict, field: str) -> str:
    for key in _PROFILE_FIELDS[field]:
        if key in profile:
            return key
    return _PROFILE_FIELDS[field][0]


def merge_profile(profile: dict, data: dict, force: bool = False) -> tuple[dict, list[str]]:
    """把 enrich() 结果合并进 profile。

    默认只补空字段；force=True 用 data 非空值覆盖（measurements 若已有
    罩杯细节如 B82(B)-W55-H82，不会被 B82-W55-H82 覆盖）。social 只补
    缺失的 x/instagram，从不覆盖已有；sources 只追加去重，不计入标签。
    返回 (新 profile, 中文更新字段标签)。debut 写入 profile 的
    debutYear（若 profile 已有 debut 键则沿用），中文名/血型同理。
    """
    source = profile if isinstance(profile, dict) else {}
    payload = data if isinstance(data, dict) else {}
    updated = dict(source)
    if isinstance(updated.get("social"), dict):
        updated["social"] = dict(updated["social"])
    if isinstance(updated.get("sources"), list):
        updated["sources"] = list(updated["sources"])

    changed: set[str] = set()
    for field, label, cleaner in _FIELD_LABELS:
        incoming_raw = payload.get(field)
        if not isinstance(incoming_raw, str) or not incoming_raw.strip():
            continue
        incoming = cleaner(incoming_raw)
        if not incoming:
            continue
        key = _profile_key(updated, field)
        existing_raw = updated.get(key, "")
        existing = existing_raw.strip() if isinstance(existing_raw, str) else ""
        if field == "measurements" and existing:
            if _has_cup_detail(existing) and not _has_cup_detail(incoming):
                continue
        if existing and not force:
            continue
        if existing == incoming:
            continue
        updated[key] = incoming
        changed.add(label)

    social_in = payload.get("social")
    if isinstance(social_in, dict):
        target = updated.get("social")
        target = dict(target) if isinstance(target, dict) else {}
        social_changed = False
        for key in ("x", "instagram"):
            if target.get(key):
                continue
            value = social_in.get(key)
            if not isinstance(value, str):
                continue
            url = _clean_social_url(value)
            if url:
                target[key] = url
                social_changed = True
        if target:
            updated["social"] = target
        if social_changed:
            changed.add("社媒")

    source_urls = payload.get("sources")
    if isinstance(source_urls, (list, tuple)):
        target_sources = updated.get("sources")
        target_sources = list(target_sources) if isinstance(target_sources, list) else []
        for url in source_urls:
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                if url not in target_sources:
                    target_sources.append(url)
        if target_sources:
            updated["sources"] = target_sources

    labels = [label for label in _LABEL_ORDER if label in changed]
    return updated, labels
