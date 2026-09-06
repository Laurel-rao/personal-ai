#!/usr/bin/env python3
"""v5 自建记忆版：Qwen 自己总结偏好并形成持久记忆，据此流式仿写+生成。

闭环：
  1. 读 labels.json 得到每条参考的 [喜欢]/[不喜欢] 标注；
  2. 把「旧记忆 + 全部带标注原文」大上下文喂给 Qwen，让它自己总结/更新一段偏好记忆，存 qwen_preference_memory.json；
  3. 改写每条提示词时都携带这段记忆（不代写任何偏好结论）；
  4. 每改写 5 条立即提交生成（流式）。
用户持续标注 → 下次运行旧记忆被再更新，自动进化。
"""
import argparse
import contextlib
import fcntl
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError

BASE = "http://127.0.0.1:4173"
ROOT = Path("/Users/raojiajun/mypro/backend/personal-ai")
MEMORY_FILE = ROOT / "qwen_preference_memory.json"
MEMORY_LOCK_FILE = ROOT / "qwen_preference_memory.lock"
CHUNK_MAX_PROMPTS = 5
MIN_CHARS = 100
WIDTH, HEIGHT, BATCH_SIZE = 768, 1024, 1
PREF_TAG = {"like": "喜欢", "unlike": "不喜欢", "neutral": "中性", "mixed": "喜欢/不喜欢混合", "unlabeled": "未标注"}


def log(msg):
    print(msg, flush=True)


def scan_refs(before_date=None, labeled_only=False, after_time=None):
    """扫描任务 + 标注，返回 [{index, prompt, pref}]。

    before_date: 只取 created_at < before_date 的任务（初始参考集用）。
    labeled_only: 只取有 like/unlike 标注的任务（记忆任务用，会自动纳入新标注的图）。
    """
    tasks = json.loads((ROOT / "photo_lab" / "data" / "tasks.json").read_text(encoding="utf-8"))
    labels = json.loads((ROOT / "photo_lab" / "data" / "labels.json").read_text(encoding="utf-8"))
    refs = []
    index = 1
    for tid, task in tasks.items():
        if not isinstance(task, dict):
            continue
        if before_date and task.get("created_at", "") >= before_date:
            continue
        prompt = (task.get("prompt") or "").strip()
        if not prompt:
            continue
        liked = disliked = 0
        has_new_label = False
        for image in task.get("outputs", []) or []:
            filename = image.get("filename") or image.get("local_filename") or ""
            label = labels.get(f"task:{tid}:{filename}") or {}
            value = label.get("value")
            if after_time and label.get("updated_at", "") > after_time:
                has_new_label = True
            liked += value == "like"
            disliked += value == "unlike"
        if labeled_only and liked + disliked == 0:
            continue
        if after_time and not has_new_label:
            continue
        if liked > disliked:
            pref = "like"
        elif disliked > liked:
            pref = "unlike"
        elif liked + disliked > 0:
            pref = "neutral"
        else:
            pref = "unlabeled"
        refs.append({"index": index, "prompt": prompt, "pref": pref,
                     "liked": liked, "disliked": disliked,
                     "label_updated_at": max((
                         (labels.get(f"task:{tid}:{image.get('filename') or image.get('local_filename') or ''}") or {}).get("updated_at", "")
                         for image in task.get("outputs", []) or []), default="")})
        index += 1
    return refs


def load_reference():
    return scan_refs(before_date="2026-09-05")


def _memory_key(category):
    return category if category in {"sexy", "closeup"} else "sexy"


def memory_file_lock():
    """用文件锁串行化多个类别进程的记忆更新。"""
    @contextlib.contextmanager
    def locked():
        with MEMORY_LOCK_FILE.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return locked()


def load_memory(category="sexy"):
    try:
        state = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        memories = state.get("memories") or {}
        return memories.get(_memory_key(category), state.get("memory", ""))
    except (OSError, json.JSONDecodeError):
        return ""


def load_memory_state(category="sexy"):
    try:
        state = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        key = _memory_key(category)
        memories = state.get("memories") or {}
        cursors = state.get("labels_updated_at_by_category") or {}
        return memories.get(key, state.get("memory", "")), cursors.get(key, state.get("labels_updated_at", ""))
    except (OSError, json.JSONDecodeError):
        return "", ""


def save_memory(memory, labels_updated_at="", category="sexy"):
    state = {}
    try:
        state = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    memories = state.get("memories") or {}
    legacy_memory = state.get("memory", "")
    if not memories and legacy_memory:
        memories = {"sexy": legacy_memory, "closeup": legacy_memory}
    cursors = state.get("labels_updated_at_by_category") or {}
    legacy_cursor = state.get("labels_updated_at", "")
    if not cursors and legacy_cursor:
        cursors = {"sexy": legacy_cursor, "closeup": legacy_cursor}
    key = _memory_key(category)
    memories[key] = memory
    cursors[key] = labels_updated_at
    MEMORY_FILE.write_text(
        json.dumps({"memory": memories.get("sexy", memory), "memories": memories,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "labels_updated_at": cursors.get("sexy", labels_updated_at),
                    "labels_updated_at_by_category": cursors}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def qwen(instruction, max_tokens=4096):
    payload = json.dumps({
        "messages": [{"role": "user", "content": instruction}],
        "temperature": 0.9,
        "max_tokens": max_tokens,
        "enable_thinking": False,
        "tools": False,
    }, ensure_ascii=False).encode("utf-8")
    req = request.Request(BASE + "/api/chat/completions", data=payload,
                          headers={"Content-Type": "application/json"})
    last_error = None
    for attempt in range(1, 5):
        try:
            with request.urlopen(req, timeout=240) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 502, 503, 504} or attempt == 4:
                raise
            delay = 5 if exc.code == 429 else attempt
            message = "请求太多，请稍后重试" if exc.code == 429 else "网关暂时不可用"
            log(f"  Qwen {message}（HTTP {exc.code}），{delay} 秒后重试 ({attempt}/3)…")
            time.sleep(delay)
            continue
        except (URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == 4:
                raise
            log(f"  Qwen 请求失败（{exc}），{attempt} 秒后重试 ({attempt}/3)…")
        time.sleep(attempt)
    raise last_error


def qwen_text(instruction, max_tokens=4096):
    result = qwen(instruction, max_tokens)
    return (result.get("choices") or [{}])[0].get("message", {}).get("content") or ""


def extract_json_object(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def extract_json_array(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


def chunk_by_chars(refs, budget):
    groups, current, size = [], [], 0
    for ref in refs:
        text = f"{ref['index']}. [{PREF_TAG[ref['pref']]}] {ref['prompt']}"
        if current and size + len(text) > budget:
            groups.append(current)
            current, size = [], 0
        current.append(ref)
        size += len(text)
    if current:
        groups.append(current)
    return groups


def chunk_by_count(refs, max_items=CHUNK_MAX_PROMPTS):
    return [refs[i:i + max_items] for i in range(0, len(refs), max_items)]


def format_refs(refs):
    lines = []
    for ref in refs:
        total = ref.get("liked", 0) + ref.get("disliked", 0)
        ratio = ""
        if total:
            liked = ref.get("liked", 0)
            disliked = ref.get("disliked", 0)
            ratio = f"（喜欢 {liked}/{total}={liked / total:.0%}，不喜欢 {disliked}/{total}={disliked / total:.0%}）"
        lines.append(f"{ref['index']}. [{PREF_TAG[ref['pref']]}]{ratio} {ref['prompt']}")
    return "\n".join(lines)


def category_memory_rules(category):
    if category == "closeup":
        return (
            "当前类别是‘女生特写（上半身）’，只维护美女人脸与上半身审美。固定标签：年轻、女性、漂亮；主体必须是年轻成年女性（明确为成年人）。"
            "重点总结脸型、五官比例、眼神表情、发型、发色、妆容、皮肤质感、肩颈和上半身服装的审美偏好；排除腿部、鞋履、全身比例、性感诱惑和裸露内容。"
        )
    return "当前类别是‘性感女性’，保持女性、性感、诱惑的核心气质。"


def update_memory(refs, budget, category="sexy"):
    """把旧记忆 + 全部带标注原文喂给 Qwen，让它自己总结/更新记忆。"""
    memory = load_memory(category)
    log(f"现有记忆长度：{len(memory)} 字，喂入预算 {budget} 字/组")
    groups = chunk_by_chars(refs, budget)
    for gi, group in enumerate(groups, 1):
        instruction = (
            "你在维护一段关于用户图片审美的偏好记忆。\n"
            f"你当前的记忆：\n{memory or '（空）'}\n\n"
            "下面是最新标注的参考提示词（[喜欢]/[不喜欢]/[未标注]），请你通读后自己总结并更新记忆：\n"
            + format_refs(group) +
            "\n\n只输出 JSON：{\"memory\": \"更新后的完整记忆\"}。要求："
            "只描述用户喜欢与要避开的风格特征（摄影/渲染类型、光线质感、镜头语言、构图、人物气质、服装、场景、氛围），"
            f"不要罗列具体提示词；{category_memory_rules(category)}；1000 字以内；不要任何解释。"
        )
        for attempt in range(1, 4):
            content = qwen_text(instruction, max_tokens=2048)
            obj = extract_json_object(content)
            if obj and obj.get("memory"):
                memory = obj["memory"].strip()
                log(f"  记忆更新（第 {gi}/{len(groups)} 组）→ {len(memory)} 字")
                break
            log(f"  记忆解析失败（尝试 {attempt}）：{content[:100]!r}")
            time.sleep(2)
    save_memory(memory, max((r.get("label_updated_at", "") for r in refs), default=""), category)
    log(f"记忆已保存到 {MEMORY_FILE.name}（{category}：{len(memory)} 字）")
    return memory


def rewrite_refs(refs, memory, retry=False, prompt_extra="", category="sexy"):
    if category == "closeup":
        category_rules = (
            "当前类别：女生特写（上半身）。固定标签：年轻、女性、漂亮。主体必须是年轻成年女性（明确为成年人），画面以脸部和上半身为主，优先突出五官、眼神、发型、妆容、皮肤真实质感、肩颈线条和上半身服装。"
            "禁止引入性感、诱惑、裸露、内衣、腿部、鞋履、全身展示或男性主体等方向。"
        )
        diversity_rules = (
            "每条在脸型、五官特点、表情、发型发色、妆容、上半身服装、背景、光线、镜头焦段和构图中进行不同组合；相邻各条不得复用同一组核心元素，差异要明显。"
        )
    else:
        category_rules = "当前类别：性感女性。固定保持女性、性感、诱惑的核心气质，主体必须是女性。"
        diversity_rules = (
            "每条随机组合不同的人物身份与气质、动作姿态、服装款式和材质、道具、环境、季节天气、光线、色彩、视角与构图；相邻各条不得复用同一组核心元素，整体差异要明显。"
        )
    instruction = (
        f"你维护了下面这段关于用户图片审美的记忆：\n{memory}\n\n"
        + category_rules + "\n"
        + ("以下几条图片提示词字数不足 100 字，请重新仿写，每条必须至少 120 字。\n" if retry else "请按记忆中的偏好，为下面每条参考提示词仿写一条全新提示词。\n")
        + "硬性要求：\n"
        "1. 风格、光线质感、镜头语言按对应类别记忆执行；\n"
        "2. 记忆只作为审美方向，不要把其中的具体服饰、场景或动作当成固定模板；允许主动发挥，探索参考中未出现过的设定。\n"
        f"3. {diversity_rules}\n"
        + ("4. 不得输出与类别无关的性暗示或身体部位描写。\n" if category == "closeup" else "")
        + ("5. 每条至少 120 字。\n" if retry else ("4. 每条至少 100 字。\n" if category == "closeup" else "4. 每条至少 100 字。\n"))
        + "只输出 JSON 数组 [{\"index\": 序号, \"prompt\": \"...\"}]，不要解释。\n\n"
        + format_refs(refs)
        + (f"\n\n额外创作要求：{prompt_extra}" if prompt_extra.strip() else "")
    )
    last = None
    for attempt in range(1, 4):
        content = qwen_text(instruction, max_tokens=4096)
        parsed = extract_json_array(content)
        if parsed:
            return {int(item.get("index")): str(item.get("prompt", "")).strip()
                    for item in parsed if str(item.get("prompt", "")).strip()}
        last = f"无法解析（尝试 {attempt}）: {content[:120]!r}"
        time.sleep(2)
    raise RuntimeError(last or "仿写失败")


def submit_prompts(prompts, image_batch_size=1, category="sexy"):
    payload = json.dumps({"prompts": prompts, "width": WIDTH, "height": HEIGHT, "batch_size": image_batch_size,
                          "metadata": {"rewrite_category": category}},
                         ensure_ascii=False).encode("utf-8")
    req = request.Request(BASE + "/photo/api/generate/batch", data=payload,
                          headers={"Content-Type": "application/json"})
    for attempt in range(1, 4):
        try:
            with request.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
            return json.loads(body).get("created", 0)
        except HTTPError as exc:
            if exc.code not in {429, 502, 503, 504} or attempt == 3:
                raise
            delay = 5 if exc.code == 429 else attempt
            message = "请求太多，请稍后重试" if exc.code == 429 else "接口暂时不可用"
            log(f"  生成接口{message}（HTTP {exc.code}），{delay} 秒后重试 ({attempt}/2)…")
            time.sleep(delay)
            continue
        except (URLError, TimeoutError) as exc:
            if attempt == 3:
                raise
            log(f"  提交请求失败（{exc}），{attempt} 秒后重试 ({attempt}/2)…")
        time.sleep(attempt)


def main():
    parser = argparse.ArgumentParser(description="偏好记忆 + 流式仿写 + 批量生成")
    parser.add_argument("--ctx", type=int, default=32768,
                        help="模型上下文大小（token）。记忆喂入预算取 ctx 的一半；64k/96k 时单次吃下全部参考")
    parser.add_argument("--daemon", action="store_true", help="批次完成后保持进程运行，等待手动停止")
    parser.add_argument("--memory-every", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--prompt-extra", default="")
    parser.add_argument("--image-batch-size", type=int, default=2)
    parser.add_argument("--category", choices=["sexy", "closeup", "all"], default="sexy")
    args = parser.parse_args()

    refs = load_reference()
    dist = Counter(ref["pref"] for ref in refs)
    log(f"读取偏好标注：{dict(dist)}（共 {len(refs)} 条参考，模型 ctx={args.ctx}）")

    memory_key = _memory_key(args.category)
    with memory_file_lock():
        memory_text, labels_updated_at = load_memory_state(memory_key)
        if labels_updated_at:
            new_refs = scan_refs(labeled_only=True, after_time=labels_updated_at)
            if new_refs:
                log(f"检测到 {len(new_refs)} 条新标注，更新 {memory_key} 类别增量记忆")
                memory = update_memory(new_refs, max(2000, args.ctx // 2), memory_key)
            else:
                memory = memory_text
                log(f"未检测到 {memory_key} 类别新标注，复用现有记忆")
        else:
            memory = update_memory(refs, max(2000, args.ctx // 2), memory_key)

    chunks = chunk_by_count(refs, max(1, args.batch_size))
    log(f"分 {len(chunks)} 批流式「按记忆仿写→生成」")
    all_rewritten = {}
    submitted_total = 0
    checkpoint_counter = 0
    memory_budget = max(2000, args.ctx // 2)
    for chunk_index, chunk in enumerate(chunks, 1):
        category = ("closeup" if chunk_index % 2 == 0 else "sexy") if args.category == "all" else args.category
        lo, hi = chunk[0]["index"], chunk[-1]["index"]
        log(f"[{chunk_index}/{len(chunks)}] 仿写 {lo}-{hi} …")
        result = rewrite_refs(chunk, memory, retry=False, prompt_extra=args.prompt_extra, category=category)
        for _ in range(3):
            short = [ref for ref in chunk if len(result.get(ref["index"], "")) < MIN_CHARS]
            if not short:
                break
            log(f"  不足 {MIN_CHARS} 字 {len(short)} 条，重写 …")
            result.update(rewrite_refs(short, memory, retry=True, prompt_extra=args.prompt_extra, category=category))

        good = {ref["index"]: result[ref["index"]] for ref in chunk if len(result.get(ref["index"], "")) >= MIN_CHARS}
        for ref in chunk:
            if ref["index"] in good:
                all_rewritten[ref["index"]] = good[ref["index"]]
            else:
                log(f"  ⚠ 第 {ref['index']} 条仍不足字数，跳过")
        if good:
            created = submit_prompts([good[ref["index"]] for ref in chunk if ref["index"] in good], max(1, args.image_batch_size), category)
            submitted_total += created
            checkpoint_counter += created
            log(f"  → 提交 {created} 条生成，累计 {submitted_total} 条")

        # 每生成 40 张，派发一次「总结记忆」任务：重扫最新 like/unlike 标注让 Qwen 更新记忆
        if checkpoint_counter >= max(1, args.memory_every):
            log(f"⚙ 每 {args.memory_every} 张：派发总结记忆任务（重扫最新标注）…")
            with memory_file_lock():
                _, cursor = load_memory_state(memory_key)
                latest = scan_refs(labeled_only=True, after_time=cursor)
                if latest:
                    memory = update_memory(latest, memory_budget, memory_key)
            checkpoint_counter = 0

    log(f"流式完成：改写 {len(all_rewritten)} 条，提交 {submitted_total} 条")
    out = ROOT / "rewritten_prompts.json"
    out.write_text(json.dumps([all_rewritten[i] for i in sorted(all_rewritten)], ensure_ascii=False, indent=2),
                   encoding="utf-8")
    log(f"已保存 {out.name}")
    if args.daemon:
        log("常驻模式：30 秒后开始下一轮生成，按 Ctrl+C 停止")
        time.sleep(30)
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
