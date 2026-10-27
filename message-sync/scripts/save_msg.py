#!/usr/bin/env python3
"""
把整理好的消息写入桌面，文件名 message-<标题>-<时间戳>.txt，保证永不覆盖已有文件。

用法（下文 python3 在 Windows 上无该命令时改用 python）:
    # 1. 从标准输入读内容
    cat msg.txt | python3 save_msg.py

    # 2. 从文件读内容
    python3 save_msg.py -f /tmp/msg.txt

    # 3. 直接传字符串
    python3 save_msg.py -c "来自:xxx\n……"

    # 4. 指定输出目录（默认自动探测桌面）
    python3 save_msg.py -f msg.txt -d ~/Desktop

文件名规则:
    message-<标题>-YYYYmmdd-HHMMSS.txt（标题取正文首行，自动剥离 @ 前缀与序号前缀）
    无标题/首行非标题时退化为 message-YYYYmmdd-HHMMSS.txt
    若同名文件已存在（同一秒内连续生成），依次追加 -2、-3 …，绝不覆盖。
"""

import argparse
import os
import re
import sys
import time

INVALID_FS = set('\\/:*?"<>|')


def _default_desktop() -> str:
    """探测真实桌面目录。

    Windows 上桌面经常被重定向到非系统盘，而 `~/Desktop` 展开成
    用户主目录下的 Desktop 并不存在，直接写会失败。
    优先级：注册表登记值 > 常见候选 > 用户主目录。
    """
    cands = []
    if os.name == "nt":
        try:
            import winreg

            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                v, _ = winreg.QueryValueEx(k, "Desktop")
            cands.append(os.path.expandvars(v))
        except (OSError, ImportError):
            pass
    cands += [
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/桌面"),
        r"D:\Users\Desktop",
        r"D:\Desktop",
        r"E:\Desktop",
    ]
    for c in cands:
        if c and os.path.isdir(c):
            return c
    return os.path.expanduser("~")



def _slugify(text: str, maxlen: int = 32) -> str:
    """把标题转成适合做文件名的片段：去掉非法字符、空格、换行。"""
    out = []
    for ch in text:
        if ch in INVALID_FS or ch in "\n\r\t \u3000":
            continue
        out.append(ch)
        if len(out) >= maxlen:
            break
    return "".join(out) or ""


def _topic(content: str) -> str:
    """从内容里提取可辨识标题。

    首行常是 `@所有人`，剥掉 @ 对象后如果空了就继续往下找，
    跳过空行——否则「@所有人 + 空行 + 【标题】」这种最常见格式会丢掉标题。
    """
    for line in content.strip("\n").split("\n"):
        first = line.strip()
        if not first:
            continue
        if first.startswith("@"):
            first = " ".join(
                tok for tok in first.split(" ") if not tok.startswith("@")
            ).strip()
            if not first:
                continue
        # 识别【…】标题，可能是 1.【…】 或 【…】
        if "【" in first and "】" in first:
            return _slugify(first)
        # 去掉前导序号再取首段
        no_num = re.sub(r"^\d+[.、)）]\s*", "", first)
        return _slugify(no_num)
    return ""


def unique_path(directory: str, content: str) -> str:
    """生成唯一且不覆盖的文件路径，文件名带正文标题提高辨识度。"""
    base = time.strftime("%Y%m%d-%H%M%S")
    topic = _topic(content)
    stem = f"{topic}-{base}" if topic else base
    path = os.path.join(directory, f"message-{stem}.txt")
    if not os.path.exists(path):
        return path
    # 同一秒内再次生成，依次追加 -2、-3 …，绝不覆盖
    for idx in range(2, 1000):
        path = os.path.join(directory, f"message-{stem}-{idx}.txt")
        if not os.path.exists(path):
            return path
    raise RuntimeError("无法生成唯一文件名，桌面同名文件过多")


def main():
    parser = argparse.ArgumentParser(description="保存整理后的消息到桌面")
    parser.add_argument("-f", "--file", help="从文件读取内容")
    parser.add_argument("-c", "--content", help="直接传入内容字符串")
    parser.add_argument(
        "-d",
        "--dir",
        default=None,
        help="输出目录，默认自动探测桌面（Windows 桌面常被重定向到非系统盘）",
    )
    parser.add_argument("--no-preview", action="store_true", help="不回显内容")
    args = parser.parse_args()

    if args.content is not None:
        content = args.content
    elif args.file:
        with open(os.path.expanduser(args.file), encoding="utf-8") as fh:
            content = fh.read()
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
    else:
        parser.error("未提供内容：用 -c / -f 或管道传入")

    content = content.rstrip("\n") + "\n"
    if not content.strip():
        parser.error("内容为空，拒绝写入")

    directory = os.path.expanduser(args.dir) if args.dir else _default_desktop()
    os.makedirs(directory, exist_ok=True)

    path = unique_path(directory, content)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)

    print(f"SAVED: {path}")
    print(f"CHARS: {len(content)}")
    if not args.no_preview:
        print("----- content -----")
        print(content, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
