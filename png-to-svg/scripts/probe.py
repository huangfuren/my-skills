"""全图几何报告：一条命令替代「为每张图手写一个探针脚本」。

用法：
    python probe.py 图.png [--colors 4] [--min-len 15] [--tol 45]
                              [--region x0,x1,y0,y1] [--json]

输出（按颜色分层）：
    水平线   y=中心  x=a..b  粗=n         ← 导线、电池极板、分隔线
    垂直线   x=中心  y=a..b  粗=n
    文字行   x=a..b  y=c..d  墨迹 WxH  建议字号 S
    图形块   x=a..b  y=c..d  墨迹 WxH     ← 椭圆、三角、字母等非直线墨迹，需目视

做法：先按颜色建掩膜，再逐行 / 逐列取连通色段，长度 >= min_len 的判为直线；
相邻行（列）且起止相近的合并成一条线；把这些线从掩膜里抹掉，
剩下的行投影聚类就是文字行与图形块。

两点必须知道：
1. 同色的水平长线挡不住——电池极板会被报成「水平线」，这是对的，别当成导线。
2. 报告只给坐标，不判断对错；对错要靠渲染回来跑 diffcheck。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pngx import bits_bytes, color_bits, color_stats, crop_bits, read_png


def _runs1d(b, min_len):
    """一维 0/1 bytes 上的连续 1 段，长度不足 min_len 丢弃。"""
    out = []
    pos = 0
    n = len(b)
    while True:
        i = b.find(1, pos)
        if i < 0:
            break
        j = b.find(0, i)
        if j < 0:
            j = n
        if j - i >= min_len:
            out.append((i, j - 1))
        pos = j
    return out


def _merge(rows, tol=4):
    """把相邻行上起止相近的段合并成一条线。rows = [(固定坐标, 起, 止)]。

    排序必须先按 (起, 止) 再按固定坐标：同一条 3px 粗线会在 3 个固定坐标上
    各出一条段，若按固定坐标排序，中途插进来的其他段会打断合并（实测会把
    一条 3px 线拆成三条 1px 线）。
    """
    rows = sorted(rows, key=lambda t: (t[1], t[0], t[2]))
    groups = []
    cur = None
    for f, a, b in rows:
        if cur and f == cur["f1"] + 1 and abs(a - cur["a"]) <= tol and abs(b - cur["b"]) <= tol:
            cur["f1"] = f
            cur["a"] = min(cur["a"], a)
            cur["b"] = max(cur["b"], b)
        else:
            if cur:
                groups.append(cur)
            cur = {"f0": f, "f1": f, "a": a, "b": b}
    if cur:
        groups.append(cur)
    groups.sort(key=lambda g: (g["f0"], g["a"]))
    return groups


def _col_segments(res, w, y0, y1, gap_min):
    """带内按列合并：同一行的多段文字要按横向间隙切开，不能并成一条。

    把所有行的 0/1 字节当作大整数按位或，一次得到列方向的「有无墨迹」，
    再按 gap_min 把相邻列段合并。
    """
    acc = 0
    for y in range(y0, y1 + 1):
        acc |= int.from_bytes(res[y * w:(y + 1) * w], "big")
    colbytes = acc.to_bytes(w, "big")
    segs = []
    for a, b in _runs1d(colbytes, 1):
        if segs and a - segs[-1][1] - 1 <= gap_min:
            segs[-1] = (segs[-1][0], b)
        else:
            segs.append((a, b))
    return segs


def _analyse(sub, w, h, min_len, gap_min=10, cjk_ratio=0.866):
    # 水平线
    hrows = []
    for y in range(h):
        for a, b in _runs1d(sub[y * w:(y + 1) * w], min_len):
            hrows.append((y, a, b))
    hlines = _merge(hrows)

    # 垂直线
    vrows = []
    for x in range(w):
        for a, b in _runs1d(sub[x::w], min_len):
            vrows.append((x, a, b))
    vlines = _merge(vrows)

    # 抹掉直线，剩残余
    res = bytearray(sub)
    for g in hlines:
        for y in range(g["f0"], g["f1"] + 1):
            base = y * w
            res[base + g["a"]:base + g["b"] + 1] = b"\x00" * (g["b"] - g["a"] + 1)
    for g in vlines:
        for x in range(g["f0"], g["f1"] + 1):
            for y in range(g["a"], g["b"] + 1):
                res[y * w + x] = 0

    # 残余行投影 → 行带
    bands = []
    cur = None
    for y in range(h):
        if res[y * w:(y + 1) * w].count(1):
            if cur is None:
                cur = [y, y]
            else:
                cur[1] = y
        else:
            if cur and y - cur[1] > 2:
                bands.append(tuple(cur))
                cur = None
    if cur:
        bands.append(tuple(cur))

    # 每个行带再按列间隙切开，逐段给 bbox
    items = []
    slivers = 0
    for by0, by1 in bands:
        for cx0, cx1 in _col_segments(res, w, by0, by1, gap_min):
            ys = [y for y in range(by0, by1 + 1)
                  if res[y * w + cx0:y * w + cx1 + 1].count(1)]
            if not ys:
                continue
            iy0, iy1 = ys[0], ys[-1]
            bw, bh = cx1 - cx0 + 1, iy1 - iy0 + 1
            # 细碎残段：没达到直线长度阈值、又窄得不像字或图形，单独计数不列坐标
            if (bw <= 2 and bh <= 18) or (bh <= 2 and bw <= 18):
                slivers += 1
                continue
            is_text = bh <= 26 and bw >= 20
            items.append({
                "x0": cx0, "x1": cx1, "y0": iy0, "y1": iy1,
                "w": bw, "h": bh,
                "kind": "text" if is_text else "shape",
                "font_size": round(bh / cjk_ratio, 1) if is_text else None,
            })

    return {"hlines": hlines, "vlines": vlines, "bands": items, "slivers": slivers}


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("image")
    ap.add_argument("--colors", type=int, default=4, help="取前 N 个主色分析，默认 4")
    ap.add_argument("--min-len", type=int, default=15, help="判为直线的最短长度，默认 15")
    ap.add_argument("--tol", type=int, default=45)
    ap.add_argument("--region", default=None, help="x0,x1,y0,y1，只分析该区域")
    ap.add_argument("--gap", type=int, default=10, help="同一行带内按横向间隙切分，默认 10px")
    ap.add_argument("--cjk-ratio", type=float, default=0.866,
                    help="中文墨迹高÷字号，默认 0.866；纯数字/字母文本约 0.72")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    w, h, px = read_png(args.image)
    pal = color_stats(px, w, h)[:max(1, args.colors)]

    if args.region:
        x0, x1, y0, y1 = [int(v) for v in args.region.split(",")]
    else:
        x0, x1, y0, y1 = 0, w, 0, h
    cw, ch = x1 - x0, y1 - y0

    report = {"size": [w, h], "region": [x0, x1, y0, y1], "layers": []}
    for r0, g0, b0, cnt in pal:
        bits = color_bits(px, w, h, (r0, g0, b0), args.tol)
        full = bits_bytes(bits, w * h)
        sub = crop_bits(full, w, x0, x1, y0, y1)
        res = _analyse(sub, cw, ch, args.min_len, args.gap, args.cjk_ratio)
        res["color"] = "#%02X%02X%02X" % (r0, g0, b0)
        res["px"] = sub.count(1)
        report["layers"].append(res)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("画布 %d x %d   分析区 x%d-%d y%d-%d" % (w, h, x0, x1, y0, y1))
    for L in report["layers"]:
        print("\n=== %s   本层 %d px" % (L["color"], L["px"]))
        for g in L["hlines"]:
            thick = g["f1"] - g["f0"] + 1
            print("  水平线  y=%d  x=%d..%d  粗%d"
                  % ((g["f0"] + g["f1"]) // 2 + y0, g["a"] + x0, g["b"] + x0, thick))
        for g in L["vlines"]:
            thick = g["f1"] - g["f0"] + 1
            print("  垂直线  x=%d  y=%d..%d  粗%d"
                  % ((g["f0"] + g["f1"]) // 2 + x0, g["a"] + y0, g["b"] + y0, thick))
        for b in L["bands"]:
            tag = "文字行" if b["kind"] == "text" else "图形块"
            extra = "  建议字号 %s" % b["font_size"] if b["kind"] == "text" else ""
            print("  %s  x=%d..%d  y=%d..%d  墨迹 %dx%d%s"
                  % (tag, b["x0"] + x0, b["x1"] + x0, b["y0"] + y0, b["y1"] + y0,
                     b["w"], b["h"], extra))
        if not (L["hlines"] or L["vlines"] or L["bands"]):
            print("  （该色在分析区内没有墨迹）")
        if L.get("slivers"):
            print("  （另有 %d 处细碎残段，短于 min-len 且窄于 3px，未列出；多为抗锯齿或短引线）"
                  % L["slivers"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
