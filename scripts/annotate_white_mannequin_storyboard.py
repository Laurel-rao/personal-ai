#!/usr/bin/env python3
"""Create a Chinese annotated delivery sheet from the six-panel storyboard."""

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont


FONT_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size=size)


def draw_arrow(draw: ImageDraw.ImageDraw, start, end, color, width=8):
    draw.line([start, end], fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    direction = 1 if x2 >= x1 else -1
    draw.polygon(
        [
            (x2, y2),
            (x2 - direction * 20, y2 - 13),
            (x2 - direction * 20, y2 + 13),
        ],
        fill=color,
    )


def label(draw, xy, text, fill, text_fill=(255, 255, 255)):
    x, y = xy
    box = draw.rounded_rectangle(
        [x, y, x + draw.textlength(text, font=font(21)) + 22, y + 34],
        radius=5,
        fill=fill,
    )
    draw.text((x + 11, y + 4), text, font=font(21), fill=text_fill)
    return box


def annotate_panel(panel: Image.Image, index: int) -> Image.Image:
    panel = panel.copy()
    draw = ImageDraw.Draw(panel, "RGBA")
    red = (193, 73, 62, 255)
    gold = (221, 159, 56, 255)
    blue = (56, 132, 190, 255)

    label(draw, (18, 16), f"{index:02d}", (25, 28, 31, 220))

    if index == 1:
        draw_arrow(draw, (50, 110), (225, 110), red)
        label(draw, (52, 122), "步兵列", red)
        draw_arrow(draw, (468, 180), (350, 180), gold)
        label(draw, (350, 192), "王车", gold, (35, 29, 20))
    elif index == 2:
        draw_arrow(draw, (468, 118), (330, 118), gold)
        label(draw, (334, 130), "王车对向驶近", gold, (35, 29, 20))
        label(draw, (25, 420), "男主前景", red)
    elif index == 3:
        draw_arrow(draw, (210, 230), (345, 230), blue, 6)
        draw_arrow(draw, (345, 248), (210, 248), blue, 6)
        label(draw, (214, 260), "侧窗对视轴线", blue)
    elif index == 4:
        draw_arrow(draw, (270, 300), (455, 300), gold)
        label(draw, (300, 312), "王车远离", gold, (35, 29, 20))
        label(draw, (22, 420), "男主留在原地", red)
    elif index == 5:
        draw.ellipse([415, 285, 560, 430], outline=blue, width=7)
        label(draw, (322, 235), "未露脸者拍右肩", blue)
    elif index == 6:
        draw.line([(260, 35), (260, 475)], fill=(255, 255, 255, 230), width=8)
        label(draw, (176, 18), "约0.2秒闪白", blue)
        label(draw, (35, 430), "战国", red)
        label(draw, (405, 430), "盛唐", gold, (35, 29, 20))

    return panel


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: annotate_white_mannequin_storyboard.py INPUT OUTPUT")

    source_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    source = Image.open(source_path).convert("RGB")
    if source.size != (1536, 1024):
        raise ValueError(f"expected 1536x1024 source, got {source.size}")

    width = 1800
    margin = 34
    gap = 18
    panel_size = 565
    caption_height = 142
    header_height = 148
    row_gap = 24
    height = header_height + 2 * (panel_size + caption_height) + row_gap + margin
    canvas = Image.new("RGB", (width, height), (18, 20, 22))
    draw = ImageDraw.Draw(canvas)

    draw.text((margin, 24), "战国 · 暮色初遇｜白模分镜故事板", font=font(48), fill=(245, 241, 231))
    draw.text(
        (margin, 88),
        "人物统一为无五官哑光白模：本阶段只验收剧情、站位、运动方向、动作和服装轮廓；后续再单独绑定人脸参考。",
        font=font(25),
        fill=(188, 193, 198),
    )

    captions = [
        ("0–5秒｜建立场景 / 男主入场", "位置：男主近景右；步兵列中后景；王车远处右侧", "场景：战国官道、夯土墙、干涸田野、暮色尘光"),
        ("0–5秒｜对向交错关系", "位置：男主左前景；王车与双马右中景", "方向：步兵左→右；王车右→左，不减速、不避让"),
        ("5–8秒｜侧窗掀帘 / 二人对视", "位置：男主车外左侧；女主仅在王车侧窗内", "镜头：车外中景慢推；保持隔窗对视，不离车、不驾车"),
        ("8–12秒｜相遇后自然远离", "位置：男主左前景停留；王车向远处离开", "剧情：男主不追车、不放矛，只目送并消化情绪"),
        ("12–14秒｜号角归队 / 拍肩触发", "位置：男主居中；右侧仅伸入半截皮甲袖口与手", "动作：拍男主右肩；拍肩者不露脸；男主回头"),
        ("14秒｜同机位跨世闪白", "位置：男主保持同一回头姿势和同一景别", "转场：战国暮色闪白约0.2秒 → 盛唐长安灯火"),
    ]

    for index in range(6):
        src_x = (index % 3) * 512
        src_y = (index // 3) * 512
        panel = source.crop((src_x + 3, src_y + 3, src_x + 509, src_y + 509))
        panel = panel.resize((panel_size, panel_size), Image.Resampling.LANCZOS)
        panel = annotate_panel(panel, index + 1)

        col = index % 3
        row = index // 3
        x = margin + col * (panel_size + gap)
        y = header_height + row * (panel_size + caption_height + row_gap)
        canvas.paste(panel, (x, y))

        draw.rectangle(
            [x, y + panel_size, x + panel_size, y + panel_size + caption_height],
            fill=(29, 32, 35),
        )
        title, position, scene = captions[index]
        draw.text((x + 17, y + panel_size + 14), title, font=font(27), fill=(247, 213, 148))
        draw.text((x + 17, y + panel_size + 55), position, font=font(21), fill=(230, 232, 233))
        draw.text((x + 17, y + panel_size + 91), scene, font=font(21), fill=(190, 196, 201))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=True)
    print(f"saved {output_path} {canvas.size[0]}x{canvas.size[1]}")


if __name__ == "__main__":
    main()
