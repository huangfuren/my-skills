"""像素差分：把渲染图和原图对齐比，量化重合率、定位差异热点、按颜色分层报账。

灰色 = 两图都有墨迹    红色 = 只有原图有    蓝色 = 只有重绘有

用法：
    python diffcheck.py 原图.png 渲染图.png [差异图.png] [选项]

    --block N       热点分块边长，默认 40
    --y-max N       只统计 y < N（新增的图例等应排除，否则稀释重合率）
    --th N          墨迹阈值，任一通道 <= N 视为墨迹，默认 200
    --top N         列出前 N 个热点块，默认 12
    --layers        按颜色分层报账（每层单独给召回率与多余率）
    --max-bad N     差异像素总数超过 N 则判失败，退出码 1
    --fail-block N  任一热点块的差异像素超过 N 则判失败，退出码 1
    --force         允许覆盖已存在的差异图
    --json          以 JSON 输出汇总，便于脚本调用

退出码：0 通过 / 1 未过阈值 / 2 输入或参数错误

判读方法：只看热点块，回到 pngx.bits_row_runs 去量那一块的坐标，改 SVG 后重跑。
重合率不是越高越好——中文笔画粗细、3px 线的抗锯齿半像素是必然残差，
主图区稳定在 60%~70% 说明几何已经对上，剩余差异应当散布而不是集中成块。

本轮改造：
- 单遍扫描 + int.bit_count，全图统计从数秒降到毫秒级（原实现扫三遍）。
- 差异图改用 translate 逐通道映射，不再逐像素写 RGB。
- --layers 来自「按颜色分层再比」的思路（visioncortex/vtracer、tomayac/SVGcode
  都是先按颜色分层再处理），但这里只借分层思想，比较仍在像素级完成。
- 阈值 + 退出码 + 覆盖保护的约定参考 syi0808/svg-skills 的 compare_render.py：
  比对结果要能当门禁用，而不只是打印一个数字。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngx import (color_bits, color_stats, ink_bits, read_png, write_png)


def _ones(n):
    return int.from_bytes(b"\x01" * n, "big")


def _trim(bits, w, h, W, H):
    """把 w×h 的掩膜裁成左上 W×H，用于两图尺寸不一致时对齐比较。"""
    if (w, h) == (W, H):
        return bits
    bb = bits.to_bytes(w * h, "big")
    out = bytearray()
    for y in range(H):
        out += bb[y * w:y * w + W]
    return int.from_bytes(bytes(out), "big")


def _diff_image(W, H, code_bytes):
    """0=空白 1=仅原图 2=仅重绘 3=两者都有 → RGB。"""
    def table(mapping):
        t = bytearray(range(256))
        for k, v in mapping.items():
            t[k] = v
        return bytes(t)

    r = table({0: 255, 1: 230, 2: 30, 3: 190})
    g = table({0: 255, 1: 30, 2: 90, 3: 190})
    b = table({0: 255, 1: 30, 2: 230, 3: 190})
    out = bytearray(W * H * 3)
    out[0::3] = code_bytes.translate(r)
    out[1::3] = code_bytes.translate(g)
    out[2::3] = code_bytes.translate(b)
    return out


def _pct(x, t):
    return 100.0 * x / t if t else 0.0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("a", help="原图")
    ap.add_argument("b", help="渲染图")
    ap.add_argument("out", nargs="?", help="差异图输出路径（省略则不出图）")
    ap.add_argument("--block", type=int, default=40)
    ap.add_argument("--y-max", type=int, default=None)
    ap.add_argument("--th", type=int, default=200)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--layers", action="store_true")
    ap.add_argument("--layer-colors", type=int, default=4,
                    help="分色层取前 N 个主色，默认 4。抗锯齿色排在后面，故意不取")
    ap.add_argument("--max-bad", type=int, default=None)
    ap.add_argument("--fail-block", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.out and os.path.exists(args.out) and not args.force:
        print("差异图已存在：%s\n加 --force 才覆盖（避免盖掉上一次的对照结果）" % args.out,
              file=sys.stderr)
        return 2
    try:
        wa, ha, pa = read_png(args.a)
        wb, hb, pb = read_png(args.b)
    except Exception as e:
        print("读图失败：%s" % e, file=sys.stderr)
        return 2

    W, H = min(wa, wb), min(ha, hb)
    if (wa, ha) != (wb, hb):
        print("尺寸不同：原图 %dx%d，渲染 %dx%d → 只比左上 %dx%d" % (wa, ha, wb, hb, W, H))

    a = _trim(ink_bits(pa, wa, ha, args.th), wa, ha, W, H)
    b = _trim(ink_bits(pb, wb, hb, args.th), wb, hb, W, H)
    n = W * H
    ones = _ones(n)

    both = (a & b).bit_count()
    only_a = (a & (ones - b)).bit_count()
    only_b = (b & (ones - a)).bit_count()
    tot = both + only_a + only_b
    bad = only_a + only_b

    if args.out:
        code = (a + 2 * b).to_bytes(n, "big")
        write_png(args.out, W, H, _diff_image(W, H, code))

    summary = {
        "size": [W, H],
        "both": both, "only_a": only_a, "only_b": only_b, "bad": bad,
        "overlap_pct": round(_pct(both, tot), 2),
    }

    if not args.json:
        print("全图：重合 %d (%.1f%%)  仅原图 %d (%.1f%%)  仅重绘 %d (%.1f%%)"
              % (both, _pct(both, tot), only_a, _pct(only_a, tot), only_b, _pct(only_b, tot)))

    # ---- 限定区域（排除图例等新增内容）
    if args.y_max:
        ym = min(args.y_max, H)
        ba = a.to_bytes(n, "big")
        bb = b.to_bytes(n, "big")
        sub_a = int.from_bytes(bytes(ba[:ym * W]), "big")
        sub_b = int.from_bytes(bytes(bb[:ym * W]), "big")
        sub_ones = _ones(ym * W)
        b2 = (sub_a & sub_b).bit_count()
        oa2 = (sub_a & (sub_ones - sub_b)).bit_count()
        ob2 = (sub_b & (sub_ones - sub_a)).bit_count()
        t2 = b2 + oa2 + ob2
        summary["y_max"] = {
            "y": ym, "overlap_pct": round(_pct(b2, t2), 2),
            "only_a": oa2, "only_b": ob2,
        }
        if not args.json:
            print("y<%d：重合 %.1f%%  仅原图 %.1f%%  仅重绘 %.1f%%"
                  % (ym, _pct(b2, t2), _pct(oa2, t2), _pct(ob2, t2)))

    # ---- 热点块
    blk = max(4, args.block)
    ba = a.to_bytes(n, "big")
    bb = b.to_bytes(n, "big")
    oa_bytes = (a & (ones - b)).to_bytes(n, "big")
    ob_bytes = (b & (ones - a)).to_bytes(n, "big")

    blocks = []
    for by in range(0, H, blk):
        y1 = min(by + blk, H)
        rows = range(by, y1)
        for bx in range(0, W, blk):
            x1 = min(bx + blk, W)
            ca = cb = 0
            for y in rows:
                base = y * W
                ca += oa_bytes[base + bx:base + x1].count(1)
                cb += ob_bytes[base + bx:base + x1].count(1)
            if ca or cb:
                blocks.append((ca + cb, bx, by, ca, cb))
    blocks.sort(reverse=True)

    summary["blocks"] = [
        {"x": bx, "y": by, "only_a": ca, "only_b": cb, "total": t}
        for t, bx, by, ca, cb in blocks[:args.top]
    ]
    worst = blocks[0][0] if blocks else 0
    summary["worst_block"] = worst

    if not args.json:
        print("\n差异热点（先看这些，其余忽略）:")
        for t, bx, by, ca, cb in blocks[:args.top]:
            print("  x=%4d-%4d y=%3d-%3d  仅原图=%4d 仅重绘=%4d"
                  % (bx, bx + blk, by, by + blk, ca, cb))
        if not blocks:
            print("  无差异块")

    # ---- 分色层报账
    if args.layers:
        layers = []
        pal = color_stats(pa, wa, ha)[:max(1, args.layer_colors)]
        for r0, g0, b0, cnt in pal:
            la = _trim(color_bits(pa, wa, ha, (r0, g0, b0), 45), wa, ha, W, H)
            lb = _trim(color_bits(pb, wb, hb, (r0, g0, b0), 45), wb, hb, W, H)
            na, nb = la.bit_count(), lb.bit_count()
            inter = (la & lb).bit_count()
            layers.append({
                "color": "#%02X%02X%02X" % (r0, g0, b0),
                "src_px": na, "out_px": nb,
                "recall_pct": round(_pct(inter, na), 1),
                "extra_pct": round(_pct(nb - inter, nb), 1),
            })
        summary["layers"] = layers
        if not args.json:
            print("\n分色层（召回＝原图该色被覆盖的比例；多余＝重绘多画的比例）:")
            for L in layers:
                print("  %s 原图%6d 重绘%6d  召回%5.1f%%  多余%5.1f%%"
                      % (L["color"], L["src_px"], L["out_px"],
                         L["recall_pct"], L["extra_pct"]))

    # ---- 门禁
    failed = []
    if args.max_bad is not None and bad > args.max_bad:
        failed.append("差异像素 %d > 阈值 %d" % (bad, args.max_bad))
    if args.fail_block is not None and worst > args.fail_block:
        failed.append("最大热点块 %d > 阈值 %d" % (worst, args.fail_block))
    summary["passed"] = not failed
    if failed:
        summary["failures"] = failed

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif failed:
        print("\n未过门禁：" + "；".join(failed))

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
