"""位图还原测量基础库。纯标准库（zlib / struct），不依赖 PIL。

由来：原先是散在 F:\\tmp 下 22 个一次性探针里的代码。
- read_png / write_png / crop_scale：来自 pngcrop.py 与 compare.py，取 compare.py 版（多处理了 alpha、灰度+alpha、调色板 tRNS，并做白底合成）。
- fit_circle：来自 circ.py（Kasa 最小二乘拟圆）。
- color_stats / row_runs / col_runs / bbox / near：把 19 个探针里反复出现的 5 行循环抽成函数，判定逻辑未改。
- ink_bits / color_bits 及配套 bits_* ：第二轮优化加入。思路参考 visioncortex/vtracer 与
  tomayac/SVGcode 都把「按颜色分层」放在转换前完成，但这里只借这个分层思想，
  实现改用 bytes.translate + int 位运算，把整图掩膜从秒级降到毫秒级（见各函数注释）。

约定：像素永远是 RGB 三元组扁平字节串，下标 (y*w+x)*3。
pred 是 (r, g, b) -> bool 的可调用对象，用 near() 快速造。
新代码优先用掩膜接口（ink_bits / color_bits）：它快一个数量级，且能直接拿 int.bit_count 统计。
"""

import struct
import zlib

__all__ = [
    "read_png", "write_png", "crop_scale", "fit_circle",
    "near", "color_stats", "row_runs", "col_runs", "bbox", "outline_points",
    "ink_bits", "color_bits", "bits_bytes", "bits_count", "bits_bbox",
    "bits_row_runs", "crop_bits", "ellipse_axes", "text_metrics",
]


# ---------------------------------------------------------------- 读写

def read_png(path):
    """解 PNG → (w, h, rgb)。只支持 8bit 非隔行；alpha 与白底合成。"""
    d = open(path, "rb").read()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", "not png: " + path
    i = 8
    idat = b""
    plte = None
    trns = None
    w = h = bd = ct = None
    while i < len(d):
        ln = struct.unpack(">I", d[i:i + 4])[0]
        typ = d[i + 4:i + 8]
        data = d[i + 8:i + 8 + ln]
        if typ == b"IHDR":
            w, h, bd, ct, comp, filt, inter = struct.unpack(">IIBBBBB", data)
            assert bd == 8 and inter == 0, "only 8bit non-interlaced"
        elif typ == b"PLTE":
            plte = data
        elif typ == b"tRNS":
            trns = data
        elif typ == b"IDAT":
            idat += data
        elif typ == b"IEND":
            break
        i += 12 + ln
    raw = zlib.decompress(idat)
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    stride = w * ch
    out = bytearray(h * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        f = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if f == 1:
            for x in range(ch, stride):
                line[x] = (line[x] + line[x - ch]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                c = prev[x - ch] if x >= ch else 0
                b = prev[x]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line

    rgb = bytearray(w * h * 3)
    for y in range(h):
        row = y * stride
        for x in range(w):
            if ct == 2:
                r, g, b = out[row + x * 3], out[row + x * 3 + 1], out[row + x * 3 + 2]
            elif ct == 6:
                r, g, b, a = out[row + x * 4], out[row + x * 4 + 1], out[row + x * 4 + 2], out[row + x * 4 + 3]
                if a != 255:
                    r = (r * a + 255 * (255 - a)) // 255
                    g = (g * a + 255 * (255 - a)) // 255
                    b = (b * a + 255 * (255 - a)) // 255
            elif ct == 0:
                r = g = b = out[row + x]
            elif ct == 4:
                v, a = out[row + x * 2], out[row + x * 2 + 1]
                r = g = b = (v * a + 255 * (255 - a)) // 255
            else:
                idx = out[row + x]
                r, g, b = plte[idx * 3], plte[idx * 3 + 1], plte[idx * 3 + 2]
                if trns and idx < len(trns) and trns[idx] != 255:
                    a = trns[idx]
                    r = (r * a + 255 * (255 - a)) // 255
                    g = (g * a + 255 * (255 - a)) // 255
                    b = (b * a + 255 * (255 - a)) // 255
            t = (y * w + x) * 3
            rgb[t] = r
            rgb[t + 1] = g
            rgb[t + 2] = b
    return w, h, rgb


def write_png(path, w, h, rgb):
    """RGB 扁平字节串 → PNG（8bit truecolor，无 alpha）。"""
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    open(path, "wb").write(png)


def crop_scale(w, h, rgb, x0, y0, cw, ch, s):
    """裁 (x0,y0,cw,ch) 并整数倍放大 s 倍，返回 (ow, oh, out)。越界补白。"""
    ow, oh = cw * s, ch * s
    out = bytearray(b"\xff" * (ow * oh * 3))
    for j in range(oh):
        sy = y0 + j // s
        if sy < 0 or sy >= h:
            continue
        for i in range(ow):
            sx = x0 + i // s
            if sx < 0 or sx >= w:
                continue
            si = (sy * w + sx) * 3
            di = (j * ow + i) * 3
            out[di:di + 3] = rgb[si:si + 3]
    return ow, oh, out


# ---------------------------------------------------------------- 判定

def near(ref, tol=40):
    """造一个颜色判定函数：三通道各自相差不超过 tol。"""
    rr, rg, rb = ref

    def pred(r, g, b):
        return abs(r - rr) <= tol and abs(g - rg) <= tol and abs(b - rb) <= tol

    return pred


def color_stats(px, w, h, min_count=20, white=245):
    """非白像素的颜色直方图，按出现次数降序。返回 [(r,g,b,count)]。

    用途：定精确色值。不要靠眼看，取众数。
    """
    tally = {}
    for i in range(0, w * h * 3, 3):
        r, g, b = px[i], px[i + 1], px[i + 2]
        if r >= white and g >= white and b >= white:
            continue
        key = (r, g, b)
        tally[key] = tally.get(key, 0) + 1
    items = [(k[0], k[1], k[2], v) for k, v in tally.items() if v >= min_count]
    items.sort(key=lambda t: -t[3])
    return items


# ---------------------------------------------------------------- 扫描

def row_runs(px, w, h, y, pred, x0=0, x1=None):
    """某一行的连续命中色段，返回 [(start, end)]，闭区间。

    这是所有几何测量的基本操作：线的起止、缺口位置、文字墨迹宽度。
    """
    if x1 is None:
        x1 = w
    if y < 0 or y >= h:
        return []
    out = []
    x = x0
    while x < x1:
        i = (y * w + x) * 3
        if pred(px[i], px[i + 1], px[i + 2]):
            s = x
            while x < x1:
                i = (y * w + x) * 3
                if not pred(px[i], px[i + 1], px[i + 2]):
                    break
                x += 1
            out.append((s, x - 1))
        else:
            x += 1
    return out


def col_runs(px, w, h, x, pred, y0=0, y1=None):
    """某一列的连续命中色段，返回 [(start, end)]，闭区间。用于量线宽、引线长度。"""
    if y1 is None:
        y1 = h
    if x < 0 or x >= w:
        return []
    out = []
    y = y0
    while y < y1:
        i = (y * w + x) * 3
        if pred(px[i], px[i + 1], px[i + 2]):
            s = y
            while y < y1:
                i = (y * w + x) * 3
                if not pred(px[i], px[i + 1], px[i + 2]):
                    break
                y += 1
            out.append((s, y - 1))
        else:
            y += 1
    return out


def bbox(px, w, h, x0, x1, y0, y1, pred):
    """区域内命中像素的外接框，返回 (minx, maxx, miny, maxy)；空则 None。

    量文字墨迹框、椭圆外接框都用它。注意排除引线列，否则会把线算进去。
    """
    minx = miny = 1 << 30
    maxx = maxy = -1
    for y in range(max(0, y0), min(h, y1)):
        base = y * w
        for x in range(max(0, x0), min(w, x1)):
            i = (base + x) * 3
            if pred(px[i], px[i + 1], px[i + 2]):
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
    if maxx < 0:
        return None
    return minx, maxx, miny, maxy


# ---------------------------------------------------------------- 拟合

def outline_points(px, w, h, x0, x1, y0, y1, pred, min_hits=6, min_span=8):
    """逐行取最左 / 最右命中像素，返回轮廓点（只保留像"轮廓"的行）。

    拟圆/椭圆**只能**用这个，不能把区域内全部命中点丢给 fit_circle：
    圆内若有文字、引线，那些点会把拟合拉退化（实测出现过 r=889 的荒谬结果）。

    min_hits / min_span 用来剔除穿过区域的导线：一根 3px 竖线在某行只贡献 3 个像素、
    跨度 3，会被跳过；椭圆轮廓行跨度动辄几十像素，不受影响。
    代价是椭圆正切处的极窄行也会被跳过，所以横向/纵向**精确外接框要用 bbox 另量**。
    """
    pts = []
    for y in range(max(0, y0), min(h, y1)):
        base = y * w
        left = right = None
        hits = 0
        for x in range(max(0, x0), min(w, x1)):
            i = (base + x) * 3
            if pred(px[i], px[i + 1], px[i + 2]):
                hits += 1
                if left is None:
                    left = x
                right = x
        if left is None or hits < min_hits or (right - left) < min_span:
            continue
        pts.append((left, y))
        if right != left:
            pts.append((right, y))
    return pts


def fit_circle(points):
    """Kasa 最小二乘拟圆：解 x²+y² = 2a·x + 2b·y + c，返回 (cx, cy, r)。

    用它可以马上判断"看着像圆"的东西到底是圆还是椭圆：
    再对同一批点分别取 x/y 跨度，两值差超过 2px 就是椭圆，必须用 <ellipse> 两轴分开写。
    """
    n = len(points)
    if n < 3:
        raise ValueError("need at least 3 points")
    sx = sy = sxx = syy = sxy = sxz = syz = sz = 0.0
    for x, y in points:
        z = x * x + y * y
        sx += x
        sy += y
        sxx += x * x
        syy += y * y
        sxy += x * y
        sxz += x * z
        syz += y * z
        sz += z
    A = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, n]]
    B = [sxz, syz, sz]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        B[i], B[p] = B[p], B[i]
        for r in range(i + 1, 3):
            f = A[r][i] / A[i][i]
            for c in range(i, 3):
                A[r][c] -= f * A[i][c]
            B[r] -= f * B[i]
    sol = [0.0, 0.0, 0.0]
    for i in (2, 1, 0):
        v = B[i] - sum(A[i][c] * sol[c] for c in range(i + 1, 3))
        sol[i] = v / A[i][i]
    a, b, c = sol
    # 正规方程解出的是 u=2a, v=2b, w=c（z = 2a·x + 2b·y + c），必须除以 2
    cx, cy = a / 2.0, b / 2.0
    return cx, cy, (c + cx * cx + cy * cy) ** 0.5


# ---------------------------------------------------------------- 掩膜（C 层）

_ONES = {}
_GT = {}


def _ones(n):
    """n 个字节全为 0x01 的大整数。用来做「1 − white」得到墨迹掩膜。"""
    v = _ONES.get(n)
    if v is None:
        v = int.from_bytes(b"\x01" * n, "big")
        _ONES[n] = v
    return v


def _gt_table(th):
    t = _GT.get(th)
    if t is None:
        t = bytes(1 if v > th else 0 for v in range(256))
        _GT[th] = t
    return t


def ink_bits(px, w, h, th=200):
    """墨迹掩膜：任一通道 <= th 即视为墨迹。返回大整数，每像素占 1 字节，值 0/1。

    性能要点：`bytes.translate` 在 C 层把每个通道映射成 0/1，
    `int.from_bytes` 之后三通道按位与就是「三通道都白」，
    再与全 1 相减得到墨迹位图。全部在 C 层完成，84 万像素约 30ms。
    旧的逐像素双循环在同样尺寸下要 3~5 秒。
    """
    n = w * h
    t = _gt_table(th)
    r = int.from_bytes(px[0::3].translate(t), "big")
    g = int.from_bytes(px[1::3].translate(t), "big")
    b = int.from_bytes(px[2::3].translate(t), "big")
    return _ones(n) - (r & g & b)


def color_bits(px, w, h, ref, tol=40):
    """颜色掩膜：三通道各自与 ref 相差不超过 tol。返回大整数，语义同 ink_bits。

    用途是把图按颜色拆成互相独立的层（紫/蓝/红/黑），
    这样导线、器件、文字不会互相干扰，diff 也能分层报告。
    """
    n = w * h
    chans = []
    for k in range(3):
        ref_k = ref[k]
        table = bytes(1 if abs(v - ref_k) <= tol else 0 for v in range(256))
        chans.append(int.from_bytes(px[k::3].translate(table), "big"))
    return chans[0] & chans[1] & chans[2]


def bits_bytes(bits, n):
    """大整数掩膜 → bytes（值 0/1），便于切片与 bytes.count。"""
    return bits.to_bytes(n, "big")


def bits_count(bits):
    """掩膜内 1 的个数，即命中像素数。"""
    return bits.bit_count()


def crop_bits(bb, w, x0, x1, y0, y1):
    """从整图掩膜 bytes 里裁一块，返回新 bytes（宽度 x1-x0）。"""
    out = bytearray()
    for y in range(y0, y1):
        out += bb[y * w + x0:y * w + x1]
    return bytes(out)


def bits_bbox(bb, w, h):
    """掩膜外接框，返回 (minx, maxx, miny, maxy)；全空返回 None。

    用 `bytes.count / find / rfind` 逐行完成，比逐像素扫描快一个数量级。
    """
    minx = miny = 1 << 30
    maxx = maxy = -1
    for y in range(h):
        row = bb[y * w:(y + 1) * w]
        if not row.count(1):
            continue
        if y < miny:
            miny = y
        maxy = y
        left = row.find(1)
        right = row.rfind(1)
        if left < minx:
            minx = left
        if right > maxx:
            maxx = right
    if maxy < 0:
        return None
    return minx, maxx, miny, maxy


def bits_row_runs(bb, w, y, x0=0, x1=None):
    """掩膜 bytes 上某一行的连续命中段，闭区间 [(start, end)]。"""
    if x1 is None:
        x1 = w
    row = bb[y * w + x0:y * w + x1]
    runs = []
    pos = 0
    while True:
        i = row.find(1, pos)
        if i < 0:
            break
        j = row.find(0, i)
        if j < 0:
            j = len(row)
        runs.append((x0 + i, x0 + j - 1))
        pos = j
    return runs


def ellipse_axes(bb, w, x0, x1, y0, y1, min_span=8):
    """取椭圆/圆的两轴与圆心，返回 (cx, cy, rx, ry, is_ellipse)。

    用**外接框法**而不是最小二乘：完整椭圆的外接框是精确的，
    且不会被圆内文字带偏（Kasa 拟合要靠 outline_points 先剔点，剔漏就退化）。

    min_span 用来剔除穿过的同色细导线：一根 3px 竖线在某行只占 3 像素宽，
    整行跨度不足 8 就被跳过；椭圆轮廓行跨度动辄几十像素，不受影响。
    但**同色的水平长线（电池极板、导线）挡不住**，选区必须自己避开它们。
    """
    sub = crop_bits(bb, w, x0, x1, y0, y1)
    cw, ch = x1 - x0, y1 - y0
    minx = miny = 1 << 30
    maxx = maxy = -1
    for y in range(ch):
        row = sub[y * cw:(y + 1) * cw]
        if not row.count(1):
            continue
        left, right = row.find(1), row.rfind(1)
        if right - left + 1 < min_span:
            continue
        if y < miny:
            miny = y
        maxy = y
        if left < minx:
            minx = left
        if right > maxx:
            maxx = right
    if maxy < 0:
        return None
    minx, maxx, miny, maxy = minx + x0, maxx + x0, miny + y0, maxy + y0
    rx = (maxx - minx) / 2.0
    ry = (maxy - miny) / 2.0
    return ((maxx + minx) / 2.0, (maxy + miny) / 2.0, rx, ry,
            abs((maxx - minx) - (maxy - miny)) > 2)


def text_metrics(bb, w, x0, x1, y0, y1, text="", cjk_ratio=0.866, min_span=4):
    """文字墨迹度量 → 直接可写进 SVG 的数值。

    返回 dict：bbox / w / h / font_size / text_length / baseline / avg_advance。
    cjk_ratio 是「中文墨迹高 ÷ font-size」的实测比例（微软雅黑 Bold 约 0.866），
    用它反推字号，比自己试字号快得多。

    传入 text 时会额外给 avg_advance = 墨迹宽 ÷ 字数，用来判断有没有被拉宽：
    中文单字 advance 与 font-size 基本 1:1，比值明显大于 1.05 说明 textLength 写大了。

    注意 text_length 给的是**墨迹宽**；SVG 的 textLength 是 advance 宽，
    含全角冒号、数字、空格的行会偏 3%~10%，写进 SVG 时按 references 里的系数再修正。
    """
    cw, ch = x1 - x0, y1 - y0
    sub = crop_bits(bb, w, x0, x1, y0, y1)
    minx = miny = 1 << 30
    maxx = maxy = -1
    for y in range(ch):
        row = sub[y * cw:(y + 1) * cw]
        if not row.count(1):
            continue
        left, right = row.find(1), row.rfind(1)
        if right - left + 1 < min_span:
            continue
        if y < miny:
            miny = y
        maxy = y
        if left < minx:
            minx = left
        if right > maxx:
            maxx = right
    if maxy < 0:
        return None
    m = (minx + x0, maxx + x0, miny + y0, maxy + y0)
    wpx, hpx = m[1] - m[0] + 1, m[3] - m[2] + 1
    fs = round(hpx / cjk_ratio, 1)
    return {
        "bbox": m,
        "w": wpx,
        "h": hpx,
        "font_size": fs,
        "text_length": wpx,
        "baseline": m[3],
        "avg_advance": round(wpx / len(text), 1) if text else None,
        "stretch": round((wpx / len(text)) / fs, 2) if text and fs else None,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python pngx.py <图片.png> [TopN 颜色]")
        raise SystemExit(0)
    w, h, px = read_png(sys.argv[1])
    print("尺寸 %d x %d" % (w, h))
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    print("非白像素主色（取众数定精确色值）:")
    for r, g, b, c in color_stats(px, w, h)[:n]:
        print("  #%02X%02X%02X  (%3d,%3d,%3d)  %8d px" % (r, g, b, r, g, b, c))
