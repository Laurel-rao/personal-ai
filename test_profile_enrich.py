"""Run with: .venv/bin/python test_profile_enrich.py

Offline checks for profile_enrich parsing / enrich priority / merge rules.
All HTML is embedded; fetch_html is monkeypatched, so no network is used.
"""
import copy

import profile_enrich as pe

THEIDOLBASE_HTML = """
<!doctype html><html><body>
<div class="info-title">人物信息</div>
<div class="info-list">
  <div class="info-item">
    <span class="info-label">出生日期</span>
    <span class="info-value">1998年<a href="/birthday/08-12">8月12日</a></span>
  </div>
  <div class="info-item">
    <span class="info-label">身高</span><span class="info-value">160cm</span>
  </div>
  <div class="info-item">
    <span class="info-label">三围</span><span class="info-value">B82-W55-H82</span>
  </div>
  <div class="info-item">
    <span class="info-label">中文名</span><span class="info-value">早美玲梦</span>
  </div>
  <div class="info-item">
    <span class="info-label">血型</span><span class="info-value">O型</span>
  </div>
</div>
</body></html>
"""

THEIDOLBASE_NO_YEAR_HTML = """
<div class="info-item">
  <span class="info-label">出生日期</span><span class="info-value">8月12日</span>
</div>
<div class="info-item">
  <span class="info-label">身高</span><span class="info-value">162厘米</span>
</div>
"""

ACTORBASE_HTML = """
<!doctype html><html><body>
<aside class="sidebar">
  <div class="meta">
    <div class="meta-item"><div class="meta-label">生日</div>
      <div class="meta-value">1997-04-05(29岁)</div></div>
    <div class="meta-item"><div class="meta-label">身高</div>
      <div class="meta-value">158cm</div></div>
    <div class="meta-item"><div class="meta-label">三围</div>
      <div class="meta-value">B85 - W56 - H86</div></div>
    <div class="meta-item"><div class="meta-label">事务所</div>
      <div class="meta-value">示例事务所</div></div>
    <div class="meta-item"><div class="meta-label">出道时间</div>
      <div class="meta-value">2018年 -</div></div>
    <div class="meta-item"><div class="meta-label">中文名</div>
      <div class="meta-value">示例中文名</div></div>
    <div class="meta-item"><div class="meta-label">血型</div>
      <div class="meta-value">A</div></div>
    <div class="meta-item social-links">
      <a href="https://x.com/example_idol/status/123456">X</a>
      <a href="https://instagram.com/example.idol/">IG</a>
    </div>
  </div>
</aside>
</body></html>
"""

JAVDATABASE_HTML = """
<!doctype html><html><body>
<ul class="idol-meta">
  <li><b>DOB:</b> 1998-07-25</li>
  <li><b>Debut:</b> 2021-08-24</li>
  <li><b>Measurements:</b> 88-58-90</li>
  <li><b>Height:</b> 166 cm</li>
  <li><b>Agency:</b> 示例经纪</li>
</ul>
</body></html>
"""

# 真实页脚：站点自己的 x 账号只出现在 JSON-LD Organization.sameAs / footer。
ACTORBASE_FOOTER_SOCIAL_HTML = """
<!doctype html><html><body>
<aside class="sidebar">
  <div class="meta">
    <div class="meta-item"><div class="meta-label">生日</div>
      <div class="meta-value">1999-02-03</div></div>
    <div class="meta-item"><div class="meta-label">身高</div>
      <div class="meta-value">157cm</div></div>
  </div>
</aside>
<footer class="site-footer">
  <a href="https://x.com/wwwtheactorbasecom">TheActorBase</a>
  <a href="https://instagram.com/theactorbase">IG</a>
</footer>
<script type="application/ld+json">
{"@type": "Organization", "sameAs": ["https://x.com/wwwtheactorbasecom"]}
</script>
</body></html>
"""

# 即使站点账号出现在人物侧栏，也不能当成女优社媒。
ACTORBASE_SITEHANDLE_SOCIAL_HTML = """
<aside class="sidebar">
  <div class="meta">
    <div class="meta-item"><div class="meta-label">生日</div>
      <div class="meta-value">1999-02-03</div></div>
    <div class="meta-item social-links">
      <a href="https://x.com/wwwtheactorbasecom">X</a>
      <a href="https://instagram.com/javdatabase">IG</a>
    </div>
  </div>
</aside>
"""

ENRICH_IDOL_HTML = """
<div class="info-item"><span class="info-label">出生日期</span>
  <span class="info-value">1998年8月12日</span></div>
<div class="info-item"><span class="info-label">身高</span>
  <span class="info-value">160cm</span></div>
<div class="info-item"><span class="info-label">中文名</span>
  <span class="info-value">早美玲梦</span></div>
<div class="info-item"><span class="info-label">血型</span>
  <span class="info-value">O型</span></div>
"""

ENRICH_ACTOR_HTML = """
<aside class="sidebar"><div class="meta">
  <div class="meta-item"><div class="meta-label">生日</div>
    <div class="meta-value">1990-01-01</div></div>
  <div class="meta-item"><div class="meta-label">身高</div>
    <div class="meta-value">158cm</div></div>
  <div class="meta-item"><div class="meta-label">三围</div>
    <div class="meta-value">B85 - W56 - H86</div></div>
  <div class="meta-item"><div class="meta-label">事务所</div>
    <div class="meta-value">Actor Agency</div></div>
  <div class="meta-item"><div class="meta-label">出道时间</div>
    <div class="meta-value">2018年</div></div>
  <div class="meta-item social-links">
    <a href="https://x.com/actor_idol/status/999">X</a>
    <a href="https://instagram.com/actor.idol/">IG</a>
  </div>
</div></aside>
"""

ENRICH_JAV_HTML = """
<li><b>DOB:</b> 1980-02-02</li>
<li><b>Height:</b> 170 cm</li>
<li><b>Measurements:</b> 90-60-90</li>
<li><b>Agency:</b> JAV Agency</li>
<li><b>Debut:</b> 2019-05-05</li>
"""


def test_parse_theidolbase():
    data = pe.parse_theidolbase(THEIDOLBASE_HTML)
    assert data["birthday"] == "1998-08-12", data
    assert data["height"] == "160", data
    assert data["measurements"] == "B82-W55-H82", data
    assert data["chinese_name"] == "早美玲梦", data
    assert data["blood_type"] == "O", data

    partial = pe.parse_theidolbase(THEIDOLBASE_NO_YEAR_HTML)
    assert partial["birthday"] == "08-12", partial
    assert partial["height"] == "162", partial

    assert pe.parse_theidolbase("") == {}
    assert pe.parse_theidolbase("<html><body>没有资料</body></html>") == {}


def test_parse_actorbase():
    data = pe.parse_actorbase(ACTORBASE_HTML)
    assert data["birthday"] == "1997-04-05", data
    assert data["height"] == "158", data
    assert data["measurements"] == "B85-W56-H86", data
    assert data["agency"] == "示例事务所", data
    assert data["debut"] == "2018", data
    assert data["chinese_name"] == "示例中文名", data
    assert data["blood_type"] == "A", data
    assert data["social"]["x"] == "https://x.com/example_idol", data
    assert data["social"]["instagram"] == "https://instagram.com/example.idol", data

    assert pe.parse_actorbase("<html><body><p>Hello</p></body></html>") == {}
    assert pe.parse_actorbase("") == {}


def test_parse_javdatabase():
    data = pe.parse_javdatabase(JAVDATABASE_HTML)
    assert data["birthday"] == "1998-07-25", data
    assert data["height"] == "166", data
    assert data["measurements"] == "B88-W58-H90", data
    assert data["agency"] == "示例经纪", data
    assert data["debut"] == "2021", data

    assert pe.parse_javdatabase("<html><body>unknown layout</body></html>") == {}
    assert pe.parse_javdatabase("") == {}


def test_site_social_is_ignored():
    # 页脚 / JSON-LD 里的站点账号不得算作女优社媒
    footer = pe.parse_actorbase(ACTORBASE_FOOTER_SOCIAL_HTML)
    assert "social" not in footer, footer
    assert footer["birthday"] == "1999-02-03" and footer["height"] == "157", footer

    # 即使出现在人物侧栏，站点名 handle 也要被过滤
    sidebar = pe.parse_actorbase(ACTORBASE_SITEHANDLE_SOCIAL_HTML)
    assert "social" not in sidebar, sidebar

    # JSON-LD / script 里的社媒一律不算（哪怕 handle 看起来像真人）
    script_only = ('<html><body><script type="application/ld+json">'
                   '{"sameAs": ["https://x.com/real_actress"]}'
                   '</script></body></html>')
    assert "social" not in pe.parse_actorbase(script_only), script_only

    # enrich 端到端：Hayami Remu 真实页只有页脚站号，social 必须为空
    pages = {
        "https://www.theactorbase.com/people/hayami-remu": ACTORBASE_FOOTER_SOCIAL_HTML,
    }
    original = pe.fetch_html
    pe.fetch_html = lambda url, proxy=None: pages.get(url, "")
    try:
        result = pe.enrich("Hayami Remu")
    finally:
        pe.fetch_html = original
    assert result["social"] == {}, result
    assert "https://www.theactorbase.com/people/hayami-remu" in result["sources"], result

    # 被污染的数据也不能经 merge_profile 写进档案
    merged, labels = pe.merge_profile({}, {"social": {
        "x": "https://x.com/wwwtheactorbasecom",
        "instagram": "https://instagram.com/theidolbase",
    }})
    assert merged == {} and labels == [], (merged, labels)


def test_enrich_priority():
    pages = {
        "https://www.theidolbase.com/actress/akari-tsumugi": ENRICH_IDOL_HTML,
        # theidolbase 倒序 stub 也在，但正序命中后不应再请求
        "https://www.theidolbase.com/actress/tsumugi-akari": ENRICH_IDOL_HTML,
        # actorbase 正序空页，倒序才命中（验证 slug 回退）
        "https://www.theactorbase.com/people/akari-tsumugi": "",
        "https://www.theactorbase.com/people/tsumugi-akari": ENRICH_ACTOR_HTML,
        "https://www.javdatabase.com/idols/akari-tsumugi": "",
        "https://www.javdatabase.com/idols/tsumugi-akari": ENRICH_JAV_HTML,
    }
    calls = []
    original = pe.fetch_html

    def fake_fetch(url, proxy=None):
        calls.append(url)
        return pages.get(url, "")

    pe.fetch_html = fake_fetch
    try:
        result = pe.enrich("Akari Tsumugi", "明里つむぎ", "明里䌷")
    finally:
        pe.fetch_html = original

    # theidolbase 优先，actorbase/javdatabase 只补空
    assert result["birthday"] == "1998-08-12", result
    assert result["height"] == "160", result
    assert result["measurements"] == "B85-W56-H86", result
    assert result["agency"] == "Actor Agency", result
    assert result["debut"] == "2018", result
    assert result["chinese_name"] == "早美玲梦", result
    assert result["blood_type"] == "O", result
    assert result["social"] == {
        "x": "https://x.com/actor_idol",
        "instagram": "https://instagram.com/actor.idol",
    }, result
    assert result["sources"] == [
        "https://www.theidolbase.com/actress/akari-tsumugi",
        "https://www.theactorbase.com/people/tsumugi-akari",
        "https://www.javdatabase.com/idols/tsumugi-akari",
    ], result
    assert "https://www.theidolbase.com/actress/tsumugi-akari" not in calls, calls
    assert calls[0].startswith("https://www.theidolbase.com/"), calls
    assert calls[1].startswith("https://www.theactorbase.com/"), calls

    # 没有罗马字名时不发任何请求
    calls.clear()
    pe.fetch_html = fake_fetch
    try:
        empty = pe.enrich("")
    finally:
        pe.fetch_html = original
    assert calls == [], calls
    assert empty == {
        "birthday": "", "height": "", "measurements": "", "agency": "",
        "debut": "", "social": {}, "chinese_name": "", "blood_type": "",
        "sources": [],
    }, empty

    # 三个源都失败时仍是完整空结构
    pe.fetch_html = lambda url, proxy=None: ""
    try:
        failed = pe.enrich("Nobody Here")
    finally:
        pe.fetch_html = original
    assert failed["sources"] == [] and failed["social"] == {}, failed


def _enrich_data():
    return {
        "birthday": "1998年8月12日",
        "height": "160cm",
        "measurements": "B:82 / W:55 / H:82",
        "agency": "示例事务所",
        "debut": "2018年",
        "social": {"x": "https://x.com/new", "instagram": "https://instagram.com/new"},
        "chinese_name": "早美玲梦",
        "blood_type": "O型",
        "sources": ["https://www.theidolbase.com/actress/akari-tsumugi"],
    }


def test_merge_profile_fill_only():
    profile = {"displayName": "测试", "sources": ["https://old.example"]}
    data = _enrich_data()
    original = copy.deepcopy(profile)

    updated, labels = pe.merge_profile(profile, data)
    assert profile == original, "merge_profile 不应修改入参"
    assert updated["height"] == "160", updated
    assert updated["measurements"] == "B82-W55-H82", updated
    assert updated["birthday"] == "1998-08-12", updated
    assert updated["agency"] == "示例事务所", updated
    assert updated["debutYear"] == "2018", updated
    assert updated["chineseName"] == "早美玲梦", updated
    assert updated["bloodType"] == "O", updated
    assert updated["social"] == {
        "x": "https://x.com/new", "instagram": "https://instagram.com/new"}, updated
    assert updated["sources"] == [
        "https://old.example", "https://www.theidolbase.com/actress/akari-tsumugi"], updated
    assert labels == ["身高", "三围", "生日", "事务所", "出道", "社媒", "中文名", "血型"], labels

    # 已有值在 force=False 时不动；social 只补缺失的 instagram
    existing = {
        "height": "165",
        "birthday": "2000-01-02",
        "agency": "旧事务所",
        "debutYear": "2010",
        "measurements": "B82(B)-W55-H82",
        "chineseName": "旧名",
        "bloodType": "A",
        "social": {"x": "https://x.com/old"},
        "sources": [],
    }
    before = copy.deepcopy(existing)
    updated, labels = pe.merge_profile(existing, data, force=False)
    assert existing == before, "merge_profile 不应修改入参"
    assert labels == ["社媒"], labels
    assert updated["height"] == "165" and updated["birthday"] == "2000-01-02", updated
    assert updated["agency"] == "旧事务所" and updated["debutYear"] == "2010", updated
    assert updated["chineseName"] == "旧名" and updated["bloodType"] == "A", updated
    assert updated["measurements"] == "B82(B)-W55-H82", updated
    assert updated["social"] == {
        "x": "https://x.com/old", "instagram": "https://instagram.com/new"}, updated


def test_merge_profile_force_and_measurements():
    existing = {
        "height": "165",
        "birthday": "2000-01-02",
        "agency": "旧事务所",
        "debutYear": "2010",
        "measurements": "B82(B)-W55-H82",
        "chineseName": "旧名",
        "bloodType": "A",
        "social": {"x": "https://x.com/old"},
    }
    updated, labels = pe.merge_profile(existing, _enrich_data(), force=True)
    assert updated["height"] == "160", updated
    assert updated["birthday"] == "1998-08-12", updated
    assert updated["agency"] == "示例事务所", updated
    assert updated["debutYear"] == "2018", updated
    assert updated["chineseName"] == "早美玲梦", updated
    assert updated["bloodType"] == "O", updated
    # force 也不能把带罩杯的详细三围降级
    assert updated["measurements"] == "B82(B)-W55-H82", updated
    # social 从不覆盖已有
    assert updated["social"]["x"] == "https://x.com/old", updated
    assert labels == ["身高", "生日", "事务所", "出道", "社媒", "中文名", "血型"], labels

    # 原三围为空时正常补；force 时更详细的来源可以升级
    plain = {"measurements": "B82-W55-H82"}
    filled, labels = pe.merge_profile({}, _enrich_data())
    assert filled["measurements"] == "B82-W55-H82", filled
    upgraded, labels = pe.merge_profile(
        plain, {"measurements": "B82(B)-W55-H82"}, force=True)
    assert upgraded["measurements"] == "B82(B)-W55-H82", upgraded
    assert labels == ["三围"], labels
    unchanged, labels = pe.merge_profile(
        plain, {"measurements": "B82(B)-W55-H82"}, force=False)
    assert unchanged["measurements"] == "B82-W55-H82" and labels == [], unchanged

    # 空数据、无效数据都是无操作
    noop, labels = pe.merge_profile({"height": "160"}, {})
    assert noop == {"height": "160"} and labels == [], noop
    noop, labels = pe.merge_profile({}, {"height": "abc", "birthday": "2020-13-40"})
    assert noop == {} and labels == [], noop

    # 只有月日的生日也能落库
    month_day, labels = pe.merge_profile({}, {"birthday": "08-12"})
    assert month_day["birthday"] == "08-12" and labels == ["生日"], month_day

    # sources 去重，且不产生标签
    deduped, labels = pe.merge_profile(
        {"sources": ["https://a"]}, {"sources": ["https://a", "https://b"]})
    assert deduped["sources"] == ["https://a", "https://b"], deduped
    assert labels == [], labels


def main():
    test_parse_theidolbase()
    test_parse_actorbase()
    test_parse_javdatabase()
    test_site_social_is_ignored()
    test_enrich_priority()
    test_merge_profile_fill_only()
    test_merge_profile_force_and_measurements()
    print("profile_enrich: all tests passed")


if __name__ == "__main__":
    main()
