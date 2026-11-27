"""上下对比图：上半放原图、下半放重绘，中间一条红带分隔。

这是还原流程里用得最多的工具——4 倍看局部，1 倍看整体。

用法：
    python compare.py 原图.png 重绘.png 输出.png x0 y0 w h scale
    python compare.py 原图.png 重绘.png 输出.png x0 y0 w h scale x0b y0b wb hb scaleb

第二组区域可省略，省略时上下两半取同一区域（最常见的用法）。
整图对比就写 x0=0 y0=0 w=原图宽 h=原图高 scale=1。

原版在 F:\\tmp\\compare.py；本版把位置参数换成 argparse（--help 与错误提示统一），
并加了 --force 覆盖保护，渲染逻辑未改。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngx import crop_scale, read_png, write_png


def main():
    ap = argparse.ArgumentParser(
        add_help=True, description="上下对比图：上=原图，下=重绘，中间红带")
    ap.add_argument("top", help="原图")
    ap.add_argument("bottom", help="重绘图")
    ap.add_argument("out", help="输出对比图")
    ap.add_argument("region", nargs="+", type=int,
                    help="x0 y0 w h scale，可选再给一组 x0b y0b wb hb scaleb")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的输出图")
    args = ap.parse_args()

    v = args.region
    if len(v) not in (5, 10):
        print("区域参数需要 5 个（x0 y0 w h scale）或 10 个（两组）", file=sys.stderr)
        return 2
    if os.path.exists(args.out) and not args.force:
        print("输出已存在：%s\n加 --force 才覆盖" % args.out, file=sys.stderr)
        return 2

    try:
        wa, ha, pa = read_png(args.top)
        wb, hb, pb = read_png(args.bottom)
    except Exception as e:
        print("读图失败：%s" % e, file=sys.stderr)
        return 2

    aw, ah, apx = crop_scale(wa, ha, pa, v[0], v[1], v[2], v[3], v[4])
    if len(v) == 5:
        bw, bh, bpx = crop_scale(wb, hb, pb, v[0], v[1], v[2], v[3], v[4])
    else:
        bw, bh, bpx = crop_scale(wb, hb, pb, v[5], v[6], v[7], v[8], v[9])

    W = max(aw, bw)
    gap = 6
    H = ah + gap + bh
    canvas = bytearray(b"\xff" * (W * H * 3))
    for j in range(ah):
        canvas[j * W * 3:j * W * 3 + aw * 3] = apx[j * aw * 3:(j + 1) * aw * 3]
    for j in range(gap):
        row = (ah + j) * W * 3
        canvas[row:row + W * 3] = b"\xcc\x00\x00" * W
    for j in range(bh):
        row = (ah + gap + j) * W * 3
        canvas[row:row + bw * 3] = bpx[j * bw * 3:(j + 1) * bw * 3]

    write_png(args.out, W, H, canvas)
    print("输出 %s  %dx%d（上=原图 %dx%d，下=重绘 %dx%d）" % (args.out, W, H, aw, ah, bw, bh))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
