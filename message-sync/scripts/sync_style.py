#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从原始语料（raw_ty）重新生成 style_guide.md 的「动态风格档案」区块。

只替换 style_guide.md 中 <!-- AUTO-SYNC:START --> 与 <!-- AUTO-SYNC:END --> 之间的
内容，上面手写的规则区不会被覆盖。

用法:
    python3 sync_style.py                      # 用默认语料路径同步
    python3 sync_style.py --source /path/raw   # 指定语料
    python3 sync_style.py --dry-run            # 只打印将要写入的内容，不落盘

退出码: 0 正常（含无变化） / 1 语料不可读
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)

# 语料路径：优先环境变量 MSG_RAW_CORPUS，其次技能目录内 references/raw_ty.txt，
# 最后当前工作目录下的 raw_ty.txt（便于临时挂一份语料跑同步）。
# 没有语料时，style_guide.md 里已固化的动态档案即为静态基线，
# 整理消息照常可用，只是不再自动刷新。
_SRC_CANDS = [
    os.environ.get("MSG_RAW_CORPUS", ""),
    os.path.join(SKILL_DIR, "references", "raw_ty.txt"),
    os.path.join(os.getcwd(), "raw_ty.txt"),
]
DEFAULT_SOURCE = next((c for c in _SRC_CANDS if c and os.path.exists(c)), _SRC_CANDS[1])
GUIDE_FILE = os.path.join(SKILL_DIR, "references", "style_guide.md")
STATE_FILE = os.path.join(SKILL_DIR, "references", ".style_state.json")


START = "<!-- AUTO-SYNC:START -->"
END = "<!-- AUTO-SYNC:END -->"

SEP_RE = re.compile(r"^\s*=+\s*$")
AT_RE = re.compile(r"@([^\s@，,。:：、；;]{1,15})")
BRACKET_RE = re.compile(r"【([^】]{1,40})】")
QUANT_RE = re.compile(r"\d+\s*%|\d+\s*(?:条|台|个|天|小时|分钟|元|万|次|步|人|年|月)")
TIME_RE = re.compile(r"今天|明天|后天|本周|上周|下周|下下周|周[一二三四五六日]|"
                     r"\d{1,2}\s*月|\d{1,2}\s*[:：]\s*\d{2}|\d{1,2}\s*点")
NUM_CN_RE = re.compile(r"^[一二三四五六七八九十]+、")
NUM_ZH_RE = re.compile(r"^第[一二三四五六七八九十]+[：:]")
NUM_AR_RE = re.compile(r"^\d+[、.．]")


INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")


def clean(text):
    """去掉零宽/不可见字符（语料从 IM 复制时常带 U+2060 之类）。"""
    return INVISIBLE_RE.sub("", text).strip()


def md5(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def split_blocks(text):
    """按空行和 ===== 分隔线切成段落块。"""
    blocks, cur = [], []
    for line in text.splitlines():
        if SEP_RE.match(line):
            if cur:
                blocks.append("\n".join(cur).strip())
                cur = []
            continue
        if not line.strip():
            if cur:
                blocks.append("\n".join(cur).strip())
                cur = []
        else:
            cur.append(line.rstrip())
    if cur:
        blocks.append("\n".join(cur).strip())
    return [b for b in blocks if b]


def top(counter, n, fmt=lambda x: x):
    return [(fmt(k), v) for k, v in counter.most_common(n)]


def analyze(text, blocks):
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    at = Counter()
    for m in AT_RE.finditer(text):
        name = clean(m.group(1))
        if name and not re.match(r"^[\d.]+$", name):
            at[name] += 1

    brackets = Counter()
    for m in BRACKET_RE.finditer(text):
        word = m.group(1).strip()
        if word and not re.match(r"^[\d\s%./-]+$", word):
            brackets[word] += 1

    quant = [l for l in lines if QUANT_RE.search(l)]
    times = Counter()
    for l in lines:
        for m in TIME_RE.finditer(l):
            times[m.group(0)] += 1

    openers = Counter()
    for b in blocks:
        first = clean(b.splitlines()[0])
        if first and len(first) >= 4:
            openers[first[:28]] += 1

    return {
        "chars": len(text),
        "lines": len(lines),
        "blocks": len(blocks),
        "at": top(at, 12, lambda x: "@" + x),
        "num_cn": sum(1 for l in lines if NUM_CN_RE.match(l)),
        "num_zh": sum(1 for l in lines if NUM_ZH_RE.match(l)),
        "num_ar": sum(1 for l in lines if NUM_AR_RE.match(l)),
        "bracket_total": sum(brackets.values()),
        "brackets": top(brackets, 15),
        "quant_recent": quant[-8:],
        "times": top(times, 10),
        "openers": top(openers, 10),
    }


def render(stat, new_blocks, synced_at, source):
    out = []
    out.append("> 上次同步：%s　语料：`%s`" % (synced_at, source))
    out.append("> 语料规模：%d 行 / %d 字 / %d 个段落块" %
               (stat["lines"], stat["chars"], stat["blocks"]))
    out.append("")

    def table(title, rows, headers, empty="（未识别到）"):
        out.append("**%s**" % title)
        out.append("")
        if not rows:
            out.append(empty)
            out.append("")
            return
        out.append("| %s | %s |" % (headers[0], headers[1]))
        out.append("|---|---|")
        for k, v in rows:
            out.append("| `%s` | %d |" % (str(k).replace("|", "\\|"), v))
        out.append("")

    table("高频 @ 对象", stat["at"], ["对象", "次数"])
    out.append("**编号体系使用分布**")
    out.append("")
    out.append("| 体系 | 写法示例 | 命中行数 |")
    out.append("|---|---|---|")
    out.append("| 大写中文 | `一、背景` | %d |" % stat["num_cn"])
    out.append("| 中文序数 | `第一：` | %d |" % stat["num_zh"])
    out.append("| 阿拉伯数字 | `1、` `1. ` | %d |" % stat["num_ar"])
    out.append("")
    table("【】标注高频内容（共 %d 处）" % stat["bracket_total"],
          stat["brackets"], ["标注内容", "次数"])
    table("常见开场白", stat["openers"], ["首句", "次数"])
    table("时间表达", stat["times"], ["表达", "次数"])

    out.append("**量化表达样例（最近 %d 条）**" % len(stat["quant_recent"]))
    out.append("")
    if stat["quant_recent"]:
        for l in stat["quant_recent"]:
            out.append("- " + (l[:90] + "…" if len(l) > 90 else l))
    else:
        out.append("（未识别到）")
    out.append("")

    out.append("**本次新增样本（%d 段）**" % len(new_blocks))
    out.append("")
    if new_blocks:
        out.append("> 相比上次同步新增的内容，作为**最新风格参考**优先模仿：")
        out.append("")
        for b in new_blocks[:5]:
            out.append("```text")
            out.append(b[:400] + ("\n…" if len(b) > 400 else ""))
            out.append("```")
            out.append("")
    else:
        out.append("本次无新增内容（语料与上次一致）。")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (ValueError, OSError):
            pass
    return {"fingerprints": []}


def main():
    ap = argparse.ArgumentParser(description="同步 raw_ty 语料到风格档案")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="语料文件路径")
    ap.add_argument("--dry-run", action="store_true", help="只预览不写入")
    ap.add_argument("--new-sample", type=int, default=5, help="新增样本最多展示几段")
    args = ap.parse_args()

    source = os.path.expanduser(args.source)
    if not os.path.exists(source):
        print("ERROR: 语料不存在: %s" % source, file=sys.stderr)
        print(
            "提示：这只影响「动态风格档案」的自动刷新，不影响消息整理本身。\n"
            "      style_guide.md 里已固化的档案可继续当作静态基线使用。\n"
            "      如需更新风格，用 --source 指定语料，或把语料放到\n"
            "      %s（也可设环境变量 MSG_RAW_CORPUS）。"
            % os.path.join(SKILL_DIR, "references", "raw_ty.txt"),
            file=sys.stderr,
        )
        return 1

    with open(source, "r", encoding="utf-8", errors="replace") as fh:
        text = clean(fh.read())

    blocks = split_blocks(text)
    stat = analyze(text, blocks)

    state = load_state()
    known = set(state.get("fingerprints", []))
    current = [md5(b) for b in blocks]
    first_run = not known
    new_blocks = [b for b, fp in zip(blocks, current) if fp not in known]

    synced_at = time.strftime("%Y-%m-%d %H:%M:%S")
    body = render(stat, new_blocks[:args.new_sample], synced_at, source)

    if args.dry_run:
        print(body)
        print("\n[DRY-RUN] 未写入。新增 %d 段 / 共 %d 段。"
              % (len(new_blocks), len(blocks)))
        return 0

    if not os.path.exists(GUIDE_FILE):
        print("ERROR: 找不到 %s" % GUIDE_FILE, file=sys.stderr)
        return 1

    with open(GUIDE_FILE, "r", encoding="utf-8") as fh:
        guide = fh.read()

    if START in guide and END in guide:
        head, rest = guide.split(START, 1)
        _, tail = rest.split(END, 1)
        new_guide = head + START + "\n\n" + body + "\n" + END + tail
    else:
        new_guide = guide.rstrip() + "\n\n" + START + "\n\n" + body + "\n" + END + "\n"

    with open(GUIDE_FILE, "w", encoding="utf-8") as fh:
        fh.write(new_guide)

    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump({"synced_at": synced_at, "source": source,
                   "block_count": len(blocks), "fingerprints": current},
                  fh, ensure_ascii=False, indent=2)

    print("SYNCED: %s" % GUIDE_FILE)
    print("新增样本 %d 段（历史累计 %d 段）%s"
          % (len(new_blocks), len(blocks), "［首次建档］" if first_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
