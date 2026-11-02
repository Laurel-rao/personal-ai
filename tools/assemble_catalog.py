#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并 movies_raw.json + 子代理检索结果 → 生成 ~/Movies/番号目录.md 及重命名计划 CSV"""
import json, os, glob, re, csv

BASE = '/Users/raojiajun/mypro/backend/personal-ai/tools'
rows = json.load(open(f'{BASE}/movies_raw.json', encoding='utf-8'))

BRANDS_CACHE = ['SSIS','SNIS','SSNI','IPX','IPZZ','IPZ','MIDA','MIDV','MIAE','MIAA','MIMK','MIRD',
          'MNGS','MADV','MEYD','NAAC','OAE','OFJE','PPX','PRED','ROYD','SNOS','SONE','SQTE',
          'SSPD','START','URKN','WAAA','ABW','ADN','AQSH','ATID','CAWD','CAWB','DASS','IDBD',
          'JUL','MDBK','SDAB','SDDE','SDMUA','TDMN','VEC','RKI','FSDSS','FSD','CJOD']
KNOWN = ['桥本有菜','橋本ありな','松本いちか','永瀬ゆい','相澤南','相沢みなみ','相泽南',
         '山岸逢花','枫カレン','楓カレン','枫可','松井一香','希島あいり','白城リサ','桃乃木かな',
         '桃乃木香奈','明里つむぎ','明里つむき','桜空もも','早美れむ','阿部乃みく','跡美しゅり',
         '有栖るる','川口桜','森日向子','新ありな','有坂深雪','山手梨愛','未歩なな','坂道みる',
         '初川みなみ','あまつか亜夢','Amatsuka','深田えいみ','伊藤舞雪','小宵こなん','希咲那奈',
         '里仲ゆい','武藤あやか','あまつか','Karen Kaede','Minami Hatsukawa','Miru Sakamichi','Eimii Fukada']

# --- 读取子代理检索结果（JSONL：每行 {"code":..., "actress_cn":..., "tag":..., "note":...}）---
GENERIC_TAGS = {'单体美少女','企划单体','单体剧情','单体作品','写真影像','素人自拍','多人共演','未核实到具体剧情','待补充',''}
def _tag_priority(t):
    return 0 if t in GENERIC_TAGS else 1

res = {}
for f in sorted(glob.glob(f'{BASE}/research_*.jsonl')):
    for line in open(f, encoding='utf-8'):
        line = line.strip()
        if not line: continue
        try:
            o = json.loads(line)
            code = o.get('code', '').upper()
            prev = res.get(code)
            if prev is None or _tag_priority(o.get('tag', '')) >= _tag_priority(prev.get('tag', '')):
                res[code] = o
        except Exception:
            pass

def _recompute_sub(r):
    n = r['name']
    return bool(re.search(r'(?:[0-9]C(?![0-9A-Za-z]))|(?:-C(?![A-Za-z]))|中文字幕|字幕|\(中字\)|中字', n))

def actress(r):
    a = r.get('actress_hint') or ''
    if not a:
        a = ' / '.join(dict.fromkeys(k for k in KNOWN if k in r['path']))
    if a: return a
    o = res.get(r['code'])
    if o:
        cn, jp = o.get('actress_cn'), o.get('actress_jp')
        if cn and jp and cn != jp: return f'{cn}/{jp}'
        return cn or jp or ''
    return ''

def _title_part(r):
    """从文件名剥离水印/番号/女优/日期后取标题文本"""
    n = r['name']
    n = re.sub(r'^[A-Za-z0-9_.\-]+\.(?:com|net|me|xyz|life|info)@', '', n)
    n = re.sub(r'\.[A-Za-z0-9]+$', '', n)
    n = re.sub(r'(?<![A-Za-z])(FC2PPV?|' + '|'.join(sorted(BRANDS_CACHE, key=len, reverse=True)) + r')[-_ ]?\d{2,8}[A-Za-z]?(?!\d)', '', n, flags=re.I)
    n = re.sub(r'\[[^\]]*\]|\([^)]*\)|（[^）]*）', '', n)
    n = re.sub(r'\d{4}[-.]\d{1,2}[-.]\d{1,2}', '', n)
    n = re.sub(r'\d{1,2}月\d{1,2}日|[0-9]{6,}', '', n)
    for k in KNOWN:
        n = n.replace(k, '')
    n = n.replace('\u3099', '').replace('\u309a', '')
    return re.sub(r'[\s\-_@#·…°\'"、。，:：;；!！?？]+', '', n)

def tag(r):
    o = res.get(r['code']) if r['code'] else None
    if o and o.get('tag'): return o['tag'][:12]
    t = _title_part(r)
    if len(t) >= 6: return t[:10]
    return '待补充'

# --- 垃圾/杂项判定 ---
JUNK_NO_CODE = re.compile(r'(SnapVid|SaveTwitter|直播|遊戲|游戏大全|最新情報|社 區)', re.I)
def is_empty(r): return r['size'] < 1024  # 0字节/几乎空
def is_junk(r):
    if is_empty(r): return True
    if not r['code'] and JUNK_NO_CODE.search(r['name']): return True
    return False

# 特殊覆盖：文件名无番号但已反查确认
OVERRIDES = {
    '今からこの一家全員': 'REAL-759',
    '就活の履歴書': 'DASD-819',
}
for r in rows:
    if not r['code']:
        for k, v in OVERRIDES.items():
            if k in r['name']:
                r['code'] = v
                break

# 每个番号的文件列表（合并）
from collections import defaultdict
by_code = defaultdict(list)
for r in rows:
    if r['code']: by_code[r['code']].append(r)

# --- 生成 Markdown ---
lines = ['# 番号目录', '', f'生成时间: {__import__("datetime").datetime.now():%Y-%m-%d %H:%M}', '',
         '格式: 番号-主演-标签-C （C=中文字幕；UNC=无码/流出）', '']
lines.append('| 番号 | 主演 | 10字标签 | C | 大小 | 文件数 | 备注 |')
lines.append('|---|---|---|---|---|---|---|')
multi = 0
for code in sorted(by_code):
    files = by_code[code]
    r0 = files[0]
    a = actress(r0) or '待查'
    t = tag(r0)
    c = '√' if any(_recompute_sub(f) for f in files) else ''
    unc = any(f['unc'] for f in files)
    total = sum(f['size'] for f in files) / 1073741824
    note = []
    if len(files) > 1: note.append(f'{len(files)}个文件'); multi += 1
    if unc: note.append('无码/流出')
    if any(is_empty(f) for f in files): note.append('含空文件')
    lines.append(f'| {code} | {a} | {t} | {c} | {total:.1f}G | {len(files)} | {"; ".join(note) or ""} |')

# 杂项
junk = [r for r in rows if not r['code']]
lines += ['', '## 无番号杂项', '', '| 文件 | 大小 | 判定 |', '|---|---|---|']
for r in junk:
    verdict = '垃圾/广告' if is_junk(r) else '内容（需补番号）'
    lines.append(f'| {r["name"]} | {r["size"]/1048576:.1f}MB | {verdict} |')

os.makedirs('/Users/raojiajun/Movies', exist_ok=True)
with open('/Users/raojiajun/Movies/番号目录.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

# --- 重命名计划 CSV ---
with open('/Users/raojiajun/Movies/重命名计划.csv', 'w', encoding='utf-8', newline='') as f:
    w = csv.writer(f)
    w.writerow(['旧路径', '新文件名（番号-主演-标签-C）', '类型'])
    for r in rows:
        if not r['code'] or is_junk(r): continue
        a = (actress(r) or '待查').split('/')[0]
        t = tag(r)
        ext = os.path.splitext(r['name'])[1]
        newname = f"{r['code']}-{a}-{t}{'-UNC' if r['unc'] else ''}{'-C' if _recompute_sub(r) else ''}{ext}"
        w.writerow([r['path'], newname, '视频'])

print('目录: ~/Movies/番号目录.md')
print('改名计划: ~/Movies/重命名计划.csv')
print(f'番号 {len(by_code)} 个 | 多文件 {multi} 组 | 杂项 {len(junk)} | 检索命中 {sum(1 for v in res.values() if v)}')
