# 组件骨架 · 内容区

三个内容区组件决定区块的信息密度：产品截图框、区块标题、文档阅读页。
外壳组件（导航、首屏、按钮、页脚）见 `components-shell.md`。

---

## 1. 产品截图框（全站最省力的一招）

用一张真实截图套浏览器外壳，替掉整个"假控制台"。

```html
<figure class="product-showcase">
  <div class="showcase-bar">
    <span class="showcase-dots"><i></i><i></i><i></i></span>
    <span>Deploy / 统一工作台</span>
    <span class="showcase-live"><i></i>产品实景</span>
  </div>
  <button class="showcase-image" type="button" aria-label="查看大图">
    <img src="/images/product/workbench.png" width="1600" height="632" alt="统一工作台截图">
    <span>查看大图 ↗</span>
  </button>
  <figcaption><span>统一工作台 · 资产、发布、审计集中呈现</span><span>1600 × 632</span></figcaption>
</figure>

<dialog class="showcase-dialog">
  <button type="button">关闭预览 ×</button>
  <img src="/images/product/workbench.png" alt="统一工作台截图（大图）">
</dialog>
```

```css
.product-showcase {
  margin: 0; overflow: hidden;
  border: 1px solid #dce3f4; border-radius: var(--r-lg);
  background: #fff;
  box-shadow: 0 24px 70px rgba(83, 107, 179, .11), 0 3px 12px rgba(83, 107, 179, .04);
  text-align: left;
}
.showcase-bar {
  height: 40px; display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 0 18px;
  border-bottom: 1px solid #e6ebf6; background: #fcfdff;
  color: #7f8ba4; font-size: 10px;
}
.showcase-dots { display: flex; gap: 6px; min-width: 90px; }
.showcase-dots i { width: 7px; height: 7px; border-radius: 100%; }
.showcase-dots i:nth-child(1) { background: #edc7c7; }
.showcase-dots i:nth-child(2) { background: #efdfb8; }
.showcase-dots i:nth-child(3) { background: #bcdccd; }

.showcase-image { display: block; width: 100%; padding: 0; border: 0; background: #f6f7fc; }
.showcase-image img { display: block; width: 100%; height: auto; }
.showcase-image > span {
  position: absolute; right: 16px; bottom: 16px;
  padding: 6px 12px; border: 1px solid #e4e9f4; border-radius: 6px;
  background: #fffefa; color: #6174c9; font-size: 12px;
  opacity: 0; transition: opacity .2s;
}
.showcase-image:hover > span, .showcase-image:focus-visible > span { opacity: 1; }

.product-showcase figcaption {
  display: flex; justify-content: space-between; gap: 16px;
  padding: 13px 18px; border-top: 1px solid #e6ebf6;
  color: #6f7d98; font-size: 11px;
}

.showcase-dialog {
  width: 1500px; max-width: calc(100vw - 40px); max-height: 90dvh;
  padding: 16px; border: 1px solid #dce3f4; border-radius: var(--r-lg);
  background: #f7f9ff;
}
.showcase-dialog::backdrop {
  background: rgba(26, 36, 77, .79);
  backdrop-filter: blur(5px);
}
```

为什么值得抄：

| 假 DOM 界面 | 真实截图 |
|---|---|
| 几十个组件、几百行 CSS | 一个 `<figure>` + 一张图 |
| 文字会被选中、按钮可误点 | 纯装饰，无交互歧义 |
| 每次改文案都要改组件 | 重截一张图 |
| 首屏 JS/样式体积上涨 | 一次性 60–80KB 图片，`width`/`height` 固定不产生 CLS |

细节：**圆点颜色不用 macOS 原生红黄绿**（`#ff5f57` 太艳），改用去饱和的
`#edc7c7 / #efdfb8 / #bcdccd`——它暗示"这是浏览器"，但不抢视线。
右上角的绿点 + "产品实景"是信任信号，比写"截图"两个字有效。

---

## 2. 区块标题（三段网格）

```css
.section-header {
  display: grid;
  grid-template-columns: .6fr 1.2fr 1fr;
  align-items: end;
  gap: 40px;
  margin-bottom: 36px;
}
.section-header .eyebrow { font-size: 12px; letter-spacing: .1em; color: #7f91d2; }
.section-header h2 { margin: 12px 0 0; font-size: clamp(28px, 3vw, 40px); line-height: 1.5; letter-spacing: -.025em; }
.section-header > p { margin: 0; color: var(--muted); font-size: 15px; line-height: 1.9; }

@media (max-width: 900px) {
  .section-header { grid-template-columns: 1fr 1.5fr; gap: 24px; }
  .section-header > p { grid-column: 1 / -1; }
}
@media (max-width: 540px) {
  .section-header { grid-template-columns: 1fr; gap: 12px; margin-bottom: 28px; }
}
```

左边小标签、中间大标题、右边说明文字**底部对齐**（`align-items: end`）。
这个三段式让每个区块的起始行都有一个稳定的视觉锚点，比"居中标题 + 居中副标题"显得
信息密度更高、更像产品文档而非宣传页。

---

## 3. 文档阅读页

```css
.docs-layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) 200px;
  gap: 48px;
  align-items: start;
}
.docs-toc { position: sticky; top: calc(var(--header-h) + 24px); font-size: 13px; }
.docs-toc a {
  display: block; padding: 6px 0 6px 12px;
  border-left: 2px solid var(--line);
  color: var(--muted); line-height: 1.7;
}
.docs-toc a[aria-current="true"] { border-left-color: var(--primary); color: var(--primary); font-weight: 500; }

.docs-content { max-width: 720px; font-size: 15px; line-height: 1.9; }
.docs-content h2 { margin: 40px 0 16px; font-size: 24px; letter-spacing: -.02em; }
.docs-content p { margin: 0 0 16px; }
.docs-content pre { padding: 16px 20px; border-radius: var(--r-md); background: #f5f7fc; overflow-x: auto; }
```

- 正文 `15px / 1.9`，比官网的 16px 略小——阅读页是"长时间读"，字号过大会降低信息密度。
- 目录用**左侧 2px 描边**做进度指示，不用背景块：背景块在长目录里会脏。
- 中栏 `max-width: 720px` 是硬约束，不要让它随窗口拉伸。超过 40 个汉字的行宽会让
  视线回扫失败。
