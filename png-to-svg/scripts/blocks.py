"""元素清单：这一色到底有几个独立部件，各自在哪。

用法：
    python blocks.py 图.png                          # 前 4 色各列 top 5 块
    python blocks.py 图.png --color A349A4           # 单色，列全部块
    python blocks.py 图.png --color 000000 --region 620,1030,60,200 --min-area 50
    python blocks.py 图.png --json

为什么需要它：
    probe.py 给的是「线 / 文字行 / 图形块」的投影视图，适合量尺寸；
    但回答不了「这里有 3 个还是 4 个独立部件」「那个端子圆到底在哪个坐标」。
    本次 MOS 图（1353×554，164 个元素）就是靠连通块把 6 个端子圆、
    2 个二极管、2 个 N 型框一次性定位的——比逐个裁图目测快得多。

判断口径：
    连通按 8 邻接（斜对角算相连）。关掉会把一个汉字拆成七八块碎片。
    min_area 按**像素数**算，不按 bbox 面积：3px×200px 的细线有 600 像素不会被滤，
    而 20×20 的抗锯齿噪点只有零星几十像素，会被滤掉。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngx import (bits_bytes, bits_components, color_bits, color_stats,
                  crop_bits, read_png)


def _hex(ref):
    return "#%02X%02X%02X" % ref


def _rows(comps, x_off, y_off, limit):
    out = []
    for i, (minx, maxx, miny, maxy, area) in enumerate(comps[:limit], 1):
        out.append({
            "no": i,
            "bbox": [minx + x_off, miny + y_off, maxx + x_off, maxy + y_off],
            "w": maxx - minx + 1,
            "h": maxy - miny + 1,
            "area": area,
        })
    return out


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("image")
    ap.add_argument("--color", default=None,
                    help="RRGGBB，只列该色；不给则遍历前 N 个主色")
    ap.add_argument("--colors", type=int, default=4, help="不给 --color 时取前 N 色，默认 4")
    ap.add_argument("--tol", type=int, default=45)
    ap.add_argument("--region", default=None, help="x0,x1,y0,y1，只分析该区域")
    ap.add_argument("--min-area", type=int, default=30, help="最小像素数，默认 30")
    ap.add_argument("--top", type=int, default=None,
                    help="每色只列前 N 块；不给 --color 时默认 5，给了 --color 时默认全列")
    ap.add_argument("--diag", dest="diag", action="store_true", default=True,
                    help="8 邻接连通（默认开）")
    ap.add_argument("--no-diag", dest="diag", action="store_false",
                    help="4 邻接连通，会把汉字拆碎，一般不用")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

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

    if args.color:
        targets = [tuple(int(args.color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))]
        limit = args.top if args.top else 10 ** 6
    else:
        targets = [t[:3] for t in color_stats(px, w, h, min_count=50)[:args.colors]]
        # 全图概览只列代表块；单色模式才需要看全
        limit = args.top if args.top else 5

    result = {"image": args.image, "size": [w, h],
              "region": [x0, x1, y0, y1], "colors": []}

    for ref in targets:
        bits = color_bits(px, w, h, ref, tol=args.tol)
        bb = bits_bytes(bits, w * h)
        if (x0, x1, y0, y1) != (0, w, 0, h):
            sub = crop_bits(bb, w, x0, x1, y0, y1)
            comps = bits_components(sub, x1 - x0, y1 - y0,
                                    min_area=args.min_area, diag=args.diag)
        else:
            comps = bits_components(bb, w, h, min_area=args.min_area, diag=args.diag)
        rows = _rows(comps, x0, y0, limit)
        result["colors"].append({"color": _hex(ref), "count": len(comps), "blocks": rows})

        if not args.json:
            print("=== %s  共 %d 块（min-area %d）===" % (_hex(ref), len(comps), args.min_area))
            print("  #  %-26s %-12s %s" % ("bbox x0,y0,x1,y1", "宽×高", "像素"))
            for r in rows:
                print("  %-2d %-26s %-12s %d" % (
                    r["no"], ",".join(str(v) for v in r["bbox"]),
                    "%d×%d" % (r["w"], r["h"]), r["area"]))
            if len(comps) > len(rows):
                print("  ... 另有 %d 块未列出（--top %d 加 --top 0 可全列）"
                      % (len(comps) - len(rows), args.top))
            print()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
