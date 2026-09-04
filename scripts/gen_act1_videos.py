#!/usr/bin/env python3
"""第一幕·战国相遇 —— 5s 图生视频 6 段并发驱动"""
import base64, os, sys, time, mimetypes
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://uu288331-7871a176d4c0.bjb2.seetacloud.com:8443"
WORKFLOW_ID = "G01-图生视频-Wan2.2万相基础版"
ASSETS = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "婚礼穿越视频", "assets", "act1_warring-states_v2_crop"))
OUT    = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "婚礼穿越视频", "output", "act1_warring-states_video_v2"))

# 风格统一尾（视频动作提示也锚定同一世界观）
WORLD = "战国边城，入秋黄昏低斜暖光，夯土墙面与尘土飞扬，低饱和土褐赭石色调，胶片质感，真实自然运动，运动平滑连贯无闪烁"

# 稳定与一致性负面项（追加到动作提示后，抑制帧间重组）
NEG = "背景人物不要凭空出现或消失，轮廓保持稳定不跳变，无闪烁无融解，物理连贯"

# 6 段：起点图 + 动作提示 + 输出名
CLIPS = [
    dict(key="clip01_market_establish",
         image="03_market_street_wide.png",
         text=("集市大远景空镜极缓横移：干燥尘土在黄昏光柱中缓慢浮动，远处一辆马车与几名守兵沿槽土路自左向右缓缓驶过，"
               "背景行人连贯移动，无人在画面中凭空出现或消失，城墙上方无任何现代杆件，画面安定如一幅流动画卷，镜头极慢横向推移。"),
         seed=147581827454101),
    dict(key="clip02_soldier_march",
         image="01_male_lead_warrior.png",
         text=("男主步兵身体轻微起伏地缓步行进，束发与衣摆被晚风轻轻吹动，甲片随步伐细微晃动，眼神平和注视前方，"
               "只有主体上半身的呼吸感与轻微重心变化，背景军阵与尘土保持静止，人脸与甲胄稳定不跳变。"),
         seed=147581827454102),
    dict(key="clip03_infantry_column",
         image="06_infantry_low_angle.png",
         text=("步兵阵列低机位由右向左整齐行进，脚步踏在沙土上扬起细碎尘团并向后拖尾，矛杆与旌旗随步伐轻晃，"
               "队伍自右向左连续前进，所有士兵原地不凭空出现或消失，尘土按落脚连续演化，运动平滑连贯。"),
         seed=147581827454103),
    dict(key="clip04_chariot_pass",
         image="07_chariot_full.png",
         text=("漆木马车自画面左侧向右明显驶过，连续右移约半幅画面，粗木车轮持续转动，双马稳步前行扬起尘土，"
               "车厢随路面轻微颠簸，马腿自然迈步连贯不粘连，车轮辐条连续旋转，镜头随马车右移跟拍。"),
         seed=147581827454104),
    dict(key="clip05_princess_lift_blind",
         image="02_female_lead_princess.png",
         text=("女主端坐车内，目光低垂温婉含笑，手指托住竹帘下缘并随竹帘同步向上抬起，手与竹帘保持持续接触，"
               "黄昏暖光斜照脸与袖口，微风吹动一缕发丝与衣摆，她仅有这一细致连贯的撩帘动作，手部稳定清晰无畸形。"),
         seed=147581827454105),
    dict(key="clip06_blind_closeup",
         image="08_bamboo_blind_closeup.png",
         text=("粗竹帘特写：暖阳透过编织竹帘投下斑驳格影，竹帘被风轻微晃动，帘隙光点柔和明灭，"
               "空气尘埃缓慢漂浮自然沉降，画面安静怀旧，只有竹帘与光影的轻微连续运动，浅景深。"),
         seed=147581827454106),
]

def _b64data(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()

def _gen(clip):
    import requests
    img = os.path.join(ASSETS, clip["image"])
    out = os.path.join(OUT, f"{clip['key']}.mp4")
    payload = {
        "workflow_id": WORKFLOW_ID,
        "input_values": {
            "119:text": f"{clip['text']}。{WORLD}。{NEG}",
            "142:seed": clip["seed"],
            "144:value": 1024,
            "145:image": _b64data(img),
            "153:Number": "5",
        },
    }
    r = requests.post(f"{BASE}/api/workflow/generate", json=payload, timeout=180)
    r.raise_for_status()
    d = r.json()
    if not d.get("success"):
        raise RuntimeError(d)
    pid = d["prompt_id"]
    print(f"[submit] {clip['key']} <- {clip['image']} -> {pid}", flush=True)
    t0 = time.time()
    while time.time() - t0 < 1800:
        dr = requests.get(f"{BASE}/api/workflow/result",
                          params={"prompt_id": pid}, timeout=90).json()
        if dr.get("success") and not dr.get("pending"):
            res = dr.get("results") or []
            if res:
                data = requests.get(BASE + res[0]["url"], timeout=180).content
                with open(out, "wb") as f:
                    f.write(data)
                return clip["key"], out, len(data)
            return clip["key"], None, 0
        time.sleep(5)
    raise TimeoutError(pid)

def run(con):
    os.makedirs(OUT, exist_ok=True)
    todo = [c for c in CLIPS if not os.path.exists(os.path.join(OUT, f"{c['key']}.mp4"))]
    print(f"== 并发 {con} 生成 {len(todo)} 段 -> {OUT} ==")
    if not todo:
        print("全部已存在，跳过。")
        return
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=min(con, len(todo))) as ex:
        futs = {ex.submit(_gen, c): c["key"] for c in todo}
        for fut in as_completed(futs):
            k = futs[fut]
            try:
                key, out, size = fut.result()
                print(f"[done] {key} -> {os.path.basename(out)} ({size//1024}KB)", flush=True)
            except Exception as e:
                print(f"[fail] {k}: {e!r}", flush=True)
    print(f"== 结束，耗时 {time.time()-t0:.1f}s ==")

if __name__ == "__main__":
    run(con=int(sys.argv[1]) if len(sys.argv) > 1 else 4)
