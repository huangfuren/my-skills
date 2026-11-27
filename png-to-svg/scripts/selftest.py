"""自检：掩膜内核、拟合、像素读写、平移搜索的最小回归。

改动 pngx.py 或 align.py 后先跑这个。合成图形的期望值必须精确命中，
否则后续所有测量都不可信——历史上这里出过一次"漏除 2"，圆心坐标全部翻倍，
肉眼看测量结果却像模像样。

    python selftest.py
"""

import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pngx


def _canvas(w, h):
    return bytearray(b"\xff" * (w * h * 3))


def check_fit_circle():
    pts = [(100 + 50 * math.cos(t / 40.0), 100 + 50 * math.sin(t / 40.0)) for t in range(0, 252)]
    cx, cy, r = pngx.fit_circle(pts)
    ok = abs(cx - 100) < 0.01 and abs(cy - 100) < 0.01 and abs(r - 50) < 0.01
    print("%s 合成圆 → cx=%.2f cy=%.2f r=%.2f（期望 100.00 / 100.00 / 50.00）"
          % ("PASS" if ok else "FAIL", cx, cy, r))
    return ok


def check_png_roundtrip():
    w, h = 7, 5
    src = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 3
            src[i], src[i + 1], src[i + 2] = x * 30, y * 40, 128
    path = os.path.join(tempfile.gettempdir(), "_pngx_selftest.png")
    pngx.write_png(path, w, h, src)
    w2, h2, back = pngx.read_png(path)
    ok = (w, h) == (w2, h2) and bytes(back) == bytes(src)
    print("%s PNG 读写往返 7x5" % ("PASS" if ok else "FAIL"))
    os.remove(path)
    return ok


def check_runs():
    w, h = 10, 1
    px = _canvas(w, h)
    for x in (2, 3, 4, 7):
        i = x * 3
        px[i] = px[i + 1] = px[i + 2] = 0
    runs = pngx.row_runs(px, w, h, 0, pngx.near((0, 0, 0), 10))
    ok = runs == [(2, 4), (7, 7)]
    print("%s row_runs → %s（期望 [(2,4),(7,7)]）" % ("PASS" if ok else "FAIL", runs))
    return ok


def check_ink_bits():
    """掩膜必须与逐像素判定逐点一致，且外接框精确。"""
    w, h = 20, 10
    px = _canvas(w, h)
    for y in range(2, 6):
        for x in range(5, 8):
            i = (y * w + x) * 3
            px[i] = px[i + 1] = px[i + 2] = 0
    manual = sum(1 for y in range(h) for x in range(w)
                 if min(px[(y * w + x) * 3:(y * w + x) * 3 + 3]) <= 200)
    bits = pngx.ink_bits(px, w, h, 200)
    box = pngx.bits_bbox(pngx.bits_bytes(bits, w * h), w, h)
    ok = pngx.bits_count(bits) == manual == 12 and box == (5, 7, 2, 5)
    print("%s ink_bits 12px 实测 %d，外接框 %s（期望 (5,7,2,5)）"
          % ("PASS" if ok else "FAIL", pngx.bits_count(bits), box))
    return ok


def check_color_bits():
    """分色掩膜只能命中自己的颜色，不能串到相邻色。"""
    w, h = 30, 10
    px = _canvas(w, h)

    def fill(x0, x1, c):
        for y in range(2, 6):
            for x in range(x0, x1):
                i = (y * w + x) * 3
                px[i], px[i + 1], px[i + 2] = c

    fill(2, 8, (163, 73, 164))
    fill(15, 21, (63, 72, 204))
    a = pngx.bits_count(pngx.color_bits(px, w, h, (163, 73, 164), 45))
    b = pngx.bits_count(pngx.color_bits(px, w, h, (63, 72, 204), 45))
    ok = a == 24 and b == 24
    print("%s color_bits 紫 %d / 蓝 %d（各期望 24）" % ("PASS" if ok else "FAIL", a, b))
    return ok


def check_ellipse_axes():
    """合成椭圆：两轴必须分开，且被判为椭圆。"""
    w, h = 100, 90
    px = _canvas(w, h)
    cx, cy, rx, ry = 50.0, 45.0, 30.0, 24.0
    for y in range(h):
        for x in range(w):
            v = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            if 0.80 <= v <= 1.10:
                i = (y * w + x) * 3
                px[i], px[i + 1], px[i + 2] = 163, 73, 164
    bits = pngx.color_bits(px, w, h, (163, 73, 164), 30)
    r = pngx.ellipse_axes(pngx.bits_bytes(bits, w * h), w, 0, w, 0, h, min_span=1)
    ok = bool(r) and abs(r[0] - cx) < 1.5 and abs(r[1] - cy) < 1.5 \
        and abs(r[2] - rx) < 2 and abs(r[3] - ry) < 2 and r[4]
    print("%s 合成椭圆 → cx=%.1f cy=%.1f rx=%.1f ry=%.1f 椭圆=%s（期望 50/45/30/24 且为椭圆）"
          % ("PASS" if ok else "FAIL", r[0], r[1], r[2], r[3], r[4]) if r else "FAIL 合成椭圆无结果")
    return ok


def check_text_metrics():
    """已知 16px 高的字块必须反算出 18.5 号字，基线落在墨迹底边。"""
    w, h = 60, 40
    px = _canvas(w, h)
    for y in range(10, 26):
        for x in range(10, 50):
            i = (y * w + x) * 3
            px[i] = px[i + 1] = px[i + 2] = 0
    bits = pngx.color_bits(px, w, h, (0, 0, 0), 45)
    m = pngx.text_metrics(pngx.bits_bytes(bits, w * h), w, 0, w, 0, h)
    ok = m and m["w"] == 40 and m["h"] == 16 and abs(m["font_size"] - 18.5) < 0.1 \
        and m["baseline"] == 25
    print("%s text_metrics → %dx%d 字号 %s 基线 %s（期望 40x16 / 18.5 / 25）"
          % ("PASS" if ok else "FAIL", m["w"], m["h"], m["font_size"], m["baseline"]))
    return ok


def check_align():
    """把图形整体平移 (3,-2)，整数搜索必须原样找回 (-3,+2)。"""
    import align
    w, h = 64, 40
    a = bytearray(w * h)
    for y in range(8, 20):
        for x in range(10, 30):
            a[y * w + x] = 1
    b = bytearray(w * h)
    dx, dy = 3, -2
    for y in range(h):
        sy = y - dy
        if 0 <= sy < h:
            for x in range(w):
                sx = x - dx
                if 0 <= sx < w:
                    b[y * w + x] = a[sy * w + sx]
    base, (best, bdx, bdy) = align._scan_shifts(int.from_bytes(bytes(a), "big"),
                                               int.from_bytes(bytes(b), "big"), w, h, 5)
    ok = (bdx, bdy) == (-dx, -dy) and best > base
    print("%s align 搜索 → translate(%+d,%+d) 重合 %d→%d（期望 (-3,+2) 且提升）"
          % ("PASS" if ok else "FAIL", bdx, bdy, base, best))
    return ok


def check_components():
    """两个分离方块 + 一条细线 + 一对斜对角像素 → 必须切出 4 块。

    斜对角那两点是本项的关键：8 邻接下是 1 块，4 邻接下必须是 2 块。
    汉字笔画全靠斜对角相连，这一条错了会把每个字拆成七八块碎片。
    """
    w, h = 60, 40
    buf = bytearray(w * h)

    def rect(x0, y0, x1, y1):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                buf[y * w + x] = 1

    rect(2, 2, 10, 10)      # 81
    rect(20, 2, 30, 10)     # 99
    for x in range(5, 50):
        buf[20 * w + x] = 1  # 45 细长线
    buf[30 * w + 40] = 1
    buf[31 * w + 41] = 1    # 斜对角两点

    bb = bytes(buf)
    c8 = pngx.bits_components(bb, w, h)
    c4 = pngx.bits_components(bb, w, h, diag=False)
    big = pngx.bits_components(bb, w, h, min_area=90)
    ok = (len(c8) == 4 and len(c4) == 5 and len(big) == 1
          and c8[0][4] == 99 and big[0][4] == 99)
    print("%s bits_components → 8邻接 %d 块 / 4邻接 %d 块 / min_area=90 %d 块"
          "（期望 4 / 5 / 1）" % ("PASS" if ok else "FAIL", len(c8), len(c4), len(big)))
    return ok


def check_inventory():
    """原图两个块、重绘只有一个 → 必须判出 1 处「缺」，另 1 处「存」。"""
    import inventory
    w, h = 80, 40

    def canvas(blocks):
        img = bytearray(b"\xff" * (w * h * 3))
        for x0, y0, x1, y1 in blocks:
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    i = (y * w + x) * 3
                    img[i:i + 3] = b"\x00\x00\x00"
        return img

    src = canvas([(10, 10, 30, 30), (50, 10, 70, 30)])
    dst = canvas([(10, 10, 30, 30)])
    rows = inventory._audit(src, dst, (0, 0, 0), w, h, 45, 40, 0.35)
    verdicts = sorted(r[4] for r in rows)
    ok = verdicts == ["存", "缺"]
    print("%s inventory 清点 → %s（期望 [存, 缺]）"
          % ("PASS" if ok else "FAIL", verdicts))
    return ok


if __name__ == "__main__":
    results = [
        check_fit_circle(), check_png_roundtrip(), check_runs(),
        check_ink_bits(), check_color_bits(), check_ellipse_axes(),
        check_text_metrics(), check_align(),
        check_components(), check_inventory(),
    ]
    print("\n%d/%d 通过" % (sum(results), len(results)))
    raise SystemExit(0 if all(results) else 1)
