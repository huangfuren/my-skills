"""坐标网格叠加：让「第几格」代替「目测大概」。

用法：
    python grid.py 图.png 出.png                       # 整图，次格 50 / 主格 100
    python grid.py 图.png 出.png --step 20 --major 100
    python grid.py 图.png 出.png --region 780,1020,195,345 --scale 4

输出：次格青色虚线（--step），主格洋红实线（--major），
      左边缘与上边缘标出原图坐标数字。--scale 整体放大，便于看清。

为什么需要它：
    目测「大概在 x=800 附近」在 1353px 宽的图上等于放弃精度，
    而放大后的截图又失去了坐标感。叠网格是把两者接上：
    看到的每个元素都能直接读成坐标，再去 probe / blocks 精测。
    本次 MOS 图靠这个才发现「结构图外框左边界不在 780 而在 777」这类偏差。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngx import crop_scale, read_png, write_png

MINOR = (0, 180, 180)
MAJOR = (255, 0, 255)

_DIGITS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


def _put(buf, w, h, x, y, color):
    if 0 <= x < w and 0 <= y < h:
        i = (y * w + x) * 3
        buf[i:i + 3] = bytes(color)


def _dot_line(buf, w, h, x0, y0, x1, y1, color, dash):
    """Bresenham + 可选虚线（dash 为 0 时实线）。"""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    n = 0
    while True:
        if not dash or (n // dash) % 2 == 0:
            _put(buf, w, h, x0, y0, color)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
        n += 1


def _num(buf, w, h, x, y, text, scale, color):
    """3×5 点阵数字，scale 倍放大。返回占用宽度。"""
    cx = x
    for ch in text:
        glyph = _DIGITS.get(ch)
        if glyph:
            for ry, row in enumerate(glyph):
                for rx, v in enumerate(row):
                    if v == "1":
                        for a in range(scale):
                            for b in range(scale):
                                _put(buf, w, h, cx + rx * scale + a, y + ry * scale + b, color)
            cx += 4 * scale
        else:
            cx += 2 * scale
    return cx - x


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("image")
    ap.add_argument("out")
    ap.add_argument("--step", type=int, default=50, help="次格间距，默认 50")
    ap.add_argument("--major", type=int, default=100, help="主格间距，默认 100")
    ap.add_argument("--region", default=None, help="x0,x1,y0,y1")
    ap.add_argument("--scale", type=int, default=2, help="放大倍数，默认 2")
    ap.add_argument("--no-label", action="store_true", help="不画坐标数字")
    ap.add_argument("--force", action="store_true", help="允许覆盖已有输出")
    args = ap.parse_args()

    if os.path.exists(args.out) and not args.force:
        print("输出已存在：%s（要覆盖加 --force）" % args.out, file=sys.stderr)
        return 2

    w, h, px = read_png(args.image)
    x0, x1, y0, y1 = 0, w, 0, h
    if args.region:
        try:
            x0, x1, y0, y1 = [int(v) for v in args.region.split(",")]
        except ValueError:
            print("--region 要写成 x0,x1,y0,y1", file=sys.stderr)
            return 2
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
    cw, ch = x1 - x0, y1 - y0

    _, _, work = crop_scale(w, h, px, x0, y0, cw, ch, 1)
    buf = bytearray(work)
    step, major = max(1, args.step), max(1, args.major)

    for gx in range(((x0 + step - 1) // step) * step, x1 + 1, step):
        lx = gx - x0
        if 0 <= lx < cw:
            is_major = gx % major == 0
            _dot_line(buf, cw, ch, lx, 0, lx, ch - 1,
                      MAJOR if is_major else MINOR, 0 if is_major else 3)
    for gy in range(((y0 + step - 1) // step) * step, y1 + 1, step):
        ly = gy - y0
        if 0 <= ly < ch:
            is_major = gy % major == 0
            _dot_line(buf, cw, ch, 0, ly, cw - 1, ly,
                      MAJOR if is_major else MINOR, 0 if is_major else 3)

    if not args.no_label:
        s = 2
        for gx in range(((x0 + major - 1) // major) * major, x1 + 1, major):
            lx = gx - x0
            if 0 <= lx <= cw - 8 * s:
                _num(buf, cw, ch, lx + 1, 1, str(gx), s, MAJOR)
        for gy in range(((y0 + major - 1) // major) * major, y1 + 1, major):
            ly = gy - y0
            # 顶部留给 x 轴标签，否则左上角两串数字会叠在一起
            if 16 * s <= ly <= ch - 6 * s:
                _num(buf, cw, ch, 2, ly + 1, str(gy), s, MAJOR)

    if args.scale != 1:
        ow, oh, out = crop_scale(cw, ch, bytes(buf), 0, 0, cw, ch, args.scale)
    else:
        ow, oh, out = cw, ch, bytes(buf)
    write_png(args.out, ow, oh, out)
    print("写入 %s  %dx%d（区域 %d,%d-%d,%d，次格 %d，主格 %d，缩放 %dx）"
          % (args.out, ow, oh, x0, y0, x1, y1, step, major, args.scale))
    print("主格线标注的是原图坐标，可直接对应 probe.py 的输出。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
