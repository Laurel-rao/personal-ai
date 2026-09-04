#!/usr/bin/env python3
"""SeetaCloud 短剧文生图 生成脚本（第一幕·战国相遇专用）

用法:
  python3 gen_scene.py            # 读取 prompts 表中全部,逐个生成并下载
  python3 gen_scene.py --one 0    # 只生成 prompts 中下标 0 的条目
"""
import argparse, json, time, sys, os, re

BASE = "https://uu288331-7871a176d4c0.bjb2.seetacloud.com:8443"
WORKFLOW_ID = "C16-短剧文生图专用-支持场景-角色"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "婚礼穿越视频", "assets", "act1_warring-states")

# ---- 统一风格基调（每个提示词都共用，保证跨镜头光影一致）----
STYLE = (
    "真人写实风格，文艺电影高级构图，镜头呼吸感，沉浸式叙事氛围感拉满；"
    "柔和漫射自然光叠加经典伦勃朗侧逆光，真实立体光影层次，光影斑驳错落，"
    "胶片颗粒质感，画面高级有故事感；景深层次自然浅景深大光圈；"
    "人物肌肤纹理真实细腻，原生真实肌肤质感，人物情态生动自然情绪饱满；"
    "零现代物件，无玻璃车窗，无文字，无水印，单一人脸无复制变形"
)

# ---- 抽帧/关键词：中文负面提示（工作流里已内建负面，这里留空即可）----
NEG = ""

# ---- 第一幕需要生成的图（按拆解清单）----
# 每项: name=文件名, prompt=核心画面内容, seed
PROMPTS = [
    dict(key="01_male_lead_warrior",
         prompt=("年轻的战国步兵男主，半侧身正面肖像，束发，深色皮札甲内衬交领深衣，甲片轻微磨损沾薄尘，"
                 "手持青铜长矛立于肩侧，面容严肃坚毅克制，目光平和深邃，琥珀色黄昏侧逆光勾勒轮廓，"
                 "浅景深虚化前景只是一抹尘土与模糊行军队列，胸口以上半身像"),
         seed=34341318406080),
    dict(key="02_female_lead_princess",
         prompt=("战国公主女主，古装仕女，端坐于漆绘马车车窗内侧，半侧身，交领深衣宫廷妆发克制发饰，"
                 "一手轻拢编织竹帘，温婉含笑目光低垂含情，黄昏暖光落在脸与袖口，车内暗部衬出被光照亮的双眼，"
                 "胸部以上中近景，浅景深"),
         seed=34341318406081),
    # —— 第二批：主场景支撑 ——
    dict(key="03_market_street_wide",
         prompt=("战国集市大道大远景，深焦，夯土墙店铺、布棚毡棚、陶罐竹篮摊贩，槽土路面扬尘，"
                 "远处置守兵与马匹，两侧人流退让留下纵深视差，两股人流交错相向，"
                 "琥珀色黄昏低角度光线拉长阴影，无人脸特写，纯环境"),
         seed=34341318406082),
    dict(key="04_market_street_mid",
         prompt=("战国集市大道中景纵深，夯土墙商铺与布棚分列两侧，陶罐竹篮布匹货架堆叠，"
                 "路面尘土，前景中景背景三层层次清晰，商贩与行人自然走动，"
                 "琥珀色黄昏暖光，35mm 焦段感，无人脸特写，纯环境"),
         seed=34341318406083),
    dict(key="05_carriage_interior",
         prompt=("战国漆绘马车内部视角，木梁漆绘内壁暗部，侧窗窗框，编织竹帘半卷透入暖光，"
                 "窗外黄昏街景虚化，光线穿过竹帘在暗室内投下斑驳格影，"
                 "安静怀旧氛围，车内空镜无人，大光圈浅景深"),
         seed=34341318406084),
    dict(key="06_infantry_low_angle",
         prompt=("战国步兵行军低机位纵深视角，脚下沙土裹腿皮靴甲胫特写，青铜矛杆旌旗屋脊尘土层层叠后景，"
                 "步兵阵列由右向左行进，踏地的重压节奏感，琥珀色黄昏逆光，"
                 "无清晰人脸，移动感与纵深感强烈"),
         seed=34341318406085),
]

def gen_one(entry):
    text = entry["prompt"]
    if STYLE and STYLE not in text:
        text = text  # 风格统一放在尾部单独拼
    full = f"{text}，{STYLE}".strip("，")
    payload = {
        "workflow_id": WORKFLOW_ID,
        "input_values": {
            "22:seed": entry["seed"],
            "49:text": full,
            "60:value": 1920,
            "61:value": 1024,
        },
    }
    print(f"[submit] {entry['key']} seed={entry['seed']}", flush=True)
    r = requests_post_generate(payload)
    return r

def requests_post_generate(payload):
    import requests
    r = requests.post(f"{BASE}/api/workflow/generate", json=payload, timeout=120)
    r.raise_for_status()
    d = r.json()
    if not d.get("success"):
        raise RuntimeError(d)
    return d["prompt_id"]

def wait_result(prompt_id, timeout=180, poll=3):
    import requests
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.get(f"{BASE}/api/workflow/result",
                         params={"prompt_id": prompt_id}, timeout=60)
        d = r.json()
        if d.get("success") and not d.get("pending"):
            return d.get("results") or []
        time.sleep(poll)
    raise TimeoutError(prompt_id)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", type=int, default=None)
    ap.add_argument("--only", type=str, default=None, help="只生成指定 key（逗号分隔）")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    targets = PROMPTS
    if args.one is not None:
        targets = [PROMPTS[args.one]]
    if args.only:
        keys = {k.strip() for k in args.only.split(",")}
        targets = [p for p in PROMPTS if p["key"] in keys]

    print(f"== 将生成 {len(targets)} 张，输出到 {OUT_DIR} ==")
    for i, entry in enumerate(targets):
        key = entry["key"]
        out = os.path.join(OUT_DIR, f"{key}.png")
        if os.path.exists(out):
            print(f"[skip] {key} 已存在")
            continue
        try:
            pid = gen_one(entry)
            print(f"[wait] {key} -> {pid}")
            results = wait_result(pid)
            if not results:
                print(f"[warn] {key} 无结果")
                continue
            img_url = BASE + results[0]["url"]
            img = requests_get(img_url)
            with open(out, "wb") as f:
                f.write(img)
            print(f"[done] {key} saved -> {out} ({len(img)//1024}KB)")
        except Exception as e:
            print(f"[fail] {key}: {e!r}")

def requests_get(url):
    import requests
    return requests.get(url, timeout=120).content

if __name__ == "__main__":
    main()
