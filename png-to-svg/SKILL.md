---
name: png-to-svg
description: |
  把位图（PNG 截图、电路原理图、流程框图、结构示意、思维导图截图）1:1 还原成可编辑的手写 SVG，
  而不是描摹成路径垃圾。适用于几何清晰、文字较多、颜色有限的工程类图片：
  用纯标准库解 PNG、按颜色掩膜逐行量色段、拟合圆/椭圆、反算字号与 textLength，
  再用 1:1 渲染回原图做像素差分，按差异热点迭代。
  不适用于照片、SEM、热图、渐变插画——那些应走描摹工具（vtracer 一类）。
  触发词: "转成 svg", "png 转 svg", "图片转矢量", "矢量化这张图", "重绘这张图", "还原成 svg",
  "做成可编辑的 svg", "把截图转 svg", "照着这张图画 svg"。
---

# png-to-svg：位图 1:1 还原成矢量

核心原则：**先量再画，画完必渲，渲完必比。** 任何"看着差不多"的判断都不可信。

## 与 svg-diagram 的边界

| | svg-diagram | 本技能 |
|---|---|---|
| 目标 | 设计一张新图 | 复刻一张已有图 |
| 字号 | 11 档规范档位 | 必须按实测（17.5 / 18.5 / 21.5 都可能） |
| 配色 | 48 色语义配色 | 必须取原图众数，哪怕不协调 |
| 验收 | 留白、对齐、可读性 | 与原图 1:1 像素重合 |

**不要**把还原图套进设计规范。用 `check_svg.py` 检查会报一堆字号与配色 ERROR，那是误报——还原类图不要为了过校验去改字号。

## 何时不用本技能

- 照片、SEM、实测热图：数据本身不可矢量重建，介入即造假。
- 手绘插画、渐变、纹理：几何测不出来，用 vtracer 类描摹更划算。
- 判断标准：图中「可以用几十条线段 + 几十个字符描述」→ 用本技能；「需要成百上千个轮廓点」→ 用描摹。

实测对比（NPN 原理图）：vtracer 把 34 处文字全变成路径（不可编辑）、319 色、体积涨 5 倍。

## 十步

### 测量段（不可跳，跳过必返工）

1. **定画布** — `pngx.read_png()` 拿原始宽高，`viewBox` 与之相同，严格 1:1。任何缩放都会让后续比对失效。
2. **取色** — `pngx.color_stats()` 对非白像素取众数，得到精确 RGB。例：紫 `#A349A4`、蓝 `#3F48CC`、红 `#ED1C24`。不能靠眼看。
3. **分色掩膜** — 用 `pngx.color_bits()` 给每种颜色建一张掩膜，之后所有测量都在单色上做，互不干扰。掩膜是**大整数**，统计用 `bits_count()`，切片前先 `bits_bytes()`。
4. **量几何** — 先跑 `probe.py` 出全图报告（按色分层的水平线/垂直线/文字行/图形块，含线宽与建议字号），再从报告里挑可疑处用 `pngx.bits_row_runs()` 精测。圆/椭圆用 `pngx.ellipse_axes()`（外接框法，两轴差 > 2px 即椭圆），**不许目测**。
5. **量文字** — `textfit.py` 给紧贴文字的框，直接得到 `x` / `y`(基线) / `font-size` / `textLength` 四个值。框贴住三条边时会自动报警：那是选区吞进了同色图形（椭圆环、导线）。

### 搭建段

6. **按色分层** — 每种颜色一个 `<g>`，坐标全部写实测值。顺序按原图图层从后到前。

### 验证段

7. **1:1 渲染** — 用 Edge headless 出图（本机脚本见下），宽度必须等于原图宽度。
8. **判偏移** — `align.py` 先回答「是整体平移，还是横向/纵向缩放不一致」。它的整数平移实测会直接告诉你平移能不能提高重合：**质心对齐不等于重合最大**，实测过平移后质心归零、重合率反而下降 0.6pt 的情况，所以只认实测。
9. **像素差分** — `diffcheck.py` 出重合率、分色层、差异图、40px 热点块。**只看热点块**，改对应坐标，重跑第 7 步。`--max-bad` / `--fail-block` 给定阈值后可当门禁用（退出码 1）。
10. **结构体检 + 目视** — `validate_vector_svg.py`（第三方，纯标准库）查 viewBox 合法性、唯一 id、无 `<image>` 污染、无 nan/inf；再出 2 倍图目视一遍。

## 工具

```
scripts/pngx.py        测量库
  读写      read_png / write_png / crop_scale
  掩膜      ink_bits / color_bits        ← C 层，84 万像素 8ms
  几何      bits_bbox / bits_row_runs / crop_bits / ellipse_axes / fit_circle
  文字      text_metrics                 ← 墨迹框 → 字号 / textLength / 基线
  旧接口    color_stats / near / row_runs / col_runs / bbox / outline_points

scripts/probe.py       全图几何报告：按色分层的水平线/垂直线/文字行/图形块，一条命令替代手写探针
scripts/textfit.py     文字度量 → 直接给出 <text> 的 x/y/font-size/textLength
scripts/align.py       亚像素偏移估计 + 整数平移实测，判断是整体平移还是缩放不一致
scripts/diffcheck.py   像素差分：全图/区域重合率、分色层、热点块、差异图、门禁
scripts/compare.py     上下对比图（上=原图，下=重绘，中间红带）
scripts/render.py      Edge headless 渲染 SVG→PNG，宽度对齐原图
scripts/selftest.py    自检：8 项，改动 pngx.py 或 align.py 后先跑
```

```bash
S=<本技能目录>/scripts    # 装在 WorkBuddy 里即 ~/.workbuddy/skills/png-to-svg/scripts

python $S/selftest.py                                   # 先自检，8/8 必须全 PASS

# 测量：先出一份全图报告，再决定量哪里
python $S/probe.py 原图.png --colors 4 --min-len 20
python $S/probe.py 原图.png --region 440,545,84,172 --colors 1   # 只看某块

# 文字：给定紧贴文字的框，直接得到可粘贴的属性
python $S/textfit.py 原图.png --color A349A4 --region 466,520,132,168 --text 大用电器

# 验证：先判偏移性质，再比像素，最后过门禁
python $S/align.py 原图.png 渲染.png --y-max 480
python $S/diffcheck.py 原图.png 渲染.png diff.png --y-max 480 --layers
python $S/diffcheck.py 原图.png 渲染.png --y-max 480 --max-bad 30000 --fail-block 300   # CI 用

# 对照图
python $S/compare.py 原图.png 渲染.png 出.png 595 400 90 45 8     # 局部 8 倍
python $S/compare.py 原图.png 渲染.png 出.png 0 0 1353 554 1      # 整图 1:1
```

`diffcheck.py` 退出码：`0` 通过 / `1` 未过阈值 / `2` 输入错误或拒绝覆盖（已有差异图时须加 `--force`）。

渲染（Edge headless，Windows 本机可用）：

```bash
python $S/render.py 图.svg --width 1353 --scale 1 --out render   # 1:1，给 diffcheck 用
python $S/render.py 图.svg --width 1353 --scale 2 --out preview  # 2 倍，给目视用
```

`--width` 必须是原图宽度，否则像素差分毫无意义。

## 验收标准

| 项 | 门槛 |
|---|---|
| 主图区重合率 | 55%~70% 属正常范围（汉字笔画差 1px 就会明显拉低）。低于 50% 说明有系统性偏移 |
| 偏移 | `align.py` 的整数平移实测应为「任何平移都不会提高重合」；若它给出可行平移，先改再判 |
| 差异分布 | 必须**散布**。单块 40×40 内差异 > 200px，说明该处几何错了，回去量 |
| 分色层 | 每一层的召回率应大致相当；某一层显著偏低 → 那一层整体错位或漏画 |
| 门禁 | `diffcheck.py --max-bad N --fail-block N` 退出码 0，才算过 |
| 位图残留 | `<image>` 必须为 0 |
| 文字 | 逐条核内容与颜色，不能有错字；宽度偏差 ≤ 2px，位置偏差 ≤ 1px |
| 尺寸 | 与原图一致（新增图例除外，图例另加高度） |

## 吸收的外部方案与边界

对比过描摹类与生成类工具后，三条结论：

- **描摹类**（vtracer / potrace / ImageMagick / SVGcode）：只借「按颜色分层」的思想，不用其输出。理由：文字会变成路径，`0.7V`、`开关` 就不可搜索不可改。
- **生成类**（StarVector / OmniSVG）：不采用。它们做的是"重新画一遍"，坐标与字号不保证，与 1:1 复刻目标相反。
- **技能类**（syi0808/svg-skills 等）：借了工程约定——比对要带阈值与退出码、输出要防覆盖、渲染要限尺寸；没借它的"看渲染图判断"，因为那仍是目测。

## 陷阱

**全部见 `references/001-陷阱与反算.md`**（10 条主项 + 3 条子项），包括字号反算、`textLength` 反算、半像素栅格、圆/椭圆判别、箭头与开关符号的真实结构。动手前先读一遍，这些都是返工过的。

## 交付

- `<原名>.svg` — 可编辑矢量，0 个位图节点
- `<原名>-预览.png` — 2 倍渲染，供目视
- 一句话说明剩余差异（通常是字体笔画粗细），不要隐瞒
