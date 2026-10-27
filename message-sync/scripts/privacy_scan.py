#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脱敏自检：扫描目录里可能泄露组织 / 个人 / 内网信息的片段。

用法:
    python3 privacy_scan.py [路径]             # 路径默认当前目录
    python3 privacy_scan.py . --strict         # 有命中则退出码 1，可接 CI
    python3 privacy_scan.py . --rules my.txt   # 追加自定义 deny 词表

检测项:
    内网 IP / 带用户名的绝对路径 / 邮箱 / 手机号 / @中文姓名 / 自定义 deny 词

退出码: 0 无命中（或未开 strict）/ 1 strict 模式下有命中 / 2 路径不存在
"""
import argparse
import os
import re
import sys

TEXT_EXT = {
    ".md", ".markdown", ".txt", ".py", ".json", ".yaml", ".yml",
    ".sh", ".bash", ".mjs", ".js", ".ts", ".css", ".html", ".toml", ".ini",
}

RULES = [
    ("内网IP", re.compile(
        r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)"
        r"\.\d{1,3}\.\d{1,3}\b")),
    ("绝对路径", re.compile(
        r"(?:/Users/|/home/|[A-Za-z]:[\\/]Users[\\/])"
        r"([A-Za-z0-9_.\-\u4e00-\u9fa5]{2,})")),
    ("邮箱", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("@中文姓名", re.compile(r"@([\u4e00-\u9fa5]{2,4})")),
]

# 绝对路径里这些段名是系统固定项，不含个人信息，不算泄露
PATH_SAFE = {"Desktop", "Public", "Default", "Default User", "All Users"}

# @ 后接这些词是泛指，不是具体人名
AT_SAFE = {
    "所有人", "某人", "成员", "对象", "对象分块", "人和截止", "负责人",
    "决策人", "姓名", "团队", "客户", "项目", "各位", "全员", "对方",
    "上级", "领导", "同事", "相关人", "执行人", "审批人",
}

DEFAULT_RULES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "references", "privacy-rules.txt",
)


def load_rules(path):
    """读自定义词表：`deny: 词` 追加敏感词，`allow: 词` 追加 @ 白名单。"""
    deny, allow = [], set()
    if not path or not os.path.exists(path):
        return deny, allow
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("allow:"):
                allow.add(line[6:].strip())
            elif line.startswith("deny:"):
                w = line[5:].strip()
                if w:
                    deny.append(w)
    return deny, allow


def iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules"}]
        for name in filenames:
            if os.path.splitext(name)[1].lower() not in TEXT_EXT:
                continue
            yield os.path.join(dirpath, name)


def scan_file(path, deny, allow, self_path):
    hits = []
    if os.path.abspath(path) == self_path:
        return hits
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as fh:
            lines = fh.read().splitlines()
    except (UnicodeDecodeError, OSError):
        return hits

    for no, line in enumerate(lines, 1):
        seen = set()
        for cat, rx in RULES:
            if cat in seen:
                continue
            m = rx.search(line)
            if not m:
                continue
            if cat == "绝对路径" and m.group(1) in PATH_SAFE:
                continue
            if cat == "@中文姓名":
                word = m.group(1)
                if word in AT_SAFE or word in allow:
                    continue
            seen.add(cat)
            hits.append((no, cat, m.group(0)[:60]))

        for word in deny:
            if word in line:
                hits.append((no, "自定义词", word))
                break
    return hits


def main():
    ap = argparse.ArgumentParser(description="脱敏自检：扫描疑似敏感片段")
    ap.add_argument("path", nargs="?", default=".", help="要扫描的目录，默认当前目录")
    ap.add_argument("--rules", default=DEFAULT_RULES_FILE, help="自定义词表路径")
    ap.add_argument("--strict", action="store_true", help="有命中即非零退出")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    root = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.isdir(root):
        print("ERROR: 目录不存在: %s" % root, file=sys.stderr)
        return 2

    deny, allow = load_rules(args.rules)
    self_path = os.path.abspath(__file__)

    total, files_hit = 0, 0
    for path in sorted(iter_files(root)):
        hits = scan_file(path, deny, allow, self_path)
        if not hits:
            continue
        files_hit += 1
        rel = os.path.relpath(path, root).replace("\\", "/")
        for no, cat, frag in hits:
            total += 1
            print("%s:%d  %-8s %s" % (rel, no, cat, frag))

    print("")
    if total:
        print("HIT: %d 处 / %d 个文件" % (total, files_hit))
        if deny:
            print("自定义词：%s" % "、".join(deny))
        print("处置：确属真实信息的替换为占位符（见 SKILL.md「脱敏约定」）；"
              "占位符与泛指词可写入 privacy-rules.txt 的 allow 行。")
        return 1 if args.strict else 0
    print("CLEAN: 未发现疑似敏感片段（扫描 %s）" % root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
