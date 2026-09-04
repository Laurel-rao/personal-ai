#!/usr/bin/env python3
"""SeetaCloud 短剧文生图 生成脚本（第一幕·战国相遇，统一世界一致性版 + 并发）

改造点：
1) WORLD 统一背景描述块：时代/地域/材质/配色/光线/器物全部锚定同一个世界，
   叠加到每张提示词上，保证人物-场景-道具-服装取材一致。
2) 并发生成：ThreadPoolExecutor 并行提交+轮询+下载，不再是串行。

用法:
  python3 gen_scene.py --con 4          # 并发 4 张同步生成全部
  python3 gen_scene.py --one <idx>      # 单张
  python3 gen_scene.py --keys a,b,c     # 只生成指定 key
"""
import argparse, json, time, sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://uu288331-7871a176d4c0.bjb2.seetacloud.com:8443"
WORKFLOW_ID = "C16-短剧文生图专用-支持场景-角色"
OUT_DIR = os.path.realpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "婚礼穿越视频", "assets", "act1_warring-states_v2"))

# ======================= 统一世界观完整描述（一致性基石） =======================
# 这一段本质上是“同一部片子的定场辞”，逐字不差地追加到每一张图。
WORLD = (
    "【统一世界设定】战国时期（公元前5—前3世纪中原）诸侯国边城；夯土城墙、干打垒房屋、槽土集市道路；"
    "画面所及皆是同一片土地、同一种取材。"
    "时代材质：夯土、粗木、麻布、皮甲、漆木、青铜、陶器、竹编与麻绳，无任何金属铠甲/锁子甲等后世或架空制品。"
    "色彩仅限于低饱和莫兰迪色系：土褐、赭石、暗土红、深褐皮甲、青灰蓝、米白麻布，全画面无刺眼高饱和色。"
    "光线统一为入秋黄昏低斜阳光，伦勃朗式侧逆光勾勒轮廓，柔和漫射光补足面部，光影斑驳错落，长影贴地，尘埃在光柱中浮动。"
    "氛围：尘雾弥漫、粗粝真实、接地气，胶片颗粒质感，电影调色，浅景深大光圈，文艺电影构图，镜头呼吸感。"
    "严禁：现代物件、玻璃车窗、塑料、拉链、金属盔甲、奢侈品、可读文字、水印、高饱和色、夸张特效。"
)
# 简短风格尾(不重复世界观)
STYLE = "真人写实，原生态自然肌肤，人物情态生动情绪饱满，胶片颗粒，电影感，单一人物或纯环境"

# ======================= 核心人脸锚点 + 主场景，全部挂在同一世界观下 =======================
PROMPTS = [
    dict(key="01_male_lead_warrior",
         prompt=("年轻的战国步兵男主，胸口以上半身侧像。素色麻布交领右衽深衣，外罩规则编缀的深褐色皮札甲（甲片层层相叠、实用朴素、边缘磨损沾尘），"
                 "束发以粗麻带系起，无冠帽无发饰。手持一支结构写实的青铜矛（暗铜绿色、铸造感、素面）竖于肩侧。"
                 "五官端正严肃、目光平和坚毅，面颊沾薄尘。琥珀黄昏侧逆光勾勒轮廓，背景虚化为模糊的夯土墙与行军队列。"),
         seed=34341318406080),
    dict(key="02_female_lead_princess",
         prompt=("战国公主女主，端坐于漆木马车车窗内侧，半侧身胸部以上。素雅交领右衽深衣（米白/青灰低饱和，素面无绣纹、仅素色窄袖缘），"
                 "低绾发髻、只插一支素木簪，无耳饰无流苏无披散发，仪态温婉含蓄内敛。一手轻拢编织粗竹帘，帘杆为素木。"
                 "车内昏暗的素面深木纹漆壁（无金属兽面/无繁复包角饰件），黄昏暖光从窗外斜照落于她脸与袖口，"
                 "双眼隐含期待但与世隔绝不张扬，浅景深。"),
         seed=34341318406081),
    dict(key="03_market_street_wide",
         prompt=("战国边城集市大远景，24mm深焦。夯土城墙与干打垒店铺分列，布棚幕布、陶罐、竹编篮、麻绳货架、槽土路面扬尘。"
                 "远处有持矛守兵与几匹驮马，行人自然退让，两股人流在路中交错相向。无人脸特写，纯环境。"
                 "入秋黄昏低斜光，长影，尘雾弥漫，统一低饱和土褐赭石配色。"),
         seed=34341318406082),
    dict(key="04_market_street_mid",
         prompt=("战国边城集市中景纵深，35mm。两侧夯土商铺与布棚，陶罐竹篮麻绳布匹货架堆叠近景，中景为行人摊贩，"
                 "背景为夯土墙与远处门楼，三层层次清晰。路面槽土扬尘，商贩与行人自然走动，无人脸特写，纯环境。"
                 "入秋黄昏低斜光，低饱和土褐赭石配色，尘雾浮动。"),
         seed=34341318406083),
    dict(key="05_carriage_interior",
         prompt=("战国漆木马车内部空镜。素面漆木车壁（深褐红/黑，无繁复纹样），侧窗窗框粗木，编织粗竹帘半卷，"
                 "黄昏暖光穿透竹帘在暗室内投下斑驳格影。车内无人物，安静怀旧，浅景深大光圈。"
                 "同一年代取材：木质、竹编、漆木，无金属包角、无后世车舆结构。"),
         seed=34341318406084),
    dict(key="06_infantry_low_angle",
         prompt=("战国步兵行军低机位纵深。近景为沙土路面与裹腿麻布、皮靴、皮甲胫具，中景为青铜矛杆与旌旗，"
                 "背景为夯土城墙屋脊，尘土层层叠起。一排步兵由右向左行进，踏地重压节奏感。"
                 "无清晰人脸，琥珀黄昏逆光，低饱和土褐配色，移动与纵深强烈。"),
         seed=34341318406085),
    # —— 第三批：关键资产特写（统一世界观/取材）——
    dict(key="07_chariot_full",
         prompt=("战国漆木马车整车侧面特写。素面漆木车厢（深褐红/黑），粗木轮辋带辐条、木轴，双马牵引，粗麻皮缰，"
                 "车厢前部设粗木板轼，顶棚为素麻/竹编。质朴实用，无金属兽面、无繁复纹样、无金石包角。"
                 "槽土路面扬尘，白天偏黄昏光，低饱和土褐配色，纯资产图无人。"),
         seed=34341318406086),
    dict(key="08_bamboo_blind_closeup",
         prompt=("战国编织粗竹帘特写。粗竹条以麻绳编结的格纹帘，半卷状态透出黄昏暖光，帘隙投下斑驳格影。"
                 "竹材自然粗糙、色呈黄褐色，边缘素木帘杆。素朴无装饰，无人无脸，大光圈浅景深，纯资产特写。"
                 "统一低饱和土褐赭石配色，胶片质感。"),
         seed=34341318406087),
    dict(key="09_bronze_spear",
         prompt=("战国青铜矛特写。暗铜绿色青铜矛头，铸造的素面刃与銎，木杆缠粗麻绳固定，结构写实无华丽纹饰。"
                 "静置于夯土墙边木架/地面，黄昏侧逆光在矛刃上拉出暖色高光，尘雾。低饱和土褐配色，纯资产图无人。"),
         seed=34341318406088),
    # —— 第四批：修复起点图（去除 v1/v2 顽固缺陷）——
    dict(key="f04_chariot_open",
         prompt=("战国开放式双轮漆木马车侧面全图。低矮开放的乘车平台，四周无封闭车厢壁板、无高顶、无格窗，"
                 "仅有低矮漆木围栏与可掀起的素麻顶棚，粗大木辐轮、横置车轴，双马并驾以粗麻皮缰牵引。"
                 "结构明确为战国车制：衡、辕、轭粗实，车厢低矮露天。素面深褐红漆，无金属兽面、无金饰包角、无雕花。"
                 "槽土路面，黄昏侧逆光，尘土，统一低饱和土褐配色，纯资产图。"),
         seed=34341318406090),
    dict(key="f01_market_no_poles",
         prompt=("战国边城集市大远景，夯土城墙与干打垒店铺分列，布棚、陶罐、竹篮、麻绳货架、槽土路面扬尘。"
                 "远处守兵与驮马，行人自然交错相向，无人脸特写。画面内绝对没有任何直立杆状物、横担、线缆、旗杆或现代物件，"
                 "城墙上方洁净无杆件。入秋黄昏低斜光，低饱和土褐赭石，尘雾弥漫，纯环境。"),
         seed=34341318406091),
    dict(key="f05_princess_plain",
         prompt=("战国公主女主，端坐于素面漆木马车车窗内侧，半侧身胸部以上。素雅交领右衽深衣（米白/青灰，素面无绣纹），"
                 "头发全部整齐挽成低发髻、以一支素木簪固定，脑后及肩侧没有任何散落的披肩长发、不留碎发，双耳无任何耳饰。"
                 "两手轻托粗竹帘下缘（手指明确从下方托住帘沿），温婉含笑目光低垂。车内暗部深木纹漆壁，黄昏暖光从窗外斜照脸与袖口，浅景深。"),
         seed=34341318406092),
    dict(key="f02_warrior_hand",
         prompt=("年轻的战国步兵男主，半身侧像。左手在胸前清晰握住一支青铜矛杆，五指明确环握矛杆清晰可见，矛头朝上，"
                 "握矛手位于画面前景清晰对焦，不被盔甲遮挡。右侧束发，深褐色素面皮札甲内衬交领深衣，甲片规则编缀。"
                 "面容严肃坚毅，琥珀黄昏侧逆光勾勒轮廓，背景虚化为夯土墙，手部甲片与矛杆细节清晰。"),
         seed=34341318406093),
]

# ======================= 并发实现 =======================
def _submit(entry):
    import requests
    full = f"{entry['prompt']}，{WORLD}，{STYLE}".strip("，")
    payload = {
        "workflow_id": WORKFLOW_ID,
        "input_values": {
            "22:seed": entry["seed"],
            "49:text": full,
            "60:value": 1920,
            "61:value": 1024,
        },
    }
    r = requests.post(f"{BASE}/api/workflow/generate", json=payload, timeout=120)
    r.raise_for_status()
    d = r.json()
    if not d.get("success"):
        raise RuntimeError(d)
    return d["prompt_id"]

def _wait_and_download(entry, prompt_id, timeout=240, poll=3):
    import requests
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = requests.get(f"{BASE}/api/workflow/result",
                         params={"prompt_id": prompt_id}, timeout=60).json()
        if d.get("success") and not d.get("pending"):
            results = d.get("results") or []
            if results:
                img = requests.get(BASE + results[0]["url"], timeout=120).content
                out = os.path.join(OUT_DIR, f"{entry['key']}.png")
                with open(out, "wb") as f:
                    f.write(img)
                return out, len(img)
        time.sleep(poll)
    raise TimeoutError(prompt_id)

def _work(entry):
    pid = _submit(entry)
    out, size = _wait_and_download(entry, pid)
    return entry["key"], out, size

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--con", type=int, default=4, help="并发数")
    ap.add_argument("--one", type=int, default=None)
    ap.add_argument("--keys", type=str, default=None)
    ap.add_argument("--force", action="store_true", help="覆盖已存在的图")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    targets = PROMPTS
    if args.one is not None:
        targets = [PROMPTS[args.one]]
    if args.keys:
        ks = {k.strip() for k in args.keys.split(",")}
        targets = [p for p in PROMPTS if p["key"] in ks]
    # 跳过已生成的，避免重复烧额度（--force 则覆盖）
    def _exists(p):
        return os.path.exists(os.path.join(OUT_DIR, f"{p['key']}.png"))
    todo = [p for p in targets if args.force or not _exists(p)]
    skipped = len(targets) - len(todo)
    if skipped:
        print(f"[skip] {skipped} 张已存在，跳过（--force 可覆盖）")

    print(f"== 并发 {args.con} 生成 {len(todo)} 张 -> {OUT_DIR} ==")
    if not todo:
        print("无事可做。")
        return

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(args.con, len(todo))) as ex:
        futures = {ex.submit(_work, p): p["key"] for p in todo}
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                key, out, size = fut.result()
                print(f"[done] {key} -> {os.path.basename(out)} ({size//1024}KB)", flush=True)
            except Exception as e:
                print(f"[fail] {key}: {e!r}", flush=True)
    print(f"== 全部结束，耗时 {time.time()-t0:.1f}s ==")

if __name__ == "__main__":
    main()
