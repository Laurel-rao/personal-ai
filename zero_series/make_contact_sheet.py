#!/usr/bin/env python3
"""Assemble the 6 generated full-body images into a 3x2 contact sheet for quick review."""
import glob
import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("PIL not available; install Pillow to build the contact sheet.", file=sys.stderr)
    sys.exit(2)

DIR = "/Users/raojiajun/mypro/media_creator/zero_series"
OUT = os.path.join(DIR, "contact_sheet.png")

files = sorted(
    glob.glob(os.path.join(DIR, "set6*.png"))
    + glob.glob(os.path.join(DIR, "set6*.webp"))
    + glob.glob(os.path.join(DIR, "set6*.jpg"))
    + glob.glob(os.path.join(DIR, "set6*.jpeg"))
)
if not files:
    print("No set6 images found yet.", file=sys.stderr)
    sys.exit(1)

labels = ["1 元气回头", "2 小恶魔", "3 傲娇嘟嘴", "4 甜妹捧脸", "5 害羞掩面", "6 比心示好"]

imgs = []
for i, fp in enumerate(files[:6]):
    im = Image.open(fp).convert("RGB")
    imgs.append((im, labels[i] if i < len(labels) else f"image {i+1}"))

# 3 columns x 2 rows contact sheet
cols, rows = 3, 2
cell_w, cell_h = 480, 720
pad, label_h = 12, 30
sheet_w = cols * cell_w + (cols + 1) * pad
sheet_h = rows * (cell_h + label_h) + (rows + 1) * pad
sheet = Image.new("RGB", (sheet_w, sheet_h), (24, 24, 28))
draw = ImageDraw.Draw(sheet)

for idx, (im, label) in enumerate(imgs):
    col, row = idx % cols, idx // cols
    x = pad + col * (cell_w + pad)
    y = pad + row * (cell_h + label_h + pad)
    thumb = im.resize((cell_w, cell_h), Image.LANCZOS)
    sheet.paste(thumb, (x, y))
    draw.text((x + 6, y + cell_h + 6), label, fill=(230, 230, 235))

sheet.save(OUT, "PNG")
print(f"contact sheet saved: {OUT}")
print("source files:", [os.path.basename(f) for f in files])
