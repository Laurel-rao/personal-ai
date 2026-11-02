#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按最终目录修正已改名文件的标签（修复批次E泛标签覆盖问题），并清理下载残留 .torrent/.js"""
import os, re, sys, glob

V = '/Users/raojiajun/Movies/Videos'
CAT = '/Users/raojiajun/Movies/番号目录.md'
apply = '--apply' in sys.argv

# 1) 从最终目录读取 code -> (actress, tag)
info = {}
for line in open(CAT, encoding='utf-8'):
    if not line.startswith('| ') or line.startswith('| 番号') or '---' in line:
        continue
    cells = [c.strip() for c in line.strip().strip('|').split('|')]
    if len(cells) < 3: continue
    code = cells[0]
    if not re.match(r'^[A-Z0-9]+(?:-\d+)?$', code): continue
    actress = re.split(r'[／/]', cells[1])[0].strip() or '待查'
    tag = cells[2]
    info[code] = (actress, tag)

VIDEO_EXT = ('.mp4', '.mkv', '.mov', '.avi', '.wmv', '.ts')
CODE_RE = re.compile(r'^((?:FC2PPV|200GANA|\d{3}GANA|[A-Z]{2,6})-\d{2,8})-')

fixed = kept = 0
for root, dirs, files in os.walk(V):
    for fn in files:
        if not fn.lower().endswith(VIDEO_EXT): continue
        m = CODE_RE.match(fn)
        if not m: continue
        code = m.group(1)
        if code == 'OFJE-620': continue  # A/B 双碟已单独命名
        if code not in info: continue
        actress, tag = info[code]
        unc = '-UNC' in fn
        sub = re.search(r'-C(?=\.)', fn) is not None
        ext = os.path.splitext(fn)[1]
        desired = f'{code}-{actress}-{tag}{"-UNC" if unc else ""}{"-C" if sub else ""}{ext}'
        if fn == desired: kept += 1; continue
        src, dst = os.path.join(root, fn), os.path.join(root, desired)
        if os.path.exists(dst):
            print(f'[冲突跳过] {fn}（目标已存在 {desired}）'); kept += 1; continue
        print(f'{"" if apply else "[dry] "}{fn}  →  {desired}')
        if apply: os.rename(src, dst)
        fixed += 1

print(f'\n标签修正 {fixed} 条, 无需改动 {kept} 条')

# 2) 清理下载残留
leftovers = []
for pat in ('*.torrent', '.magent_*.torrent', '*.js', '.*.js'):
    leftovers += glob.glob(os.path.join(V, '**', pat), recursive=True)
leftovers = [p for p in set(leftovers) if os.path.isfile(p)]
print(f'\n下载残留文件 {len(leftovers)} 个:')
for p in sorted(leftovers): print('  ', os.path.relpath(p, V))
if apply:
    for p in leftovers: os.remove(p)
    print('已删除全部残留')
else:
    print('（dry-run 未删除，加 --apply 执行）')
