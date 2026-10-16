# 客户端 bundle：平台模块表、纯净门、CSS 通道

这份文件是 SKILL.md §三 的展开。全部语义来自官方客户端构建预设
`<harness-checkout>\packages\client\tsdown.client.ts`
（0.1.7-rc.2 检出）与其平台表 `packages/client/web/src/platform.ts`；
`dsh-context` 的 `tsdown.config.ts`（v0.72.0）是**照它复刻**的一个可用实例。

## 1. 为什么是「闭包工厂」形态

官方预设文件头的原话（语义转述）：

> 产物是一个**闭包工厂**：bundle 调用 `window.__ModuleLoader__.load({id, factory})`，
> 并通过注入的 `require` 解析外部模块（loader 模块表 —— cordis 的 DI 实体，
> **没有 globals，没有 import map**）。CSS 由 bundle 内的 lightningcss 编译：
> `x.module.css` 产出哈希类名映射并在工厂执行时注入一个带标签的 `<style>`；
> `x.css?inline` 导出编译后的文本供插件自己的生命周期 effect 使用。

由此推出两条铁律：

1. 产物**不是** ESM 模块，`format` 必须是 `cjs`，且必须被三件套包住。
2. 平台模块**只能**通过注入的 `require` 拿到 —— 打进 bundle 就会得到第二份实例。

## 2. 三件套（字符串必须一致）

```ts
outputOptions: {
  entryFileNames: 'client.js',
  banner: `window.__ModuleLoader__.load({ id: ${JSON.stringify(id)}, factory: (require) => {`,
  intro:  'var module = { exports: {} }; var exports = module.exports;',
  footer: 'return module.exports; } });',
}
```

非入口 chunk（异步分包）在 `factory` 前多一个 `chunk` 键，且需要
`chunkFileNames: 'client.[name].js'`：

```ts
banner: (chunk) =>
  `window.__ModuleLoader__.load({ id: ${JSON.stringify(id)}, `
  + `${chunk.isEntry ? '' : `chunk: ${JSON.stringify(chunk.fileName)}, `}`
  + `factory: (require) => {`
```

`intro` 里的 `var module = { exports: {} }` 就是「浏览器半为什么写 CJS
`module.exports`」的答案 —— 外壳在工厂里造了这对变量，你的源文件直接写 CJS 即可。

## 3. 平台模块表（硬边界）

官方表（`packages/client/web/src/platform.ts`，0.1.7-rc.2，9 项）：

```ts
export const PLATFORM_MODULES = [
  'react', 'react/jsx-runtime', 'react-dom', 'react-dom/client',
  '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-store',
  '@deepseek-ai/dsh-client-ui-slots',
  '@deepseek-ai/dsh-client-ui-primitives',
  '@deepseek-ai/dsh-client-ui-dockkit',
] as const

/** 工厂在 shell 启动前预加载的客户端 bundle 说明符。 */
export const PRELOADED_CLIENT_EXTERNALS = [] as const
```

`dsh-context` 实际用的是这张表的一个**子集 + 自己的追加**：

```ts
const PLATFORM_MODULES = [
  'react', 'react/jsx-runtime', 'react-dom',
  '@deepseek-ai/dsh-client-ui-primitives',
]
const requested = new Set([...PLATFORM_MODULES, ...(pkg.dsh?.client?.external ?? [])])
```

**用法**：不要照抄这 9 项。正确做法是 ——

1. 读**已装宿主**里的平台表（或官方检出的 `platform.ts`）
2. 只保留你**真的会 `import`** 的项
3. 用 `dsh.client.external` 追加非默认项
4. 把两者并成 `requested`，`neverBundle: isRequested` / `alwaysBundle: !isRequested`

判断逻辑一句话：**`require()` 请求到的说明符留在外部，其余全部 inline。**
理由（官方注释）：模块表答不上来的 `require()` 是**必然的运行时抛错**。

## 4. 纯净门

一个 `resolveId` 插件，把「模块边规则」搬到构建期。三类放行 + 一条兜底：

```ts
// 1) 平台表 / 本包 dsh.client.external 里的 → 放行（external 优先）
// 2) 官方 vendored 库（无共享运行时身份）→ 放行，inline
const VENDORED_LIBRARY = /^@deepseek-ai\/(cosmokit|schemastery)(\/|$)/

// 3) 只含 wire/type 层、没有共享运行时实例的包 → 放行，inline 才是本意
const INLINE_SAFE = /^@deepseek-ai\/dsh-(host-apiproxy|file-reference|session|llm|tools|brand|util-workspace-path)(\/|$)/

// 4) 生成的 /remote 贡献 → 放行，inline
const GENERATED_REMOTE = /^@deepseek-ai\/dsh-[a-z0-9]+(?:-[a-z0-9]+)*\/remote$/
```

四条都不命中时，**抛构建错误**（原文）：

> client bundle purity: `"<specifier>"` is not in the default client externals or
> `<pkg>`'s `dsh.client.external`, an inline-safe wire layer, or a generated `/remote`
> contribution — **cross-plugin value imports are forbidden**; declare a non-default module
> request or collaborate through cordis services (type-only imports are erased and never reach
> this gate)

理解要点：

- 放行的是 **type-only import 之外**的东西。`import type { X }` 会被 TS 擦除，
  根本到不了这道门，所以类型可以随便跨包引用。
- **跨插件协作走 cordis 服务**，不要 `import` 别人的值 —— 要么 inline 出第二份运行时实例，
  要么 `require` 一个模块表答不上来的说明符。
- `INLINE_SAFE` / `VENDORED_LIBRARY` 的 **名单要跟着宿主基线走**。
  你的插件若声明更低的基线，就把这几条正则抄成你自己的常量，而不是从别人包里 import。

## 5. CSS 通道

三个虚拟模块通道，都在 bundle 内完成（**不装 `@tsdown/css`**）：

| 源写法 | 虚拟前缀 | 产物 |
|---|---|---|
| `x.module.css` | `\0dsh-css:` | 哈希类名映射（`pattern: '[hash]_[local]'`）+ 注入 `<style>` |
| `x.css?inline` | `\0dsh-inline-css:` | `export default "<编译后 CSS>"` |
| `x.css` | `\0dsh-global-css:` | 注入 `<style>` |

两个必守点：

1. **虚拟 id 不能以 `.css` 结尾** —— tsdown 自己的 css-pipeline 守卫是按这个后缀匹配的。
   所以统一加 `.mjs` 后缀（`CSS_VIRTUAL_SUFFIX = '.mjs'`）。
2. **必须 `addWatchFile(真实文件路径)`** —— 否则虚拟 id 把物理样式表从 watch 图里藏掉，
   `--watch` 改了 CSS 不重建。

注入器的去重方式（同一张表被多次求值也只挂一个标签）：

```ts
const tagId = `${id}/${basename(fileId)}`
if (document.querySelector('style[data-plugin-css=' + JSON.stringify(tagId) + ']') === null) {
  const tag = document.createElement('style')
  tag.dataset.plugin = id
  tag.dataset.pluginCss = tagId
  tag.textContent = css
  document.head.appendChild(tag)
}
```

## 6. Tailwind 通道

**只有一张表被编译**（`tailwind.css`），其余走普通 CSS 通道：

```ts
const TAILWIND_ENTRY = 'tailwind.css'

const compiler = await compileTailwind(source, {
  base: dirname(fileId),
  onDependency: (file) => { loader.addWatchFile(file) },
})
const scanner = new Scanner({ sources: compiler.sources })
const candidates = scanner.scan()
for (const file of scanner.files) loader.addWatchFile(file)   // 类名变了也要重建
return compiler.build(candidates)
```

判分支就一句：`basename(fileId) === TAILWIND_ENTRY` 时先编译成 CSS 字符串，
否则把 `Buffer` 直接交给 lightningcss（它的 binding 读 TypedArray）。

## 7. `define` 替换

CJS 浏览器产物承载不了 node 惯用法。四个键都要写：

```ts
define: {
  'process.env': '{}',
  'process.env.NODE_ENV': JSON.stringify(NODE_ENV),
  'import.meta.env.MODE': JSON.stringify(NODE_ENV),
  'import.meta.env': JSON.stringify({ MODE: NODE_ENV }),
}
```

**为什么第四个（裸的 `import.meta.env`）不能省**：有库写的是
`import.meta.env ? import.meta.env.MODE : …`。只替换 `.MODE` 的话，那个真值探测会活下来
变成一个空的 `import.meta`，构建期就报 `EMPTY_IMPORT_META`，或者运行时崩。

## 8. 产物自检（改完构建链跑一遍）

```bash
# 1) 产物是不是单文件、是不是工厂形态
head -c 200 lib/client.js
#    期望看到 window.__ModuleLoader__.load({ id: "...", factory: (require) => {

tail -c 120 lib/client.js
#    期望看到 return module.exports; } });

# 2) require() 里只剩平台模块
grep -o 'require("[^"]*")' lib/client.js | sort -u

# 3) 没有第二份 react
grep -c "react-dom/client" lib/client.js   # 期望 0 或只在 require 里

# 4) 宿主半没被误删
ls -la lib/index.js lib/client.js
```

第 2 步是**最有价值的一条**：`require()` 列表就是「这个 bundle 依赖宿主提供什么」的
完整清单。出现意料之外的包名，说明它该进 `onlyBundle` 或该改走 cordis 服务。

## 9. 排错对照

| 现象 | 先查 |
|---|---|
| 页面白屏，控制台提 `__ModuleLoader__` | 三件套字符串（banner/intro/footer）是否与外预设逐字一致 |
| 插件"没有任何反应"且无报错 | 浏览器半顶层 `inject` 里写了可能缺席的服务 → fiber 停在 INACTIVE |
| React hooks 报错 / 渲染错乱 | 是否有两份 React（grep 产物） |
| 构建报 `client bundle purity` | 你 import 了非白名单的 `@deepseek-ai/*` 值 → 改走 cordis 服务 |
| 构建报 `EMPTY_IMPORT_META` | 少写了裸的 `import.meta.env` 替换 |
| 改了 CSS 不生效（`--watch`） | CSS 通道漏了 `addWatchFile(真实路径)` |
| Tailwind 类名不生效 | 类名是动态拼的，Scanner 扫不到 → 用完整字面量 |
| `lib/index.js` 莫名消失 | 客户端配置 `clean: true` 抹掉了同 `outDir` 的宿主半产物 |
