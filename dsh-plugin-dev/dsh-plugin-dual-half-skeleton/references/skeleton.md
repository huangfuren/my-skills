# 可复制骨架：双半边插件（含构建链）

按此骨架新建插件，得到：一个宿主半（折叠数据 / 注册服务）+ 一个浏览器半（React 组件树 +
Tailwind）+ 一条能产出单文件 `client.js` 的构建链。示例插件名统一用 `my-plugin`。

> 摘录来源：`bowenliang123/dsh-context` v0.72.0（Apache-2.0）。
> 本文件是**重写后的骨架**，不是整文件搬运；保留的是配置结构与关键注释的语义。

## 1. 目录

```
my-plugin/
├── package.json
├── cordis.patch.yml          # 宿主半需要在启动时装配时才有
├── tsdown.config.ts          # 路线 B 才有
├── tailwind.css              # Tailwind 入口（唯一被编译的那张表）
├── src/
│   ├── host/
│   │   ├── index.ts          # 宿主半入口（ESM）
│   │   ├── ...fold 等
│   ├── client/
│   │   ├── index.ts          # 浏览器半入口（CJS 产物）
│   │   ├── i18n.ts
│   │   ├── components/…
│   │   └── styles/
│   │       ├── tailwind.css
│   │       ├── base.css
│   │       └── …
│   └── shared/               # 两侧共用的**纯类型 + 常量**（两侧都会 inline 进去）
└── lib/                      # 产物：index.js / index.d.ts / client.js
```

`src/shared/` 只能放类型和纯函数字面量。它会被**分别 inline** 进两个产物 ——
放运行时状态就会得到两份互不相识的副本。

## 2. `package.json`

```json
{
  "name": "my-plugin",
  "version": "0.1.0",
  "type": "module",
  "main": "lib/index.js",
  "types": "lib/index.d.ts",
  "exports": {
    ".": { "types": "./lib/index.d.ts", "default": "./lib/index.js" },
    "./client": "./lib/client.js",
    "./package.json": "./package.json",
    "./locale/*.json": "./locale/*.json"
  },
  "files": [
    "lib/index.js", "lib/index.d.ts", "lib/client.js",
    "locale/*.json", "cordis.patch.yml", "README.md"
  ],
  "scripts": { "build": "tsdown", "typecheck": "tsc --noEmit" },
  "engines": { "node": "^22.19.0 || >=24.0.0" },
  "dsh": {
    "bundle": { "patch": "./cordis.patch.yml" },
    "client": {
      "inject": [
        "@deepseek-ai/dsh-client-connection",
        "@deepseek-ai/dsh-client-locale",
        "@deepseek-ai/dsh-client-ui-conversation",
        "@deepseek-ai/dsh-client-ui-settings"
      ],
      "platform": "web"
    },
    "compatibility": { "dshReleases": { "0.1.7-rc.2": "compatible", "0.2.0-rc.2": "compatible" } }
  },
  "dependencies": { "zod": "^4.4.3" },
  "peerDependencies": {
    "@deepseek-ai/cordis": "^4.0.4",
    "@deepseek-ai/dsh-client-ui-primitives": ">=0.1.7-rc.2",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "peerDependenciesMeta": {
    "@deepseek-ai/dsh-client-ui-primitives": { "optional": true },
    "react": { "optional": true },
    "react-dom": { "optional": true }
  }
}
```

注意：`dependencies` 里放**运行时真的要装**的东西（`zod`）。其余全部 `peerDependencies` ——
它们会由宿主提供或 inline 进 bundle，写成 `dependencies` 会让构建把它们当外部依赖留下。

## 3. 宿主半 `src/host/index.ts`

```ts
export const name = 'my-plugin'
// 顶层只列确定存在的服务。名单上任一缺席 → fiber 停在 INACTIVE，插件完全不加载。
export const inject = ['sessionProjections']

export function apply(ctx, config) {
  // 可选服务：延迟注入，服务后到也生效，缺失则整段 no-op
  ctx.inject(['settings'], (sctx) => {
    const settings = sctx.settings
    if (typeof settings?.describe !== 'function') return
    // …
  })

  ctx.sessionProjections.register(myDefinition)
}
```

宿主半的 `Config` 若要在设置页读写，字段必须导出并 `.volatile()`（见配套 skill
`dsh-settings-page`）。

## 4. 浏览器半 `src/client/index.ts`

```ts
import { createElement as h } from 'react'
import { DICT_EN, DICT_ZH } from './i18n'
import { makeMyView } from './components/myView'

// import 顺序 = 级联顺序。Tailwind 永远第一，随后 base，再各组件表。
import './styles/tailwind.css'
import './styles/base.css'
import './styles/myView.css'

const NS = 'my-plugin'

function apply(ctx) {
  ctx.effect(() => ctx.locale.register(NS, { zh: DICT_ZH, en: DICT_EN }), 'my-plugin: dictionaries')
  const t = ctx.locale.bind(NS)

  const MyView = makeMyView(t)

  ctx.effect(() => ctx.slots.inject('conversation.view', () => ctx.slots.register(
    // order 20 渲染在 Chat(0) 与 Trajectory(10) 之右；label 必须是 thunk
    { name: 'conversation.view', id: 'mine', order: 20, locale: NS, label: () => t('tab.mine') },
    props => h(MyView, props),
  )), 'my-plugin: placement')
}

// 浏览器半是 CJS：外壳用 var module = { exports: {} } … return module.exports 包住它
module.exports = {
  name: 'my-plugin',
  inject: ['slots', 'locale'],
  apply,
}
```

## 5. `cordis.patch.yml`

只写「宿主半需要在启动时装配」的行。最小形态：

```yaml
- insert:
    - id: my-plugin
```

（具体插入位置取决于你要挂到哪个 group；不确定时先不写这个文件，
让插件作为普通 loader row 加载。）

## 6. `tsdown.config.ts`

两条配置，一个数组。**顺序有意义**：宿主半先出（`clean: true`），客户端半后出（`clean: false`）。

```ts
import { defineConfig } from 'tsdown'

const REQUESTED = [
  // 平台模块表里的说明符 + 本包追加的 dsh.client.external
  'react', 'react/jsx-runtime', 'react-dom',
  '@deepseek-ai/dsh-client-ui-primitives',
]
const isRequested = (s: string) => REQUESTED.includes(s)

export default defineConfig([
  {
    name: 'my-plugin',
    entry: { index: 'src/host/index.ts' },
    outDir: 'lib',
    format: ['esm'],
    platform: 'node',
    target: 'es2024',
    dts: true,          // 宿主半的类型是别的插件要编译对照的契约
    clean: true,
    minify: true,
    deps: {
      // 生产依赖留在磁盘上做 import；其余 inline
      neverBundle: (s) => isProductionDependency(s),
      alwaysBundle: (s) => !isBuiltin(s) && !isProductionDependency(s),
    },
  },
  {
    name: 'my-plugin/client',
    entry: { client: 'src/client/index.ts' },
    outDir: 'lib',
    format: ['cjs'],
    platform: 'browser',
    target: 'es2024',
    dts: false,         // .d.cts 会把 banner/footer 包进去，解析不了
    clean: false,       // ← 忘了这行会删掉上面刚产出的宿主半
    minify: true,
    sourcemap: true,    // 浏览器 profile 工具要靠它；npm 包通过 files allowlist 不带 .map
    deps: {
      // 请求到的说明符留在 require 里（外部），其余全部 inline
      neverBundle: isRequested,
      alwaysBundle: (s) => !isRequested(s),
      // 让「其余全部 inline」可审计：新出现的第三方依赖必须显式列进来
      onlyBundle: ['some-dep'],
    },
    define: {
      // CJS 浏览器产物承载不了这些 node 惯用法；不替换，工厂会在启动时抛 ReferenceError
      'process.env': '{}',
      'process.env.NODE_ENV': JSON.stringify('production'),
      'import.meta.env.MODE': JSON.stringify('production'),
      'import.meta.env': JSON.stringify({ MODE: 'production' }),
    },
    plugins: [
      purityGate(),
      ...cssChannels(),
      tailwindChannel(),
    ],
    outputOptions: {
      entryFileNames: 'client.js',
      comments: { legal: true, annotation: false, jsdoc: false },
      // ModuleLoader 三件套 —— 字符串必须与外预设一致
      banner: `window.__ModuleLoader__.load({ id: "my-plugin", factory: (require) => {`,
      intro: 'var module = { exports: {} }; var exports = module.exports;',
      footer: 'return module.exports; } });',
    },
  },
])
```

纯净门与 CSS 通道的完整实现见 [bundle-purity.md](bundle-purity.md)。

## 7. `tailwind.css`（入口）

```css
@import "tailwindcss";

/* 只在这里放 utilities 相关；组件样式进各自的 .css */
```

扫描候选类名靠 `@tailwindcss/node` 的 `Scanner`：它会读**源码文件**里的类名字符串。
所以动态拼类名（`` `text-${size}` ``）扫不到 —— 用完整字面量或用普通 CSS。

## 8. 落地顺序

1. 先只做宿主半：`package.json` + `src/host/index.ts`，`tsdown` 跑通产出 `lib/index.js`
2. 加 `dsh.client` 段与浏览器半，先渲染一个静态 `div`，确认页面上出现
3. 再接数据（投影值 / `/api` 路由）
4. 再接 CSS 与 i18n
5. 用 `dsh-client-slot-placement` 的清单核对落位与视觉

## 9. 常见偏差

| 偏差 | 后果 |
|---|---|
| 客户端配置 `clean` 忘了改 `false` | 宿主半产物被删 |
| ModuleLoader banner/footer 抄错一个字符 | 页面报 `__ModuleLoader__` 相关错，或插件根本不注册 |
| `onlyBundle` 不维护 | 依赖悄悄变大，产物体积失控且没人发现 |
| `define` 漏了 `import.meta.env`（只写 `.MODE`） | 有库会在 `import.meta.env ? … : …` 的真值探测上崩 |
| `src/shared/` 放了可变状态 | 两侧各一份，改一边另一边不知道 |
| CSS 顺序随意 | 组件样式互相压，只能靠 `!important` 硬顶 |
