# 性能与 SEO：源站的四个缺陷及修法

源站视觉做得好，工程配置有明显欠账。照抄视觉，但**不要照抄部署**。

## 实测数据（2026-10-27，直连）

| 项 | 实测值 | 应有值 |
|---|---|---|
| `index-BdeuzaEo.js` | `Content-Length: 352664`，无 `Content-Encoding` | gzip 后约 90–110KB（估算，压缩比 3.2–3.9×） |
| `index-BgxvFayx.css` | 66,861 字节，无 `Content-Encoding` | gzip 后约 11KB |
| 哈希资源缓存 | 只有 `ETag`，无 `Cache-Control` | `public, max-age=31536000, immutable` |
| `/robots.txt` | 返回 724 字节 `index.html` 外壳 | 独立纯文本 |
| `/sitemap.xml` | 同上，被 SPA fallback 吞掉 | 独立 XML |
| 首屏截图 | `/images/product/workbench.png`，1600×632，62KB | 可再出 webp，约 25KB |

结论：**三个纯服务端配置项（压缩、缓存、fallback 例外）就能省掉约 65% 首屏字节，
且不需要改一行前端代码。**

---

## 缺陷 1：未开压缩

症状：`curl -I -H "Accept-Encoding: gzip"` 返回里**没有** `Content-Encoding`。

nginx 最小修复：

```nginx
# /etc/nginx/nginx.conf 的 http {} 内
gzip on;
gzip_comp_level 5;          # 6 以上边际收益极低，CPU 反而明显
gzip_min_length 1024;
gzip_vary on;
gzip_proxied any;
gzip_types text/plain text/css text/xml application/javascript
           application/json application/xml image/svg+xml;
```

条件允许时上 brotli（需 `ngx_brotli` 模块），比 gzip 再省 15–20%：

```nginx
brotli on;
brotli_comp_level 5;
brotli_types text/css application/javascript application/json image/svg+xml;
```

注意：**不要压缩图片**（png/jpg/webp 已压缩，二次压缩可能变大）。

验证：

```bash
curl -sI -H 'Accept-Encoding: gzip,br' https://example.com/assets/index-xxx.js \
  | grep -i 'content-encoding\|content-length'
```

---

## 缺陷 2：哈希资源没有强缓存

症状：构建产物文件名已带内容指纹（`index-BdeuzaEo.js`），却只给 `ETag`。
每次访问浏览器都要发一次条件请求，白白多一个 RTT。

```nginx
# 带指纹的构建产物：一年强缓存
location /assets/ {
    add_header Cache-Control "public, max-age=31536000, immutable";
    try_files $uri =404;
}

# 入口 HTML 与配置：永不缓存
location = /index.html {
    add_header Cache-Control "no-cache, must-revalidate";
}
```

关键区分：**带指纹的可以永久缓存，不带指纹的必须每次校验**。
把 `index.html` 也设成强缓存是最常见的发布事故来源——用户会一直拿到旧入口、
引用已删除的 JS 文件，白屏。

---

## 缺陷 3：纯客户端渲染，SEO 为空

症状：`/robots.txt`、`/sitemap.xml` 都命中了 SPA fallback，返回同一份 724 字节外壳；
博客 `/blog`、文档 `/docs` 的实际内容只在 JS 里，搜索引擎与分享卡片抓不到。

修复按代价排序：

| 方案 | 代价 | 效果 |
|---|---|---|
| **构建期预渲染**（`vite-plugin-prerender` / `vite-ssg`） | 低，改构建配置 | 静态路由出真 HTML，博客/文档走路由清单生成 |
| **混合**：官网静态化，控制台仍 SPA | 中 | 推荐——搜索引擎只看官网与文档 |
| 运行时 SSR（Nuxt / Next） | 高，需 Node 常驻 | 全站可索引，运维复杂度上升 |
| 什么都不做，只补 robots/sitemap | 极低 | 至少别把爬虫挡在门外 |

至少先做这两件事：

```nginx
location = /robots.txt { try_files $uri =404; }
location = /sitemap.xml { try_files $uri =404; }
```

```txt
# robots.txt
User-agent: *
Allow: /
Disallow: /account
Disallow: /login
Sitemap: https://example.com/sitemap.xml
```

预渲染路由清单（Vite 项目常见写法）：

```js
// vite.config.js
import prerender from 'vite-plugin-prerender'
export default {
  plugins: [prerender({
    staticDir: 'dist',
    routes: ['/', '/product', '/download', '/about', '/docs', '/blog'],
  })],
}
```

细节：预渲染会为每个路由生成独立 `index.html`，**每个页面要有自己的 `<title>` 与
`<meta name="description">`**，否则预渲染只是换了个白屏时机。博客详情页建议
构建期从接口 dump 一份 JSON 再批量生成。

---

## 缺陷 4：对比度未达 AA

| 组合 | 实测 | 标准 | 判定 |
|---|---|---|---|
| `#273451` on `#f5f7fc`（正文） | 11.55:1 | 4.5:1 | ✓✓ 优秀 |
| `#66758e` on `#f5f7fc`（辅助） | 4.35:1 | 4.5:1 | ⚠ 差 0.15 |
| `#7a88a1` on `#f5f7fc`（元信息） | 3.34:1 | 4.5:1 | ✗ 不达标 |
| `#fff` on `#6579ee`（主按钮） | 3.80:1 | 4.5:1 | ✗ 不达标 |
| `#6579ee` on `#f5f7fc`（大标题关键词） | 3.55:1 | 3:1（大字） | ✓ |

修法见 [design-tokens.md](design-tokens.md) 的「对比度修正」：主按钮底改 `#5063d6`
（5.13:1）、辅助文字改 `#5a6880`（5.26:1）。**主色本身不用动**，只调整它承载白字的场景。

自查工具：

```js
// 对比度速算（WCAG 2.1）
const lum = h => {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255)
    .map(c => c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const cr = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05) }
```

---

## 另外三项（非缺陷，但可再压）

1. **首屏截图出 webp/avif**：`<picture>` 包一层，PNG 兜底。1600×632 的
   PNG 62KB → webp 约 25KB。同时**必须有 `width`/`height`**，否则产生 CLS。
2. **关键 CSS 内联**：首屏 hero 的样式（约 3–4KB）内联进 `<head>`，
   其余 CSS 异步加载。这个站的 CSS 只有 65KB，收益有限，但首屏 paint 会早 100–200ms。
3. **字体不加载就删掉声明**：写了 `Inter` 却不加载，等于把观感交给用户机器上的
   偶然安装。要么自托管子集，要么老老实实用系统栈。

---

## 验收清单

```bash
# 1. 压缩是否生效
curl -sI -H 'Accept-Encoding: gzip,br' https://example.com/assets/index-xxx.js \
  | grep -i content-encoding

# 2. 强缓存是否生效（应看到 immutable）
curl -sI https://example.com/assets/index-xxx.js | grep -i cache-control

# 3. HTML 是否禁止缓存
curl -sI https://example.com/ | grep -i cache-control

# 4. robots / sitemap 是否独立存在（不应返回 text/html）
curl -sI https://example.com/robots.txt | grep -i content-type
curl -s  https://example.com/robots.txt | head -3

# 5. 首屏 HTML 是否含真实正文（预渲染是否生效）
curl -s https://example.com/ | grep -c '<h1'
```

最终以 Lighthouse（Performance / SEO / Accessibility）或 Chrome 的
Coverage 面板复核，不要只看上面几条命令——命令只能证明"配置生效"，
不能证明"用户感受变好"。
