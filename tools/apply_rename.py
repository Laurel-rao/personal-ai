#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 重命名计划.csv 将视频文件改为「番号-主演-标签-C.ext」格式
用法: python3 apply_rename.py [--dry-run]
默认 dry-run 只打印『旧 → 新』，加 --apply 才真正改名。"""
import csv, os, sys

CSV = '/Users/raojiajun/Movies/重命名计划.csv'
BASE = '/Users/raojiajun/Movies/Videos'
apply = '--apply' in sys.argv

rows = list(csv.DictReader(open(CSV, encoding='utf-8')))
done = skipped = 0
for row in rows:
    old = row['旧路径']
    if not os.path.isabs(old):
        old = os.path.join(BASE, old[2:] if old.startswith('./') else old)
    newname = row['新文件名（番号-主演-标签-C）']
    if not os.path.exists(old):
        print(f'[跳过] 不存在: {old}')
        skipped += 1
        continue
    oldname = os.path.basename(old)
    if oldname == newname:
        print(f'[已是标准名] {old}')
        skipped += 1
        continue
    d = os.path.dirname(old)
    new = os.path.join(d, newname)
    if os.path.exists(new):
        print(f'[冲突] 目标已存在: {new}')
        skipped += 1
        continue
    print(f'{"" if apply else "[dry-run] "}{old}  →  {newname}')
    if apply:
        os.rename(old, new)
    done += 1

print(f'\n共 {len(rows)} 条; {"已改名" if apply else "预览"} {done} 条, 跳过 {skipped} 条')
if not apply:
    print('确认无误后执行: python3 apply_rename.py --apply')
