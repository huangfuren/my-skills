---
name: ui-visual-language
description: >-
  Use when building or restyling a Chinese enterprise frontend that must feel
  calm, credible and comfortable to read — SaaS / DevOps / data-platform landing
  pages, product pages, docs sites, download pages, console shells and settings
  panels — or when a UI "works but looks cheap" and the cause is unknown.
  Distilled from yjops.com.cn (Deploy 运维平台, measured 2026-10-27): the six
  numeric parameters that carry the whole feel, exact colour / type / spacing /
  radius / shadow / easing tokens with contrast ratios, seven component
  skeletons (sticky blurred header, hero, button, browser-framed product
  screenshot, three-column section header, docs reading page, footer), page
  recipes, and the four defects
  found on the source site with correct settings. Triggers: 做得像这个站 /
  高级感 / 企业级 SaaS 官网 / 运维平台界面 / 设计 token / 看着舒服 / calm
  landing page / design system extraction.
license: MIT
compatibility: >-
  Source site yjops.com.cn measured 2026-10-27 (nginx static host; Vite bundle
  index-BdeuzaEo.js 344KB / index-BgxvFayx.css 65KB; Vue 3 + vue-router, no UI
  library, no animation library, no webfont). Tokens and recipes are
  stack-agnostic — apply unchanged to plain HTML/CSS, Vue 3 or React.
  `assets/tokens.css` is framework-free; `assets/landing.html` is a
  dependency-free single file that opens directly in a browser.
---

# 企业级前端视觉语言 · 参数手册

一句话结论：**这种"舒服"不是一种风格，是六个数字卡在窄区间里的结果**。
其中三条——中文行高、底色非纯白、单一强调色——决定约七成观感；任一条跑偏，
其余做得再细也会立刻掉档。反过来，这六条全做对，**不需要任何动画库**。

## 什么时候用

适用：

| 场景 | 具体形态 |
|---|---|
| 企业级产品官网 | 首屏 hero + 产品截图 + 能力矩阵 + CTA |
| 运维 / 数据 / 安全平台界面 | 控制台外壳、工作台、设置页、列表与详情 |
| 文档站 / 博客 | 阅读页、目录、搜索弹层 |
| 存量项目补设计规范 | 只接手 token 与组件骨架，不换框架 |

不适用（会做错）：

- 面向消费者的活动页、电商大促页 —— 需要高饱和、强对比、强情绪，本手册的
  "低对比克制"会显得寡淡。
- 已有成熟设计系统（Ant Design / Element Plus / shadcn）且 token 不可改 ——
  硬套会和组件库打架，收益低于直接调主题变量。
- 作品集 / Creative / 品牌 campaign 站 —— 那类站点靠视觉冲击，不靠阅读舒适。

## 六条铁律

按影响力排序，前三条决定基调。

| # | 参数 | 取值 | 为什么 | 典型反例 |
|---|---|---|---|---|
| 1 | 中文正文行高 | **1.9 – 1.95**（全局 1.7，长段落单独提） | 中文无西文升降部留白，同样行高下视觉密度更高；1.5 会成"字墙" | `line-height: 1.5` 铺满一段 16px 中文 |
| 2 | 底色 / 正文色 | 底 `#f5f7fc`、正文 `#273451` | 纯白 + 纯黑的对比过强，刺眼且廉价；冷灰蓝降低刺激、保留清晰 | `#fff` 底 + `#000` 字 |
| 3 | 强调色数量 | **全站 1 个**：按钮底 `#5063d6`，大字 / 图标 / 边框 / 焦点环 `#6579ee` | 多个彩色 = 没有重点，观众的注意力被摊平 | 每个模块配一种渐变 |
| 4 | 大标题字距 | `-0.03em ~ -0.04em`，字重 700–750 | 中文字形方正，大字号默认字距显松散，负字距把标题"拧成一个块" | 58px 标题用默认字距 |
| 5 | 缓动曲线 | `0.3s cubic-bezier(.22, 1, .36, 1)` | 起步快、收尾极慢；默认 `ease` 起步迟滞、收尾突兀，显机械 | `transition: all .3s ease` |
| 6 | 阴影 | 6–10% 透明度，大模糊半径 | 阴影的作用是"托起层级"，不是"描一道边" | `0 2px 4px rgba(0,0,0,.3)` |

第 4 条只对标题生效——**正文和小字不要用负字距**，会粘连。

第 3 条的两个值不是两个强调色。`#6579ee` 压白字只有 3.80:1，不达 AA，所以**按钮底必须用
加深的 `#5063d6`**（5.13:1）；浅的那支只给大字、图标、边框、焦点环——图形与大字只需 3:1。

## 技术选型：源站怎么做的

| 层 | 选择 | 判断依据 |
|---|---|---|
| 构建 | Vite | `type="module" crossorigin` + 哈希文件名 |
| 框架 | Vue 3 + vue-router（history） | `__vue_app__`、`data-v-*` scoped 样式、13 条路由 |
| 样式 | **手写 CSS，65KB**，无 Tailwind / Element Plus / Sass | 无 utility class、无 `el-` 前缀 |
| 动效 | **纯 CSS transition**，无 GSAP / Lenis / Swiper | 依赖扫描为 0；`@keyframes` 全站只有 1 个 |
| 图标 | 内联 SVG，无图标库 | 图标规则里直接写 `svg{stroke:currentColor}` |
| 字体 | **零字体文件**，`Inter` 打头但无 `@font-face` | 实际回落 PingFang SC / 微软雅黑 |
| 内容 | marked + highlight.js + DOMPurify + Mermaid | 文档页运行时渲染 Markdown |

关键结论：**这套观感的来源是"没有依赖"，不是 Vue**。手写 CSS 覆盖 13 条路由，
换来的是首屏零框架样式、零动画库开销。

需要偏离时：

| 需求 | 改动 |
|---|---|
| 要 SEO / 首屏直出 | 换 Nuxt / Next 或静态生成器，token 与配方不动 |
| 团队是 React | 只取 token 与组件骨架，不换框架 |
| 必须用组件库 | 把 token 灌进库的主题变量，禁止在业务层覆盖颜色 |

## 落地顺序

1. **先落 token**：把 `assets/tokens.css` 拷进项目，此步禁止边写边定颜色。
2. **定字阶**：只允许 7 档（见 `references/design-tokens.md`），超出就用 `clamp()` 在相邻档之间插值。
3. **做首屏**：hero（eyebrow → h1 带 `<em>` → 导语 → 双按钮 → 元信息行）+ 产品截图框。
4. **补外壳**：sticky 毛玻璃导航 + 页脚，然后才做内容区。
5. **过检查清单**：见文末，逐条勾。

## assets 用法

| 文件 | 用法 |
|---|---|
| `assets/tokens.css` | 直接 `<link>` 或 `@import`，提供全部 CSS 变量与 6 个原子类（按钮 / 容器 / 卡片 / 分段标题 / 标签 / 代码） |
| `assets/landing.html` | 单文件落地页基准，**双击即可打开**。作为骨架拷贝后替换文案与截图，不要重新设计版式 |

`landing.html` 里的产品图位置是内联 SVG 占位，**上线前必须换成真实截图**
（1600×632 左右的 PNG，控制在 80KB 内）——用 DOM 拼假界面是本手册明确反对的做法。

## 偏差表

改之前先确认代价。

| 你想改 | 会发生什么 | 建议 |
|---|---|---|
| 底色改纯白 | 立刻变成"后台管理系统"质感，失去产品感 | 保持 `#f5f7fc`，最浅退到 `#fafbfd` |
| 正文行高降到 1.75 | 中文长段落明显变挤 | 只在卡片、表格内降到 1.75 |
| 强调色提饱和度 | 观感从"工具"滑向"电商 / 游戏" | 上限约 `#5b6ff0` |
| 删掉阴影 | 卡片"飘"在底色上，层级消失 | 至少保留 `0 8px 24px rgba(52,75,128,.06)` |
| 加第二个强调色 | 视线分散 | 橙色只用于状态（警告 / 异常），绝不用于 CTA |
| 引入动画库 | 首屏 +30KB 起，收益极低 | CSS transition 覆盖这个量级的动效 |
| 上暗色主题 | 本 token 未验证，需重算阴影与对比 | 阴影改发光、强调色提亮 8% |
| 只改前台、后台管理不动 | 后台表格密度高，行高 1.9 与 64px 内边距会显得空，一屏装不下几行 | 后台另设密度 token：行高 1.7、单元格内边距 12px，颜色照用 |

## 源站实测到的四个缺陷

不要顺手抄进去，细节与修法见 `references/perf-and-seo.md`：

1. **未开压缩**：JS 352,664 字节原样传输（`Content-Length` 等于原始字节），
   CSS 65KB 同样裸传。gzip 后 JS 约 110KB。
2. **哈希资源无 `Cache-Control`**：只给 `ETag`，每次访问回源校验。
3. **纯客户端渲染**：`/robots.txt` 与 `/sitemap.xml` 均返回同一份 724 字节
   `index.html` 外壳，博客与文档内容搜索引擎抓不到。
4. **白字配主色按钮 = 3.80:1**，低于 WCAG AA 的 4.5:1；辅助色 `#66758e`
   在底色上 4.35:1，同样压线。

## 复现取证

上面的数值不必信任本文档，可以自己重算：

```bash
curl -s https://yjops.com.cn -o index.html && wc -c index.html   # 724 字节外壳
CSS=$(grep -o '/assets/index-[^"]*\.css' index.html) && curl -s "https://yjops.com.cn$CSS" -o site.css
grep -o ':root{[^}]*}' site.css                                   # 全部设计 token
grep -oE 'line-height:[0-9.]+' site.css | sort | uniq -c          # 行高分布
curl -sI "https://yjops.com.cn$CSS" | grep -i 'content-encoding\|cache-control'  # 两项皆空 = 缺陷 1、2
```

对比度用任意 WCAG 计算器复算 `#ffffff / #6579ee` 与 `#66758e / #f5f7fc` 两组即可。

## 检查清单

- [ ] 全站强调色只有一个，且没有用在非交互装饰上？
- [ ] 中文正文行高 ≥ 1.9？
- [ ] 底色不是纯白、正文不是纯黑？
- [ ] h1 有 -0.03em 以上负字距，正文没有？
- [ ] 每个 `transition` 都写了曲线，没有 `all` + `ease`？
- [ ] 阴影透明度 ≤ 12%，模糊半径 ≥ 24px？
- [ ] 圆角只在 5 档里取值，没有 11px / 13px 这类孤值？
- [ ] 首屏视觉是真实截图，不是 DOM 拼的假界面？
- [ ] 有 `@media (prefers-reduced-motion: reduce)` 降级？
- [ ] 构建产物开了 gzip / brotli，哈希资源 `immutable`？

## references

- [design-tokens.md](references/design-tokens.md) —— 色板 / 字阶 / 间距 / 圆角 / 阴影 / 缓动 / 断点，含对比度与可复制 `:root`
- [components-shell.md](references/components-shell.md) —— 外壳四件：吸顶导航、首屏 hero、按钮、页脚
- [components-content.md](references/components-content.md) —— 内容区三件：产品截图框、区块标题、文档阅读页
- [page-recipes.md](references/page-recipes.md) —— 落地页 / 文档站 / 下载页的节序与节奏
- [perf-and-seo.md](references/perf-and-seo.md) —— 四个缺陷的正确修法与验收命令

---

配套 skill：本篇不依赖 DSH 生态，目标不是插件界面时自足即可。若这套视觉要落进 DSH 插件的设置页，
页面结构与配置读写见 `dsh-settings-page`；控件放哪、被裁切怎么处理见 `dsh-client-slot-placement`。
总览与索引见 `dsh-plugin-dev-guide`。

页面里要配架构图、流程图、拓扑图时，作图规范见 `svg-diagram`——配色语义与字号层级与本篇同源，可直接对接。
