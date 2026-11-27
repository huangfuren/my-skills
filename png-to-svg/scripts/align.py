"""亚像素偏移估计：告诉你是整体平移、还是横向/纵向缩放不一致。

原理：把两图分别投影成「每行墨迹数」和「每列墨迹数」两条一维曲线，
在 ±N 像素内滑动求互相关，峰值位置就是偏移；再对峰值左右三点做抛物线插值，
得到 0.1px 量级的亚像素偏移。整图只扫一遍掩膜，比逐像素搜索快几个数量级。

用法：
    python align.py 原图.png 渲染图.png [--radius 8] [--th 200] [--y-max 480] [--json]

输出（以「渲染图相对原图的位置」为准，正值＝渲染图偏右下）：
    整体 dx dy        → 建议给全图加 transform="translate(-dx,-dy)"
    上半 dy / 下半 dy → 两者符号相反说明纵向缩放不一致
    左半 dx / 右半 dx → 两者符号相反说明横向缩放不一致

注意：整图 translate 会把已经对齐的元素一起带偏。
本工具的价值是**判断偏差性质**，不是无脑平移；改完必须重跑 diffcheck。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngx import ink_bits, read_png


def _trim_bytes(bits, w, h, W, H):
    """掩膜 → 左上 W×H 的 bytes（两图尺寸不一致时对齐比较用）。"""
    bb = bits.to_bytes(w * h, "big")
    if (w, h) == (W, H):
        return bb
    out = bytearray()
    for y in range(H):
        out += bb[y * w:y * w + W]
    return bytes(out)


def _row_profile(bb, W, H, y0, y1):
    return [bb[y * W:(y + 1) * W].count(1) for y in range(y0, y1)]


def _col_profile(bb, W, H, x0, x1, y0, y1):
    """列投影。整列切片 [x::W] 是 C 层操作，再 count 也是 C 层。"""
    out = []
    for x in range(x0, x1):
        seg = bb[x + y0 * W:x + y1 * W:W]
        out.append(seg.count(1))
    return out


def _score(pa, pb, d):
    """pa[i] 与 pb[i+d] 的重叠区点积，除以重叠长度消除边界效应。"""
    n = len(pa)
    if d >= 0:
        i0, i1 = 0, n - d
    else:
        i0, i1 = -d, n
    if i1 <= i0:
        return 0.0
    s = 0
    for i in range(i0, i1):
        s += pa[i] * pb[i + d]
    return s / float(i1 - i0)


def _shift(pa, pb, radius):
    """返回 (偏移, 峰值相关, 次峰比)。偏移为正＝pb 的内容在坐标更大处。"""
    best_d, best_s = 0, -1.0
    scores = {}
    for d in range(-radius, radius + 1):
        s = _score(pa, pb, d)
        scores[d] = s
        if s > best_s:
            best_d, best_s = d, s
    # 抛物线插值求亚像素
    sub = 0.0
    if -radius < best_d < radius:
        s0, s1, s2 = scores[best_d - 1], scores[best_d], scores[best_d + 1]
        den = s0 - 2 * s1 + s2
        if abs(den) > 1e-9:
            sub = 0.5 * (s0 - s2) / den
            sub = max(-0.5, min(0.5, sub))
    return best_d + sub, best_s


def _shift_bits(w, h, bb, dx, dy):
    """把掩膜整体平移 (dx,dy) 后的新掩膜（越界裁掉）。"""
    out = bytearray(w * h)
    for y in range(h):
        sy = y - dy
        if sy < 0 or sy >= h:
            continue
        row = bb[sy * w:sy * w + w]
        x0 = max(0, dx)
        x1 = min(w, w + dx)
        if x1 > x0:
            out[y * w + x0:y * w + x1] = row[x0 - dx:x1 - dx]
    return int.from_bytes(bytes(out), "big")


def _scan_shifts(a, b, W, H, radius):
    """直接按「平移后重合多少像素」搜索整数平移。

    相关性估计给的是质心偏移，但质心对齐不等于像素重合最大：
    亚像素平移会把原本落在整像素上的笔画摊到两个像素，重合反而下降。
    所以最终建议以本函数的实测为准。
    """
    best = None
    base = (a & b).bit_count()
    bb = b.to_bytes(W * H, "big")
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                ov = base
            else:
                ov = (a & _shift_bits(W, H, bb, dx, dy)).bit_count()
            if best is None or ov > best[0]:
                best = (ov, dx, dy)
    return base, best


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("a", help="原图")
    ap.add_argument("b", help="渲染图")
    ap.add_argument("--radius", type=int, default=8)
    ap.add_argument("--th", type=int, default=200)
    ap.add_argument("--y-max", type=int, default=None, help="只统计 y<N（排除新增图例）")
    ap.add_argument("--no-scan", action="store_true", help="跳过整数平移实测搜索")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        wa, ha, pa = read_png(args.a)
        wb, hb, pb = read_png(args.b)
    except Exception as e:
        print("读图失败：%s" % e, file=sys.stderr)
        return 2

    W, H = min(wa, wb), min(ha, hb)
    if args.y_max:
        H = min(H, args.y_max)
    if (wa, ha) != (wb, hb):
        print("尺寸不同：原图 %dx%d，渲染 %dx%d → 只比左上 %dx%d" % (wa, ha, wb, hb, W, H))

    A = _trim_bytes(ink_bits(pa, wa, ha, args.th), wa, ha, W, H)
    B = _trim_bytes(ink_bits(pb, wb, hb, args.th), wb, hb, W, H)

    r = args.radius
    out = {}

    row_a = _row_profile(A, W, H, 0, H)
    row_b = _row_profile(B, W, H, 0, H)
    dy, _ = _shift(row_a, row_b, r)

    col_a = _col_profile(A, W, H, 0, W, 0, H)
    col_b = _col_profile(B, W, H, 0, W, 0, H)
    dx, _ = _shift(col_a, col_b, r)
    out["global"] = {"dx": round(dx, 2), "dy": round(dy, 2)}

    # 分区：上半/下半各测 dy，左半/右半各测 dx
    half = H // 2
    dy_top, _ = _shift(_row_profile(A, W, H, 0, half), _row_profile(B, W, H, 0, half), r)
    dy_bot, _ = _shift(_row_profile(A, W, H, half, H), _row_profile(B, W, H, half, H), r)
    out["dy_top"] = round(dy_top, 2)
    out["dy_bottom"] = round(dy_bot, 2)

    halfw = W // 2
    dx_l, _ = _shift(_col_profile(A, W, H, 0, halfw, 0, H),
                     _col_profile(B, W, H, 0, halfw, 0, H), r)
    dx_r, _ = _shift(_col_profile(A, W, H, halfw, W, 0, H),
                     _col_profile(B, W, H, halfw, W, 0, H), r)
    out["dx_left"] = round(dx_l, 2)
    out["dx_right"] = round(dx_r, 2)

    # 整数平移实测：以「平移后多重合多少像素」为准
    scan = None
    if not args.no_scan:
        base, (best_ov, bdx, bdy) = _scan_shifts(int.from_bytes(A, "big"),
                                                 int.from_bytes(B, "big"), W, H, 3)
        scan = {"base_overlap": base, "best_overlap": best_ov,
                "best_dx": bdx, "best_dy": bdy, "gain_px": best_ov - base}
        out["scan"] = scan

    advice = []
    if scan is not None:
        if scan["gain_px"] <= 0:
            advice.append("整数平移实测：任何平移都不会提高重合 → 不要动位置，余下差异来自抗锯齿与笔画粗细")
        else:
            advice.append("整数平移实测：translate(%+d,%+d) 可多重合 %d 像素（+%.1f%%），改完重跑 diffcheck"
                          % (scan["best_dx"], scan["best_dy"], scan["gain_px"],
                             100.0 * scan["gain_px"] / max(1, scan["base_overlap"])))
    if abs(dx) >= 0.25 or abs(dy) >= 0.25:
        advice.append("质心偏移 dx=%+.2f dy=%+.2f → 线宽在栅格上有系统偏置（3px 线画在整像素上常见）；"
                      "但质心对齐不等于重合最大，以上面实测为准" % (dx, dy))
    if abs(dx_l - dx_r) > 0.5:
        advice.append("左右 dx 相差 %.2fpx → 横向缩放或宽度不一致，不要用整图平移掩盖" % (dx_l - dx_r))
    if abs(dy_top - dy_bot) > 0.5:
        advice.append("上下 dy 相差 %.2fpx → 纵向缩放或高度不一致" % (dy_top - dy_bot))
    out["advice"] = advice
    out["passed"] = (scan["gain_px"] <= 0) if scan else (abs(dx) < 0.25 and abs(dy) < 0.25)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("整体        dx=%+.2f  dy=%+.2f" % (dx, dy))
        print("纵向分区   上 %+.2f  下 %+.2f" % (dy_top, dy_bot))
        print("横向分区   左 %+.2f  右 %+.2f" % (dx_l, dx_r))
        print()
        for a in advice:
            print("· " + a)
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
