"""元素清点对比：重绘图到底少画了什么。

用法：
    python inventory.py 原图.png 渲染.png
    python inventory.py 原图.png 渲染.png --colors 6 --min-area 40
    python inventory.py 原图.png 渲染.png --color A349A4
    python inventory.py 原图.png 渲染.png --extra        # 反向：重绘多画了什么
    python inventory.py 原图.png 渲染.png --json

为什么需要它：
    diffcheck 回答的是「差了多少像素」，回答不了「哪个元素根本没画」。
    本次 MOS 图的真实事故：漏掉整行「电子移动方向」，diff 只报
    「某 40×40 块仅原图多 427 像素」。看着像字号问题，实际是元素缺失，
    为此来回试了三轮字号才找到根因。本工具把这类问题变成一行输出。

判据（两个指标，宁可少报不误报）：
    cover = bbox 内与原图墨迹真正重合的像素 ÷ 该块像素数
    hit   = 块中心 ±3px 邻域里有没有重绘的同色像素

    缺   cover < 0.05 且 hit 无   → 这个元素没画
    残   cover < 0.35            → 画了，但严重偏位或漏笔画
    存   cover >= 0.35           → 认为在

    为什么 cover 用「与原图掩膜求交」而不是「bbox 内命中数」：
    后者会把紧邻的其他元素算进来，导致漏报。求交后数字才有意义。
    文字层 cover 普遍只有 0.4~0.7（字形差异），所以阈值不能设高。

    --extra 反向检查时同一套口径，只是把原图与重绘图对调。
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


def _audit(src, dst, ref, w, h, tol, min_area, cover_th=0.35):
    """src 的每块在 dst 里的存续情况。返回 [(bbox, area, cover, hit, verdict)]。"""
    s_bits = color_bits(src, w, h, ref, tol=tol)
    d_bits = color_bits(dst, w, h, ref, tol=tol)
    s_bb = bits_bytes(s_bits, w * h)
    d_bb = bits_bytes(d_bits, w * h)
    inter = bits_bytes(s_bits & d_bits, w * h)

    out = []
    for minx, maxx, miny, maxy, area in bits_components(s_bb, w, h, min_area=min_area):
        sub = crop_bits(inter, w, minx, maxx + 1, miny, maxy + 1)
        cover = min(1.0, sub.count(1) / float(area))

        cx, cy = (minx + maxx) // 2, (miny + maxy) // 2
        hit = False
        for y in range(max(0, cy - 3), min(h, cy + 4)):
            base = y * w
            for x in range(max(0, cx - 3), min(w, cx + 4)):
                if d_bb[base + x]:
                    hit = True
                    break
            if hit:
                break

        # 大面积块 cover<0.05 即判缺；小笔画（括号、竖笔）在字形差异下
        # 天然只有 0.03~0.05，必须等它彻底为 0 才算数
        if cover == 0.0 or (cover < 0.05 and area >= 150):
            verdict = "缺"
        elif cover < cover_th:
            verdict = "残"
        else:
            verdict = "存"
        out.append(((minx, miny, maxx, maxy), area, cover, hit, verdict))
    return out


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("original")
    ap.add_argument("rendered")
    ap.add_argument("--color", default=None, help="RRGGBB，只查该色；不给则遍历前 N 主色")
    ap.add_argument("--colors", type=int, default=5)
    ap.add_argument("--tol", type=int, default=45)
    ap.add_argument("--min-area", type=int, default=40, help="小于此像素数的块不查，默认 40")
    ap.add_argument("--cover", type=float, default=0.35, help="低于此覆盖率判残缺，默认 0.35")
    ap.add_argument("--strict", action="store_true",
                    help="连「残」一起报。文字层天然 0.2~0.3，开了会很吵，只在查特定元素时用")
    ap.add_argument("--extra", action="store_true", help="反向：查重绘图多画了什么")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    w, h, px = read_png(args.original)
    w2, h2, px2 = read_png(args.rendered)
    if (w, h) != (w2, h2):
        print("尺寸不一致：原图 %dx%d，渲染 %dx%d —— 必须先按原图宽度重渲"
              % (w, h, w2, h2), file=sys.stderr)
        return 2

    src, dst = (px2, px) if args.extra else (px, px2)
    src_name, dst_name = (("重绘", "原图") if args.extra else ("原图", "重绘"))

    if args.color:
        targets = [tuple(int(args.color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))]
    else:
        targets = [t[:3] for t in color_stats(px, w, h, min_count=50)[:args.colors]]

    report = {"original": args.original, "rendered": args.rendered,
              "size": [w, h], "colors": []}
    total_bad = 0

    for ref in targets:
        rows = _audit(src, dst, ref, w, h, args.tol, args.min_area, args.cover)
        bad = [r for r in rows if r[4] == "缺" or (args.strict and r[4] == "残")]
        total_bad += len(bad)
        report["colors"].append({
            "color": _hex(ref),
            "blocks": len(rows),
            "suspect": [
                {"bbox": list(r[0]), "area": r[1], "cover": round(r[2], 2),
                 "center_hit": r[3], "verdict": r[4]} for r in bad
            ],
        })

        if args.json:
            continue
        head = "=== %s  %s %d 块" % (_hex(ref), src_name, len(rows))
        if bad:
            print(head + "，其中 %d 块在%s里对不上 ===" % (len(bad), dst_name))
            print("  判定  %-24s %-8s %-6s %s" % ("bbox x0,y0,x1,y1", "像素", "覆盖", "中心"))
            for bbox, area, cover, hit, verdict in bad:
                print("  %-4s  %-24s %-8d %-6.2f %s" % (
                    verdict, ",".join(str(v) for v in bbox), area, cover,
                    "有" if hit else "无"))
        else:
            print(head + "，全部对得上 ===")

    if total_bad:
        print("\n合计 %d 处对不上。判定为「缺」的是没画；「残」的是位置或笔画严重偏。"
              % total_bad)
        print("先补元素，再调坐标与字号 —— 顺序反了会白试很多轮。")
    else:
        print("\n元素清点通过：没有漏画的块。")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
