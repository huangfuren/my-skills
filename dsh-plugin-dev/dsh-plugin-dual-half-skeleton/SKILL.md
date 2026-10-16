---
name: dsh-plugin-dual-half-skeleton
description: >-
  Use when starting a DSH plugin's UI from scratch, or when a plugin's browser half never
  loads, its host half never reaches the page, or a client build fails on an import. Covers
  the two-half package layout (dsh.bundle.patch inserts the host half as a loader row,
  dsh.client loads the browser half), the asymmetric export shapes (host = ESM
  `export function apply`, client = CJS `module.exports`), the tsdown chain that compiles
  React + Tailwind into one client.js wrapped in the __ModuleLoader__ closure factory, the
  platform-module allowlist that is a hard build boundary (react must stay an injected
  require), the CSS import-order cascade rule, and i18n dictionary registration.
license: MIT
compatibility: >-
  DSH plugin packages with a client half (dsh.client.platform = "web"). Package fields verified
  against the installed dsh 0.2.0-rc.2 runtime; build-config semantics read from
  packages/client/tsdown.client.ts and packages/client/web/src/platform.ts (0.1.7-rc.2 checkout).
---

# DSH 双半边插件骨架

目标：从零建一个带 UI 的 DSH 插件，一次把「宿主半 + 浏览器半 + 构建链」摆正，
不靠猜、不靠反复重启试。

现有 skill 都假设**插件已经在跑**；这一篇只回答「怎么开始」。

## 双半边分工

|  | 宿主半 host | 浏览器半 client |
|---|---|---|
| 跑在 | Node（主进程 / 服务端） | 浏览器渲染进程 |
| 入口 | `package.json` → `main` → `lib/index.js` | `exports["./client"]` → `lib/client.js` |
| 谁把它装进去 | `dsh.bundle.patch` 在 loader 配置里插一行 | `dsh.client` 段 |
| 模块形态 | **ESM**（`"type": "module"`） | **CJS 单文件** |
| 导出形态 | `export const name` / `export const inject` / `export function apply` | `module.exports = { name, inject, apply }` |
| 拿得到什么 | cordis 服务：`tools` / `settings` / `sessionProjections` … | `ctx.slots` / `ctx.locale` + 槽位 props |
| 干什么 | 折叠数据、注册投影、开路由、注册工具 | 注册插槽、渲染组件、读投影值 |

**两个半边不共享运行时**：客户端半边不能 `import` 宿主半边的任何值（见
[references/bundle-purity.md](references/bundle-purity.md) 的纯净门）。数据只能走两条路 ——
宿主已认证的 `/api` 路由（配套 skill `dsh-plugin-fetch-route`），或投影值流（配套 skill
`dsh-session-projection`）。

---

## 一、`package.json`

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
    "./package.json": "./package.json"
  },
  "files": ["lib/index.js", "lib/index.d.ts", "lib/client.js", "cordis.patch.yml"],
  "engines": { "node": "^22.19.0 || >=24.0.0" },
  "dsh": {
    "bundle": { "patch": "./cordis.patch.yml" },
    "client": {
      "inject": ["@deepseek-ai/dsh-client-ui-conversation", "@deepseek-ai/dsh-client-ui-layout"],
      "platform": "web"
    },
    "compatibility": {
      "dshReleases": { "0.1.7-rc.2": "compatible", "0.2.0-rc.2": "compatible" }
    }
  },
  "peerDependencies": {
    "@deepseek-ai/cordis": "^4.0.4",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "peerDependenciesMeta": {
    "react": { "optional": true },
    "react-dom": { "optional": true }
  }
}
```

四个易混点：

| 字段 | 它**不是**什么 | 它**是**什么 |
|---|---|---|
| `dsh.bundle.patch` | 不是「有 UI 就必须有」 | 只有宿主半需要**在启动时装配**（注册服务/路由/配置行）时才需要；缺了就得手工在 profile 的 `cordis.patch.yml` 里 insert |
| `dsh.client.inject` | **不是** cordis 服务名清单 | 是**要随插件预加载的客户端包**名单（模块表里的包） |
| `dsh.client.platform` | 不是可选优化 | `"web"` 是 Web 与桌面端加载浏览器半的**唯一开关**；桌面端只加载 `platform === "web"` 的包 |
| `dsh.compatibility.dshReleases` | 不是给宿主做校验用的 | 是**声明**（供市场和兼容性阅读）；宿主实际校验的是 `peerDependencies`，`engines.dsh` 不校验 |

`dsh.client.immediately: true` 可让浏览器半在启动时就装入而非等到某个页面 ——
`dsh-context` 没用它（按需加载更省），两者都合法。

---

## 二、两个半边的不对称导出形态

**这是最容易错的一处**：同一个插件，宿主半用 ESM，浏览器半用 CJS。

宿主半 `src/host/index.ts`：

```ts
export const name = 'my-plugin'
// 顶层 inject 只列「确定存在」的服务；不确定的走 ctx.inject([...]) 延迟注入
export const inject = ['sessionProjections']
export function apply(ctx, config) { /* … */ }
```

浏览器半 `src/client/index.ts`：

```ts
function apply(ctx) { /* … */ }

// 浏览器半是 CJS —— 宿主外壳用「var module = { exports: {} } … return module.exports」
// 包住它（见 bundle-purity.md 的 ModuleLoader 三件套）
module.exports = {
  name: 'my-plugin',
  inject: ['slots', 'locale'],
  apply,
}
```

**`inject` 是硬闸门**：名单上任一服务缺席，这个 fiber 会**永远停在 INACTIVE**，
插件完全不加载 —— 表现为「什么都不发生，也没有报错」。所以：

- 确定存在的服务 → 顶层 `inject`
- 可能缺席的服务（老宿主、可选伴生包）→ `ctx.inject(['configForms'], (c) => { … })`，
  服务后到也能生效，缺失则这段静默 no-op

---

## 三、客户端 bundle：两条路

| 路线 | 形态 | 什么时候用 |
|---|---|---|
| **A 轻** | 手写 `client.js`，IIFE 包一层 `module.exports`，无构建 | 单文件、少量原生 DOM 或 `h()` 调用的小插件（本机 `dsh-outline` / `dsh-localsend` 就是这么写的） |
| **B 重** | `src/` 源码 + tsdown 构建链 | React 组件树、Tailwind、多文件、需要 CSS Modules 的插件（`dsh-context`、`dsh-grafana`、`dsh-mindmap`） |

路线 A 的最小骨架见 `dsh-settings-page/references/skeleton.md` §3.1。
路线 B 见 [references/skeleton.md](references/skeleton.md) 与
[references/bundle-purity.md](references/bundle-purity.md)。

路线 B 的四个必守点（错了就是白屏 + 控制台一句看不懂的错）：

1. **产物必须是单文件 `lib/client.js`**，`format: ['cjs']`、`platform: 'browser'`
2. **客户端配置的 `clean` 必须 `false`** —— 默认 `clean` 会把同一 `outDir` 下已产出的宿主半删掉
3. **必须套 `__ModuleLoader__` 闭包工厂**（banner / intro / footer 三件套，字符串要一模一样）
4. **平台模块白名单是硬边界**：白名单里的说明符必须**留给注入的 `require`**，
   其余 `@deepseek-ai/*` 值导入一律构建报错

---

## 四、CSS：import 顺序就是级联顺序

同权重规则的胜负由 `import` 顺序决定。约定排法：

```ts
import './styles/tailwind.css'   // ① Tailwind utilities 永远第一
import './styles/base.css'       // ② 基础层
import './styles/panel.css'      // ③ 各组件层，后者压前者
import './styles/modal.css'
```

`dsh-context` 用 18 个 CSS 严格按这个顺序排（`src/client/index.ts:27-45`）。
Tailwind **只编译入口那一张表**（`tailwind.css`），其余保持普通 CSS。

三种 CSS 通道由构建链自己实现（不装 `@tsdown/css`）：

| 写法 | 得到什么 |
|---|---|
| `x.module.css` | 哈希类名 + 默认导出类名映射，并在工厂执行时注入带标签的 `<style>` |
| `x.css?inline` | 只导出编译后的 CSS 字符串（生命周期由你自己的 effect 管） |
| `x.css` | 直接注入带标签的 `<style>` |

---

## 五、i18n 词典注册（骨架的一部分）

```ts
const NS = 'my-plugin'

ctx.effect(() => {
  return ctx.locale.register(NS, { zh: DICT_ZH, en: DICT_EN })
}, 'my-plugin: dictionaries')
const t = ctx.locale.bind(NS)
```

槽位注册时把 `locale` 与 **label thunk** 一起给：

```ts
ctx.slots.inject('conversation.view', () => ctx.slots.register(
  { name: 'conversation.view', id: 'mine', order: 20, locale: NS, label: () => t('tab.mine') },
  props => h(MyView, props),
))
```

`label` 必须是 thunk（`() => t(key)`），否则语言切换不会重渲染。

---

## 常见偏差

| 偏差 | 后果 |
|---|---|
| 浏览器半写成 ESM `export default` | 外壳读不到 `apply`，插件静默不加载 |
| 顶层 `inject` 写了可能缺席的服务 | fiber 停在 INACTIVE，**无报错**，整个插件失效 |
| `exports` 漏了 `"./client"` | 宿主找不到浏览器半 |
| `files` allowlist 漏了 `lib/client.js` | 发布包装不上；本地 `link:` 反而看不出来 |
| 客户端配置忘了 `clean: false` | 宿主半产物被删，宿主功能消失 |
| 把 react 打进 bundle | 页面出现两份 React，hooks 报错或渲染全乱 |
| import 了别的 `@deepseek-ai/*` 值 | 构建直接失败（纯净门），别去关掉这道门 |
| CSS import 顺序随意 | 样式互相覆盖，改了顺序才好 —— 而不是加 `!important` |
| `label` 给了字符串而非 thunk | 切语言不刷新 |

## 落地检查清单

- [ ] `type: "module"` + `main` + `exports["./client"]` + `files` 四处齐全
- [ ] `dsh.client.platform === "web"`
- [ ] `dsh.client.inject` 里是**包名**，不是服务名
- [ ] 宿主半 ESM 导出 `name` / `inject` / `apply`
- [ ] 浏览器半 CJS `module.exports = { name, inject, apply }`
- [ ] 顶层 `inject` 只列确定存在的服务，其余走 `ctx.inject([...])`
- [ ] 产物是单文件 `lib/client.js`，且顶部有 `window.__ModuleLoader__.load({ id, factory })`
- [ ] 客户端配置 `clean: false`
- [ ] `require()` 里只剩平台模块（grep 产物确认没有 `require("react")` 以外的意外项）
- [ ] CSS import 顺序：Tailwind → base → 组件层
- [ ] `label` 全部是 thunk
- [ ] 声明了 `peerDependencies`（宿主校验的是它，不是 `engines.dsh`）

## 参考实现

| 用途 | 位置 |
|---|---|
| 完整双臂骨架 + 构建链 + 纯净门（**最完整范例**） | `<dsh-context-checkout>`（v0.72.0 源码快照） |
| 官方客户端构建预设（构建语义的事实来源） | `…\packages\client\tsdown.client.ts` |
| 官方平台模块表 | `…\packages\client\web\src\platform.ts` |
| 手写 IIFE 形态的浏览器半（轻路线范例） | `<dsh-home>\profiles\desktop\node_modules\dsh-outline\client.js` |
| 已装产物（压缩后仍可 grep 定位） | `…\node_modules\dsh-context\lib\client.js`、`…\lib\index.js` |

> 路径前缀：`…\packages\client` = `<harness-checkout>\packages\client`
> （**0.1.7-rc.2 检出**）。已装宿主是 **0.2.0-rc.2** —— 读构建语义看检出可以，
> 判断**运行时行为**必须读已装副本。

> 取材许可：本 skill 的结构与配置语义取自 `bowenliang123/dsh-context`（**Apache-2.0**）
> 与官方预设 `packages/client/tsdown.client.ts`。文中代码均为**重写后的骨架**，
> 非整文件搬运；引用处已标注来源。

详细的清单骨架、构建配置与纯净门全文见
[references/skeleton.md](references/skeleton.md)（可复制骨架 + tsdown 配置）
与 [references/bundle-purity.md](references/bundle-purity.md)（平台模块表 + CSS 通道 + 排错）。

配套 skill：把会话数据流给浏览器见 `dsh-session-projection`；控件放哪见
`dsh-client-slot-placement`；会话标签页见 `dsh-conversation-view-tab`；设置页入口见
`dsh-settings-page`；「同服务多实例 + 每源独立凭据」见 `dsh-multi-source-config`。

配套 skill 补充：宿主侧随取随送数据的认证路由与冷读治理见 `dsh-plugin-fetch-route`；
宿主跨版本探测与基线降级见 `dsh-harness-compat-gate`；可选服务缺席时的延迟注入与
单活挂载守卫见 `dsh-plugin-robust-mount`。

总览与索引见 `dsh-plugin-dev-guide`。
