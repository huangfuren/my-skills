# 组件骨架 · 外壳

四个外壳组件决定这类站点"像不像一个产品"：吸顶导航、首屏、按钮、页脚。
每节给：结构 → 关键 CSS → 为什么这样做。CSS 已去掉 scoped 哈希与无关属性，可直接粘贴。
内容区组件（产品截图框、区块标题、文档阅读页）见 `components-content.md`。

---

## 1. 吸顶导航

```html
<header class="site-header" data-hidden="false">
  <div class="shell header-inner">
    <a class="brand" href="/">…logo…</a>
    <nav class="nav">
      <a href="/" aria-current="page">首页</a>
      <a href="/product">产品</a>
      <a href="/docs">文档</a>
    </nav>
    <div class="header-actions">
      <button class="search-trigger">搜索文档、文章 <kbd>/</kbd></button>
      <a href="/login">登录</a>
      <a class="site-button site-button--primary" href="/register">注册账号</a>
    </div>
  </div>
</header>
```

```css
.site-header {
  position: sticky; top: 0; z-index: 100;
  height: var(--header-h);
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, .93);
  -webkit-backdrop-filter: blur(20px);
  backdrop-filter: blur(20px);
  transition: transform .32s var(--ease-out), opacity .24s ease;
}
.site-header[data-hidden="true"] { transform: translateY(-100%); opacity: 0; }

.nav a {
  display: inline-flex; align-items: center;
  min-height: 40px; padding: 8px 16px;
  border-radius: var(--r-md);
  color: #4a5875; font-size: 15px;
  transition: background .18s, color .18s;
}
.nav a:hover { color: var(--primary); }
.nav a[aria-current="page"] { background: var(--soft); color: var(--primary); font-weight: 500; }

.search-trigger {
  display: flex; align-items: center; gap: 9px;
  width: 216px; min-height: 40px; padding: 8px 12px;
  border: 1px solid #e7ebf5; border-radius: 9px;
  background: #f5f7fc; color: #8995ae;
  font-size: 12px; text-align: left;
}
.search-trigger:hover { border-color: #c5d0f6; background: #eff3ff; color: #667bd5; }
```

三个要点：

- **93% 白 + 20px 模糊**。低于 90% 会透出内容显脏，100% 就没有毛玻璃；模糊半径
  20px 是为了让滚过去的标题变成一团柔和的色块，而不是可辨认的字。
- **下滚隐藏、上滚出现**。几十行 JS：比较 `scrollY` 与上一次值，向下且超过
  `header-h` 时置 `data-hidden="true"`。移动端这一步比什么都重要——它把首屏高度还给了内容。
- **激活态用浅色底而非下划线**。药丸底比下划线更"控件"，在 SaaS 语境里更像应用而非博客。

---

## 2. 首屏 hero

```html
<section class="home-hero">
  <div class="home-hero__glow" aria-hidden="true"></div>
  <div class="shell home-hero__inner">
    <div class="home-hero__copy">
      <p class="hero-eyebrow"><i></i>为自建基础设施而设计</p>
      <h1>让部署、运维与<br><em>安全管理</em>集中在一个平台</h1>
      <p class="hero-lead">统一资产、自动化发布、远程运维与审计，帮助技术团队更快、更稳、更安全地交付应用。</p>
      <div class="hero-actions">
        <a class="site-button site-button--primary" href="/register">注册账号，开始使用 →</a>
        <a class="site-button" href="/download">获取 Deploy ↓</a>
        <a class="hero-link" href="/docs">阅读文档 ↗</a>
      </div>
      <div class="hero-meta">
        <span><i>01</i>Server + K8s</span>
        <span><i>02</i>Playbook + Pipeline</span>
        <span><i>03</i>RBAC + Audit</span>
      </div>
    </div>
    <!-- 产品截图框，见 components-content.md 第 1 节 -->
  </div>
</section>
```

```css
.home-hero {
  position: relative; overflow: hidden;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(120deg, #f2f6ff, #f6f5ff 60%, #edf5ff);
}
.home-hero__glow {
  position: absolute; width: 600px; height: 600px;
  right: -140px; top: -160px;
  border: 80px solid rgba(227, 232, 255, .25);
  border-radius: 50%;
}
.home-hero__inner {
  position: relative;
  display: grid; grid-template-columns: minmax(0, 1fr);
  gap: 44px; padding-block: 64px 40px; text-align: center;
}

.hero-eyebrow {
  display: inline-flex; align-items: center; gap: 9px;
  margin: 0; padding: 7px 12px;
  border: 1px solid #dfe7ff; border-radius: var(--r-pill);
  background: rgba(255, 255, 255, .7);
  color: #5e72b4; font-size: 12px; font-weight: 600;
}
.hero-eyebrow i { width: 6px; height: 6px; border-radius: 50%; background: var(--primary); }

.home-hero h1 {
  margin: 24px 0;
  font-size: clamp(38px, 4vw, 58px);
  line-height: 1.38;
  letter-spacing: -.035em;
  font-weight: 750;
}
.home-hero h1 em { color: var(--primary); font-style: normal; }

.hero-lead {
  max-width: 660px; margin: 0 auto;
  color: var(--muted); font-size: 16px; line-height: 1.95;
}
```

四个要点：

- **`<em>` 只染一个词**。整句一个强调色，读起来有重音但不花。染两个词就散了。
- **背景光晕不用 `filter: blur()`**。一个 600×600 的圆、80px 粗边框、挪到画布外，
  柔和度来自"边框本身是低透明度的粗环"，GPU 开销为零。用 `blur(80px)` 在大屏上会掉帧。
- **渐变三停靠足够**。`#f2f6ff → #f6f5ff → #edf5ff` 三个近乎同色的冷调，
  120° 斜切；同色系微差是"有质感"和"有颜色"的分界线。
- **元信息行（01/02/03）承担免责声明的作用**。三个技术名词先给出，让懂行的人立刻确认
  "这是给我们的"，不需要往下滚。

---

## 3. 按钮

```css
.site-button {
  display: inline-flex; align-items: center; justify-content: center; gap: 16px;
  min-height: 48px; padding: 10px 24px;
  border: 1px solid transparent; border-radius: var(--r-md);
  font-size: 14px; font-weight: 600;
  transition: background .18s, box-shadow .18s, border-color .18s;
}
.site-button--primary {
  background: var(--primary); color: #fff;
  box-shadow: 0 5px 14px rgba(101, 121, 238, .145);
}
.site-button--primary:hover {
  background: var(--primary-hover);
  box-shadow: 0 7px 18px rgba(101, 121, 238, .196);
}
.site-button--small { min-height: 42px; padding: 8px 18px; }
```

- **48px 高**是触控友好的下限，也是视觉上"可信"的尺寸；40px 会显轻。
- **hover 只加深 8–10% 并加一点阴影**，不做位移、不做缩放。按钮动多了显廉价。
- 组内**主按钮永远只有一个**。三个按钮并列时，另外两个必须是白底描边，
  第三个退成纯文字链接（`.hero-link`）。

---

## 4. 页脚

```css
.site-footer { padding: 64px 0 40px; border-top: 1px solid var(--line); background: #fff; }
.footer-grid { display: grid; grid-template-columns: minmax(240px, 1.4fr) 3fr; gap: 64px; }
.footer-brand p { max-width: 340px; margin: 20px 0 0; color: var(--muted); font-size: 14px; line-height: 1.9; }
.footer-links { display: grid; grid-template-columns: repeat(3, minmax(100px, 1fr)); gap: 64px; }
.footer-links div { display: grid; align-content: start; gap: 12px; }
.footer-links strong { margin-bottom: 5px; font-size: 14px; }
.footer-links a { color: var(--muted); font-size: 13px; transition: color .18s; }
.footer-links a:hover { color: var(--primary); }
```

- **白底页脚**。整站底色是 `#f5f7fc`，页脚翻成白色形成"落地"感，比加深色页脚轻。
- 品牌区占 `1.4fr`、链接区 3 列等宽，右侧列间距 64px——比常见的 32px 松，
  这是页脚显"从容"的关键，代价是移动端要立刻折成一列。
- 页脚链接 13px，比正文小一档且用 `--muted`，不参与主视觉竞争。
