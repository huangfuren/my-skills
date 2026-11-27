"""文字度量 → 直接可写进 SVG 的数值，替代「试字号、试 textLength」的循环。

用法：
    python textfit.py 图.png --color A349A4 --region 466,520,132,168 [--text 大用电器]

    --color   RRGGBB 或 R,G,B；也可以用 --layer N 取调色板第 N 色
    --region  x0,x1,y0,y1 —— **必须是紧贴文字的框**，否则会把同色图形（椭圆环、导线）算进来
    --text    知道文字内容时给出平均字宽与拉伸比，用来判断 textLength 是否写大

输出：
    墨迹框、宽高、建议 font-size、建议 textLength、建议基线
    以及三条自检警告（选区是否吞了图形、字号是否超出常识范围、是否被横向拉宽）

判读兜底：本工具只负责算数，最终仍要渲染回来跑 diffcheck 验证。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngx import bits_bytes, color_bits, color_stats, read_png, text_metrics


def _parse_color(s):
    s = s.strip().lstrip("#")
    if "," in s:
        return tuple(int(v) for v in s.split(","))
    if len(s) != 6:
        raise ValueError("颜色格式应为 RRGGBB 或 R,G,B")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("image")
    ap.add_argument("--color", default=None, help="RRGGBB 或 R,G,B")
    ap.add_argument("--layer", type=int, default=1, help="未给 --color 时取调色板第 N 色（从 1 开始）")
    ap.add_argument("--region", required=True, help="x0,x1,y0,y1，紧贴文字的框")
    ap.add_argument("--text", default="")
    ap.add_argument("--tol", type=int, default=45)
    ap.add_argument("--cjk-ratio", type=float, default=0.866)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        x0, x1, y0, y1 = [int(v) for v in args.region.split(",")]
    except Exception:
        print("--region 需要 x0,x1,y0,y1 四个整数", file=sys.stderr)
        return 2

    try:
        w, h, px = read_png(args.image)
    except Exception as e:
        print("读图失败：%s" % e, file=sys.stderr)
        return 2

    if args.color:
        ref = _parse_color(args.color)
    else:
        pal = color_stats(px, w, h)
        if not pal:
            print("没有非白像素", file=sys.stderr)
            return 2
        idx = max(0, min(len(pal) - 1, args.layer - 1))
        ref = pal[idx][:3]
        if not args.json:
            print("取调色板第 %d 色 #%02X%02X%02X（共 %d 个主色）"
                  % (idx + 1, ref[0], ref[1], ref[2], len(pal)))

    bits = bits_bytes(color_bits(px, w, h, ref, args.tol), w * h)
    m = text_metrics(bits, w, x0, x1, y0, y1, text=args.text, cjk_ratio=args.cjk_ratio)
    if not m:
        print("该区域内没有命中颜色 #%02X%02X%02X" % ref, file=sys.stderr)
        return 2

    bx0, bx1, by0, by1 = m["bbox"]
    warns = []
    # 选区自检：字框贴住了区域边界，说明框给小了或区域内混进了图形
    edges = sum([bx0 <= x0, bx1 >= x1 - 1, by0 <= y0, by1 >= y1 - 1])
    if edges >= 3:
        warns.append("墨迹框有 %d 条边贴住选区边界 → 选区可能吞进了同色图形，收紧 --region 再测" % edges)
    if not (6 <= m["h"] <= 48):
        warns.append("墨迹高 %dpx 不在常见正文字号范围，确认没把图形算进来" % m["h"])
    if m.get("stretch") and m["stretch"] > 1.05:
        warns.append("字宽/字号 = %.2f > 1.05：源图字形偏宽或有字距，textLength 按实测 %d 写，不要用字号×字数推算"
                     % (m["stretch"], m["text_length"]))
    if m.get("stretch") and m["stretch"] < 0.68:
        warns.append("字宽/字号 = %.2f < 0.68：常规中文墨迹约占字号的 0.85~1.0，这么窄多半是选区裁到了两侧，"
                     "或者源图是压缩排版（那就照实测 %d 写 textLength）"
                     % (m["stretch"], m["text_length"]))

    out = {
        "color": "#%02X%02X%02X" % ref,
        "bbox": m["bbox"], "w": m["w"], "h": m["h"],
        "font_size": m["font_size"], "text_length": m["text_length"],
        "baseline": m["baseline"], "x": bx0,
        "avg_advance": m.get("avg_advance"), "stretch": m.get("stretch"),
        "warnings": warns,
    }

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("墨迹框 x%d-%d y%d-%d   墨迹 %dx%d" % (bx0, bx1, by0, by1, m["w"], m["h"]))
        print()
        print('建议写进 SVG：')
        print('  <text x="%d" y="%d" font-size="%s"' % (bx0, m["baseline"], m["font_size"]))
        print('        textLength="%d" lengthAdjust="spacingAndGlyphs">%s</text>'
              % (m["text_length"], args.text or "文字"))
        if m.get("avg_advance"):
            print()
            print("平均字宽 %.1fpx（%d 字），字宽/字号 = %.2f"
                  % (m["avg_advance"], len(args.text), m["stretch"]))
        if warns:
            print()
            for a in warns:
                print("· " + a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
