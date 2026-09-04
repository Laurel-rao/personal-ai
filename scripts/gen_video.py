#!/usr/bin/env python3
"""SeetaCloud 图生视频（G01-图生视频-Wan2.2万相基础版）

输入：一张起点图（本地PNG）+ 动作提示词
输出：一段视频 mp4

用法:
  python3 gen_video.py --image a.png --text "动作描述" --out b.mp4 \
      --seed 147581827454151 --seconds 5 --workers 4
"""
import argparse, base64, json, os, sys, time, mimetypes
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://uu288331-7871a176d4c0.bjb2.seetacloud.com:8443"
WORKFLOW_ID = "G01-图生视频-Wan2.2万相基础版"

def _b64data(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()

def gen_video(image_path, text, out_path, seed=147581827454151, seconds=5):
    import requests
    payload = {
        "workflow_id": WORKFLOW_ID,
        "input_values": {
            "119:text": text,
            "142:seed": seed,
            "144:value": 1024,
            "145:image": _b64data(image_path),
            "153:Number": str(seconds),
        },
    }
    r = requests.post(f"{BASE}/api/workflow/generate", json=payload, timeout=180)
    r.raise_for_status()
    d = r.json()
    if not d.get("success"):
        raise RuntimeError(d)
    pid = d["prompt_id"]
    print(f"[submit] {os.path.basename(image_path)} -> {pid}", flush=True)

    # 轮询
    t0 = time.time()
    timeout = 900  # 视频较慢，给足 15 分钟
    while time.time() - t0 < timeout:
        dr = requests.get(f"{BASE}/api/workflow/result",
                          params={"prompt_id": pid}, timeout=90).json()
        if dr.get("success") and not dr.get("pending"):
            res = dr.get("results") or []
            if res:
                vurl = res[0]["url"]
                data = requests.get(BASE + vurl, timeout=180).content
                with open(out_path, "wb") as f:
                    f.write(data)
                return out_path, len(data)
            return None, 0
        time.sleep(5)
    raise TimeoutError(pid)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=147581827454151)
    ap.add_argument("--seconds", type=int, default=5)
    args = ap.parse_args()
    out, size = gen_video(args.image, args.text, args.out,
                          seed=args.seed, seconds=args.seconds)
    if out:
        print(f"[done] {args.out} ({size//1024}KB)")
    else:
        print("[warn] 无结果")

if __name__ == "__main__":
    main()
