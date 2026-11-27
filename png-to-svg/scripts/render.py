#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SVG 渲染为 PNG（Edge headless），供 png-to-svg 第 7 步「1:1 渲染」与目视验收

- 宽度必须等于原图宽度，否则像素差分对不上；高度按 viewBox 宽高比自动算
- 批量循环不互相覆盖：文件名带父目录前缀
- 输出目录默认 ./render/，用完即弃，不要提交
- Edge 路径自动探测，可用 --edge 或环境变量 EDGE_PATH 覆盖

用法:
  python render.py 图.svg --width 1353 --scale 1          # 1:1 渲染，给 diffcheck 用
  python render.py images/ --width 800                    # 批量，缩到 800 宽看可读性
  python render.py 图.svg --width 1353 --scale 2 --out preview   # 2 倍图，给目视用

选项: --width 默认 1240 | --scale 默认 2 | --out 默认 render | --edge <msedge.exe>

退出码: 0=全部渲染成功；1=有失败或没找到 SVG
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
# Edge 已在运行时，headless 复用现有实例会以 0xE0000008 失败；独占 profile 可避开
PROFILE_DIR = Path(tempfile.gettempdir()) / "svg-render-profile"


def parse_args(argv):
    o = {"width": 1240, "scale": 2, "out": None, "edge": None, "paths": []}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        if a in ("--width", "--scale", "--out", "--edge"):
            i += 1
            if i >= len(argv):
                sys.exit("%s 缺少参数" % a)
            key = a[2:]
            o[key] = argv[i] if key in ("out", "edge") else int(argv[i])
        else:
            o["paths"].append(a)
        i += 1
    if not o["paths"]:
        sys.exit("用法: render.py <svg文件或目录>... [--width 1240] [--scale 2] [--out DIR]\n用 --help 看说明")
    return o


def find_edge(explicit):
    for c in ([explicit] if explicit else []) + [os.environ.get("EDGE_PATH")] + list(EDGE_CANDIDATES):
        if c and Path(c).exists():
            return c
    sys.exit("找不到 msedge.exe：用 --edge 指定路径，或设环境变量 EDGE_PATH")


def svg_size(p: Path):
    """从 viewBox 取宽高比；退化为 width/height 属性"""
    text = p.read_text(encoding="utf-8", errors="ignore")[:4000]
    m = re.search(r'viewBox\s*=\s*"\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)"', text)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        if w > 0 and h > 0:
            return w, h
    mw = re.search(r'<svg[^>]*\bwidth\s*=\s*"([\d.]+)', text)
    mh = re.search(r'<svg[^>]*\bheight\s*=\s*"([\d.]+)', text)
    if mw and mh:
        return float(mw.group(1)), float(mh.group(1))
    return None


def collect(paths):
    files = []
    for t in paths:
        p = Path(t) if os.path.isabs(t) else (Path.cwd() / t)
        if p.is_file() and p.suffix.lower() == ".svg":
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(x for x in p.rglob("*.svg") if "_render" not in x.parts))
    return files


def main():
    o = parse_args(sys.argv[1:])
    edge = find_edge(o["edge"])
    out = Path(o["out"]) if o["out"] else (Path.cwd() / "render")
    out.mkdir(parents=True, exist_ok=True)
    width = o["width"]

    files = collect(o["paths"])
    if not files:
        print("没找到 SVG，检查路径：%s" % " ".join(o["paths"]))
        return 1

    print("== SVG 渲染 → %s（宽 %d，缩放 %dx）==" % (out, width, o["scale"]))
    print("   Edge: %s" % edge)
    print("")
    fails = 0
    for p in files:
        size = svg_size(p)
        if size:
            w, h = size
            win_h = max(1, round(h * width / w))
        else:
            win_h = width  # 取不到比例时退化成正方形窗口，靠目视判断是否截断
        prefix = p.parent.name if p.parent.name != "images" else p.parent.parent.name
        # Edge 的 --screenshot 按自身工作目录解析相对路径，必须给绝对路径
        png = (out / ("%s__%s-w%d.png" % (prefix, p.stem, width))).resolve()
        cmd = [
            edge, "--headless=new", "--disable-gpu", "--no-first-run",
            "--user-data-dir=%s" % PROFILE_DIR,
            "--force-device-scale-factor=%d" % o["scale"],
            "--screenshot=%s" % png,
            "--window-size=%d,%d" % (width, win_h),
            "--default-background-color=FFFFFFFF",
            "file:///" + quote(p.resolve().as_posix()),
        ]
        code = "超时"
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=90)
            okfile = png.exists() and png.stat().st_size > 0
            code = "returncode=%d" % r.returncode
        except subprocess.TimeoutExpired:
            okfile = False
        if okfile:
            print("   OK    %s  (%d×%d)" % (png.name, width * o["scale"], win_h * o["scale"]))
        else:
            fails += 1
            print("   FAIL  %s  （%s，窗口 %d×%d）" % (p.name, code, width, win_h))
    print("")
    print("   %d 张渲染完成，%d 张失败" % (len(files) - fails, fails))
    print("   下一步：diffcheck.py 比像素；再出一张 2 倍图目视，不许跳过")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
