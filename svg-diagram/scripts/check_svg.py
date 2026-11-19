#!/usr/bin/env python3
"""
check_svg.py —— svg-diagram skill 的结构校验器

只查"机器能查的"，查不了"图有没有表达对意思"——后者必须渲染目视。
定位：目视之前的粗筛，不是替代品。

用法：
    python check_svg.py images/xxx.svg
    python check_svg.py images/*.svg --json
    python check_svg.py images/xxx.svg --palette ../../references/001-视觉规范.md

退出码：
    0  没有 error（可能有 warning）
    1  有 error
    2  文件读不了 / 用法错误

零第三方依赖，Python 3.8+ 可用。
"""

import sys
import re
import json
import pathlib
import xml.etree.ElementTree as ET

NS = "{http://www.w3.org/2000/svg}"

# 001 第四节固定的 11 档字号
FONT_SIZES = {"20", "17", "15", "14", "13", "12.5", "12", "11.5", "11", "10", "9.5"}

# marker 尺寸与线宽的配套关系：stroke-width 上限 -> 允许的最小 markerWidth
MARKER_MIN_WIDTH = [(1.5, 7), (2.5, 10), (99, 12)]

# 画布模式（001 第一节）
CANVAS_MODES = {1200: "A 内嵌即读", 1400: "A 宽图", 1960: "B 全景查阅"}

# 容器色不进图例（002 第八节的例外条款）
CONTAINER_FILLS = {"#ffffff", "#f1f8e9", "#fff3e0", "#fff8e1", "#eceff1", "#fafafa"}


class Report:
    def __init__(self, path):
        self.path = path
        self.items = []          # (severity, check, message)
        self.skipped = []

    def err(self, check, msg):
        self.items.append(("error", check, msg))

    def warn(self, check, msg):
        self.items.append(("warning", check, msg))

    def skip(self, msg):
        self.skipped.append(msg)

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "error"]

    @property
    def warnings(self):
        return [i for i in self.items if i[0] == "warning"]


def fnum(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_viewbox(root):
    vb = (root.get("viewBox") or "").replace(",", " ").split()
    if len(vb) != 4:
        return None
    return tuple(fnum(x) for x in vb)


def load_palette(explicit=None):
    """从 001-视觉规范.md 提取已登记色值；找不到就返回 None（跳过色值检查）"""
    candidates = []
    if explicit:
        candidates.append(pathlib.Path(explicit))
    here = pathlib.Path(__file__).resolve().parent
    candidates += [here.parent / "references" / "001-视觉规范.md",
                   here.parent / "001-视觉规范.md"]
    for c in candidates:
        if c.exists():
            txt = c.read_text(encoding="utf-8", errors="ignore")
            return {h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}", txt)}
    return None


def text_width(s, fs):
    """宽度估算：中文/全角 ≈ fs，其余 ≈ fs × 0.55（002 第五节）"""
    w = 0.0
    for ch in s:
        w += fs if ord(ch) > 0x2E80 else fs * 0.55
    return w


def anchor_bounds(el, s, fs):
    """返回 (左边界, 右边界)"""
    x = fnum(el.get("x"))
    w = text_width(s, fs)
    anchor = el.get("text-anchor") or "start"
    if anchor == "middle":
        return x - w / 2, x + w / 2
    if anchor == "end":
        return x - w, x
    return x, x + w


def check_file(path, palette):
    rep = Report(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        rep.err("read", f"文件读不了：{e}")
        return rep

    # ---- 1. XML 可解析 ----
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        rep.err("xml", f"XML 解析失败：{e}")
        rep.err("xml", "最常见原因：文字里有未转义的 & 或 <；转义为 &amp; / &lt; / &gt;（见 001 第九节）")
        if re.search(r"<!--[^>]*--[^>]*-->", raw):
            rep.err("xml", "XML 注释内容里出现了 -- ，XML 不允许，换成单个短横线")
        return rep

    vb = parse_viewbox(root)
    if not vb:
        rep.err("viewbox", "缺少 viewBox 或格式不是 4 个数——图无法自适应缩放")
        vb = (0, 0, 0, 0)
    vx, vy, vw, vh = vb

    # ---- 2. 白底 rect ----
    bg = [r for r in root.iter(NS + "rect")
          if (r.get("fill") or "").lower() == "#ffffff"
          and abs(fnum(r.get("x"))) < 1 and abs(fnum(r.get("y"))) < 1]
    if not bg:
        rep.err("background", "缺白底 rect——深色模式下文字会看不见")
    else:
        b = bg[0]
        if abs(fnum(b.get("width")) - vw) > 1 or abs(fnum(b.get("height")) - vh) > 1:
            rep.warn("background",
                     f"白底 rect 尺寸 {b.get('width')}×{b.get('height')} 与 viewBox {vw:g}×{vh:g} 不一致")

    # ---- 3. 画布模式 ----
    mode = CANVAS_MODES.get(int(vw))
    if mode is None:
        rep.warn("canvas", f"画布宽 {vw:g} 不是标准值（1200 / 1400 / 1960）——先确认读者会不会点开看大图")

    # ---- 4. 字体栈 ----
    family = root.get("font-family") or ""
    if not family:
        for t in root.iter(NS + "text"):
            if t.get("font-family"):
                family = t.get("font-family")
                break
    if family:
        fams = [f.strip().strip("'\"") for f in family.split(",")]
        first = fams[0] if fams else ""
        if first in ("-apple-system", "system-ui", "sans-serif"):
            rep.err("font", f"字体栈以通用族名 {first!r} 打头——cairosvg/rsvg 会整段渲染成方块，"
                            "首个必须是本机实体字体（Microsoft YaHei）")
        if not any("Noto Sans CJK" in f for f in fams):
            rep.err("font", "字体栈缺 Noto Sans CJK SC——Linux / 容器 / 服务端渲染会中文豆腐块")
        if not any("YaHei" in f or "PingFang" in f for f in fams):
            rep.warn("font", "字体栈里没有 Microsoft YaHei / PingFang SC，Windows 和 macOS 可能选不到中文字体")
    else:
        rep.warn("font", "整个文件没声明 font-family，渲染器会用默认字体，中文可能豆腐块")

    # ---- 5. 色值登记 ----
    if palette is None:
        rep.skip("找不到 001-视觉规范.md，跳过色值登记检查")
    else:
        used = {}
        for el in root.iter():
            for attr in ("fill", "stroke"):
                v = el.get(attr)
                if v and v.startswith("#") and len(v) == 7:
                    used.setdefault(v.lower(), el.tag.split("}")[-1])
        unregistered = {c: t for c, t in used.items() if c not in palette}
        for c, t in sorted(unregistered.items()):
            rep.err("palette", f"色值 {c} 未在 001 登记（出现在 <{t}>）——复用最接近的语义色，不要新增")

    # ---- 6. 元素越出画布 ----
    def out_of_canvas(x, y, w, h):
        return x < -0.5 or y < -0.5 or x + w > vw + 0.5 or y + h > vh + 0.5

    for r in root.iter(NS + "rect"):
        x, y = fnum(r.get("x")), fnum(r.get("y"))
        w, h = fnum(r.get("width")), fnum(r.get("height"))
        if out_of_canvas(x, y, w, h):
            rep.err("bounds", f"<rect> 越出画布：x={x:g} y={y:g} w={w:g} h={h:g}（画布 {vw:g}×{vh:g}）")
    for ln in root.iter(NS + "line"):
        pts = [(fnum(ln.get("x1")), fnum(ln.get("y1"))), (fnum(ln.get("x2")), fnum(ln.get("y2")))]
        for px, py in pts:
            if px < -0.5 or py < -0.5 or px > vw + 0.5 or py > vh + 0.5:
                rep.err("bounds", f"<line> 端点越出画布：({px:g}, {py:g})")

    # ---- 7. 字号档位 ----
    for t in root.iter(NS + "text"):
        fs_raw = t.get("font-size")
        if not fs_raw:
            continue
        if fs_raw not in FONT_SIZES:
            content = (t.text or "").strip()[:18]
            rep.err("font-size", f"字号 {fs_raw} 不在固定 11 档内（{content!r}）——只从 001 第四节取值")
        if fnum(fs_raw) < 9.5:
            rep.err("font-size", f"字号 {fs_raw} 低于 9.5 下限")

    # ---- 8. marker 属性 ----
    markers = {}
    for m in root.iter(NS + "marker"):
        mid = m.get("id") or "(无 id)"
        markers[mid] = fnum(m.get("markerWidth"), 0)
        if m.get("markerUnits") != "userSpaceOnUse":
            rep.err("marker", f"marker #{mid} 缺 markerUnits=\"userSpaceOnUse\"——箭头会随线宽翻倍")
        if not m.get("orient"):
            rep.err("marker", f"marker #{mid} 缺 orient，箭头不会转向")

    # 粗线配小箭头
    for el in list(root.iter(NS + "path")) + list(root.iter(NS + "line")):
        mref = el.get("marker-end") or el.get("marker-start")
        if not mref:
            continue
        mid = mref.replace("url(#", "").replace(")", "").strip()
        if mid not in markers:
            rep.err("marker", f"引用了未定义的 marker #{mid}")
            continue
        sw = fnum(el.get("stroke-width"), 1.0)
        mw = markers[mid]
        limit = next((need for cap, need in MARKER_MIN_WIDTH if sw <= cap), 7)
        if mw < limit:
            rep.err("marker",
                    f"stroke-width={sw:g} 配了 {mw:g}×{mw:g} 的箭头 #{mid}——"
                    f"线宽 ≥2 要换 10×10，3 换 12×12，否则箭头不成比例")

    # ---- 9. 卡片溢出容器 ----
    rects = []
    for r in root.iter(NS + "rect"):
        rects.append({
            "x": fnum(r.get("x")), "y": fnum(r.get("y")),
            "w": fnum(r.get("width")), "h": fnum(r.get("height")),
            "fill": (r.get("fill") or "").lower(),
        })
    # 容器 = 白色填充的高框；排除与画布同尺寸的页面白底
    containers = [
        r for r in rects
        if r["fill"] == "#ffffff" and r["h"] >= 100
        and not (r["x"] <= 1 and r["y"] <= 1
                 and abs(r["w"] - vw) < 2 and abs(r["h"] - vh) < 2)
    ]
    for c in rects:
        if c["fill"] in ("", "#ffffff") or c is None:
            continue
        for box in containers:
            # 卡片包含容器 → 是父级，跳过
            if (c["x"] <= box["x"] and c["y"] <= box["y"]
                    and c["x"] + c["w"] >= box["x"] + box["w"]
                    and c["y"] + c["h"] >= box["y"] + box["h"]):
                continue
            overlaps = (c["x"] < box["x"] + box["w"] and c["x"] + c["w"] > box["x"]
                        and c["y"] < box["y"] + box["h"] and c["y"] + c["h"] > box["y"])
            inside = (c["x"] >= box["x"] - 0.5 and c["x"] + c["w"] <= box["x"] + box["w"] + 0.5
                      and c["y"] >= box["y"] - 0.5 and c["y"] + c["h"] <= box["y"] + box["h"] + 0.5)
            if overlaps and not inside:
                rep.err("container",
                        f"卡片 x={c['x']:g} y={c['y']:g} {c['w']:g}×{c['h']:g} "
                        f"溢出了容器 x={box['x']:g} y={box['y']:g} {box['w']:g}×{box['h']:g}")

    # ---- 10. 文字溢出卡片 ----
    for t in root.iter(NS + "text"):
        s = (t.text or "").strip()
        if not s:
            continue
        fs = fnum(t.get("font-size"), 12)
        ty = fnum(t.get("y"))
        left, right = anchor_bounds(t, s, fs)
        # 找中心点所在的卡片（非白底、非通栏）
        cx = (left + right) / 2
        for c in rects:
            if c["fill"] in ("", "#ffffff") or c["w"] >= vw * 0.7:
                continue
            if not (c["x"] - 0.5 <= cx <= c["x"] + c["w"] + 0.5):
                continue
            if not (c["y"] - 0.5 <= ty <= c["y"] + c["h"] + 0.5):
                continue
            pad = 2.0
            if right > c["x"] + c["w"] - pad or left < c["x"] + pad:
                over = max(right - (c["x"] + c["w"]), c["x"] - left)
                rep.err("text-overflow",
                        f"文字 {s[:16]!r} (字号 {fs:g}) 溢出卡片 {c['w']:g} 宽约 {over:.0f}px"
                        "——降字号或加宽卡片（002 第五节）")
            break

    # ---- 11. 图例与图上元素对应 ----
    legend_zone_y = vh * 0.85
    legend_fills = {r["fill"] for r in rects
                    if r["y"] >= legend_zone_y and 10 <= r["w"] <= 40 and r["h"] <= 22
                    and r["fill"] not in ("", "#ffffff")}
    body_fills = {r["fill"] for r in rects
                  if r["y"] < legend_zone_y and r["fill"] not in ("", "#ffffff")}
    for c in sorted(legend_fills - body_fills):
        rep.warn("legend", f"图例里出现 {c}，但正文区没有这个颜色的元素——删掉该图例条目")
    for c in sorted(body_fills - legend_fills - CONTAINER_FILLS):
        rep.warn("legend", f"正文区出现 {c}，图例里没有——补一条，或确认它是不是容器色（容器色不进图例）")

    # ---- 12. 成排卡片左右内边距对称 ----
    for box in containers:
        row = [r for r in rects
               if r is not box and r["fill"] not in ("", "#ffffff")
               and abs(r["h"] - 60) < 30
               and r["y"] >= box["y"] and r["y"] + r["h"] <= box["y"] + box["h"]
               and r["x"] >= box["x"] and r["x"] + r["w"] <= box["x"] + box["w"] + 30]
        if len(row) < 2:
            continue
        # 按 y 分组，同排才比
        rows = {}
        for r in row:
            key = round(r["y"])
            rows.setdefault(key, []).append(r)
        for key, items in rows.items():
            if len(items) < 2:
                continue
            items.sort(key=lambda r: r["x"])
            p_left = items[0]["x"] - box["x"]
            p_right = (box["x"] + box["w"]) - (items[-1]["x"] + items[-1]["w"])
            if abs(p_left - p_right) > 1.0:
                rep.warn("symmetry",
                         f"容器 y={box['y']:g} 内 y={key} 那排：左内边距 {p_left:.0f} / "
                         f"右内边距 {p_right:.0f} 不等——视觉上会觉得歪")

    # ---- 13. 完全没文字的图 ----
    if not any((t.text or "").strip() for t in root.iter(NS + "text")):
        rep.err("empty", "图里没有任何文字——确认是否漏了标签")

    return rep


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    as_json = "--json" in argv
    palette = None
    if "--palette" in argv:
        idx = argv.index("--palette")
        if idx + 1 < len(argv):
            palette = argv[idx + 1]
            args = [a for a in args if a != palette]

    if not args:
        print(__doc__)
        return 2

    pal = load_palette(palette)
    reports = []
    for a in args:
        p = pathlib.Path(a)
        if not p.exists():
            reports.append(Report(p))
            reports[-1].err("read", "文件不存在")
            continue
        reports.append(check_file(p, pal))

    total_err = sum(len(r.errors) for r in reports)
    total_warn = sum(len(r.warnings) for r in reports)

    if as_json:
        out = {
            "tool": "check_svg",
            "summary": {"files": len(reports), "errors": total_err, "warnings": total_warn},
            "files": [{
                "file": str(r.path),
                "findings": [{"severity": s, "check": c, "message": m} for s, c, m in r.items],
                "skipped": r.skipped,
            } for r in reports],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for r in reports:
            print(f"\n=== {r.path} ===")
            if not r.items:
                print("  未发现结构问题")
            for sev, chk, msg in r.items:
                tag = "ERROR" if sev == "error" else "WARN "
                print(f"  [{tag}] {chk:<14} {msg}")
            for s in r.skipped:
                print(f"  [SKIP ] {s}")
        print(f"\n{len(reports)} 个文件，{total_err} 个 error，{total_warn} 个 warning")
        if total_err == 0 and total_warn == 0:
            print("结构层通过。但这不代表图画对了——必须渲染目视（004 第二节）。")
        elif total_err:
            print("先修 error。warning 逐条判断，可能是容器色等例外情况。")

    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
