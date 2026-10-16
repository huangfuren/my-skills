---
name: dsh-settings-page
description: >-
  Use when a DSH plugin needs its own page inside the Settings dialog (a left-nav
  entry such as Grafana / 思维脑图), a tab inside the 内置插件 section, a
  configuration card that reads and writes the plugin's own settings namespace, or
  when such an entry never appears or appears in the wrong host generation. Covers
  the three-generation slot fallback (settings.section -> settings.plugins.tab ->
  settings.plugin.item), the host-half namespace registration (0.1.5 `scope` vs
  0.1.7+ `describe`/`update`), the client-half service fallback
  (`remote.settings` / `connection.api.settings`), nav order and icon rules, the
  volatile two-track field split (bound fields remount the entry, preference fields
  commit in place), `autoGenerate`, and the gotchas that make a page silently
  never render.
license: MIT
compatibility: >-
  DSH client plugins (dsh.client.platform = "web") that also ship a host half
  (index.js). Slot names, kinds and options verified against dsh 0.2.0-rc.2
  desktop (@deepseek-ai/dsh-client-ui-settings, -ui-settings-general,
  -ui-settings-plugins, -ui-renderer) and the 0.1.7-rc.2 source checkout;
  cross-checked against dsh-grafana 0.18.1 and dsh-mindmap 0.17.0.
---

# DSH 插件设置页

一句话结论：**「设置里多一个左栏条目」= 客户端半的一次 `settings.section` 插槽注册**
（`kind: list`、`scope: root`）。但要让这一页真的能读写自己的配置，还需要**宿主半注册一个
同名 settings 命名空间**——两半缺一不可：**插槽给你入口，命名空间给你数据**。

反过来也成立：只导出 `Config` 的插件**不是没有设置页**——`autoGenerate` 缺省为 `true`，
宿主可为「没有自定义页」的插件自动生成一页。自动页与自定义页二选一，不会同时出现。

## 四条半进设置页的路

| 路 | 插槽 | 形态 | 落点 | 本机实例 |
|---|---|---|---|---|
| **左栏独立一页**（推荐） | `settings.section` | `list` / root | 设置弹窗左栏一个导航项，点开是整页内容 | Grafana、思维脑图、背景设置 |
| 「内置插件」里的页签 | `settings.plugins.tab` | `list` / root | 内置插件页内部的 tab；**由内置插件段用 `children` 声明**，只有它存在时才有 | dsh-outline、dsh-localsend、Aqua |
| 「通用设置」里的一行 | `settings.general.item` | `list` / root | 不需要整页的单个偏好行 | Aqua（主题相关行） |
| 单插件配置卡片（旧线） | `settings.plugin.item` | `keyed` | 按 `key` = settings 命名空间派发；0.2.x 宿主**不声明**此槽 | 插件市场、Grafana（备选） |
| 零客户端代码 | — | — | 宿主半导出 `Config`，宿主按 `autoGenerate` 自动生成页 | 本机未见实例；机制由 `autoGenerate` 缺省 `true` 决定 |

判断口径：**要一整页就用 `settings.section`**；只想在内置插件里多一个页签用
`settings.plugins.tab`；只是一个开关行用 `settings.general.item`。第三方优先第一条——
它不与别人抢同一个落点。

### `order` 实测值（0.2.0-rc.2 桌面版）

左栏顺序就是 `order` 升序，缺省 `0`。以下是本机已装插件的真实取值，可作为排位参照
（与设置弹窗左栏自上而下的顺序一致）：

| 导航项 | `id` | `order` |
|---|---|---|
| 账号与余额 | `account` | `-10` |
| 通用设置 | `general` | `0` |
| 模型 | `models` | `10` |
| 背景设置 | `background` | `12` |
| 内置插件 | `plugins` | `15` |
| **Grafana** | `grafana` | `16` |
| Agent 预设 | `agent-presets` | `20` |
| 插件市场 | `market` | `40` |
| **思维脑图** | `dsh-mindmap` | `100` |

排位建议：想紧跟在「内置插件」之后用 `16`；想排在所有官方段之后用 `100` 这一档。

### 另两条路的注册要点

- `settings.plugins.tab`：options 同 `id` / `order` / `label`。它是**子槽**，只有「内置插件」段
  在位时才存在——必须用 `ctx.slots.inject` 等它被声明，裸 `register` 会抛
  `slot "settings.plugins.tab" is not declared`。
- `settings.general.item`：options 只有 `id` / `order`；**段不给任何 props**，文案、当前值与写入
  路径全部由你自己的 `inject` 面提供。

## 最小配方：一个左栏设置页

### 客户端半（`client.js`）

```js
const inject = ["slots"];

function apply(ctx) {
  ctx.slots.inject("settings.section", () => ctx.slots.register({
    name: "settings.section",
    id: "my-plugin",          // 导航键：同时是 renderSlot 的 only 过滤键。必填
    order: 16,                // 升序；16 落在「内置插件」(15) 之后
    label: () => t("nav"),    // 必须是 thunk，跟随语言
    locale: NS,               // 让上面的 thunk 跟随当前语言
    inject: () => ({ face }), // 交给组件的私有数据面
  }, SettingsPanel));
}
```

组件收到的 props 是 `SettingsSectionOwnerProps = { close }`（外壳唯一给你的能力：关掉设置弹窗）
加上你在 `inject` 里声明的面。

### 宿主半（`index.js`）

```js
export const Config = Schema.object({
  lineStyle: Schema.union(["curve", "elbow"]).default("elbow").volatile(),
});

ctx.inject(["settings"], (sctx) => {
  const settings = sctx.settings;
  const scope = typeof settings.register === "function"
    ? settings.register("my-plugin", Config, { base: entryConfig })  // 0.1.5 及更早
    : null;                                                          // 0.1.7+ 只认 describe/update
  const current = () => scope?.get()
    ?? settings.describe().find((r) => r.ns === "my-plugin")?.value
    ?? entryConfig;
  activeConfig = current;
  sctx.effect(() => () => { activeConfig = () => entryConfig; });     // 必须撤销
});
```

全链路（含 `revision` 乐观并发、客户端取服务的三路降级）见
[references/settings-namespace.md](references/settings-namespace.md)。

## 六条硬规则

| # | 规则 | 依据 |
|---|---|---|
| 1 | `list` 槽注册**必须带 `id`**，否则 `SlotCore.register` 直接抛错；导航排序 = `entries('settings.section')` 按 `order` 升序（缺省 `0`） | `ui-slots/src/index.ts:1203-1236`；`ui-settings-general/src/client/index.ts` 的 `getSnapshot()` |
| 2 | `label` 缺失 → 导航项标题为**空串**；跨语言用 `() => t(key)` 配 `locale` | `resolveSlotLabel(options.label) ?? ''` |
| 3 | 导航**图标由宿主按 `id` 硬编码映射**（`account` / `models` / `agent-presets` / `plugins` / `archived-sessions`），其余一律回落到默认齿轮 | `ui-settings-general/src/client/SettingsRoot.tsx` 的 `navIcon(id)` |
| 4 | 暴露给设置页读写的字段**必须标 `.volatile()`**；否则 0.1.7+ 的 `describe` 读回空、`update` 被拒 | `dsh-grafana/index.js` 头部注释 + 其全字段 `.volatile()` |
| 5 | `ctx.slots.inject(slot, cb)` 的 `cb` 在**声明已存在时**同步执行，否则在声明提交后执行；其返回的 disposer 在**声明撤销时**执行 —— **一个声明生命周期一次** | `ui-renderer/src/client/registry.ts:209` |
| 6 | 客户端 `inject` 名单里出现**未注册的服务名**，cordis 会让 fiber 永远停在 `INACTIVE`（插件根本不加载）。拿不准的服务改用 `ctx.get("全名")` 可选查取 | `dsh-grafana/client.js` 头部注释 |

## volatile 双轨：绑定字段与偏好字段

`.volatile()` 不是「一个开关」，它把 schema 里的字段劈成两类，**编辑它们的后果完全不同**：

| 字段类型 | 例子 | 编辑后发生什么 | 为什么 |
|---|---|---|---|
| **绑定字段**（不标 volatile） | 折叠边界、扫描范围、采集端点 | **重挂载 entry** | 这些值在 `apply()` 期间就被读进闭包/投影单元，改了必须重装 |
| **偏好字段**（标 `.volatile()`） | 显示位置、排序方式、趋势模式 | **只提交 volatile，不重挂载** | 只在渲染/每次请求时才读，改了立即生效 |

宿主侧的策略是：Config-form 从同一份 schema 生成 Plugins 页的在线表单，命名空间就是
entry id，**只有 `.volatile()` 字段会被服务且可编辑**；非 volatile 字段的编辑走「重挂载 entry」。

于是判断标准只有一句：

> **这个值在 `apply()` 期间被读进闭包或注册项了吗？**
> 是 → 绑定字段（不标 volatile，靠重挂载生效）。
> 只在渲染/每次请求时才读 → 偏好字段（标 volatile，就地生效）。

标错的代价不对称：

| 标错方向 | 症状 |
|---|---|
| 该 volatile 的没标 | 设置页里改不动（`describe` 读回空、`update` 被拒） |
| 不该 volatile 的标了 | 改了**不重挂载**，可代码在 apply 时已经读过 → 表现为「设置没生效」 |

### 两个一起用的修饰器

```ts
const Config = Schema.object({
  // 绑定字段：不标 volatile —— 改了重挂载
  maxEvents: Schema.number().min(1).step(1).default(400),
  // 偏好字段：volatile + loose —— 就地生效，且陈旧值不炸 entry
  defaultPlacement: volatileField(Schema.union(['all', 'tab', 'sidebar']).default('all').loose()),
})
```

- **`.loose()`**：陈旧的持久值（或类型不对的值）**退化为默认，而不是让 entry 装载失败**。
  老版本写进存储的枚举项在新版本里被删掉了 —— 没有 `.loose()` 就是「升级即启动失败」
- **`volatileField()` 特性探测包装**：`.volatile()` 只在较新宿主上存在，用探测而不是版本号分支：

  ```ts
  export function volatileField<S>(field: S): S {
    const volatile = (field as unknown as { volatile?: () => S }).volatile
    return typeof volatile === 'function' ? volatile.call(field) : field
  }
  ```

  一份 schema 服务所有宿主：新宿主得到在线可编辑，老宿主得到普通字段（功能降级但能装）。

### 消费侧：偏好值是活引用

**标记了 volatile 的字段，运行时解析出来是一个带 `get()` 的引用对象**，不是普通的字符串/数字。
消费方必须按引用读（包成 thunk），才能在偏好编辑后立即生效**且不重挂载**：

```ts
function liveText(value: unknown): () => string {
  if (value !== null && typeof value === 'object' && typeof (value as { get?: unknown }).get === 'function') {
    const get = (value as { get: () => unknown }).get
    return () => { const t = get(); return typeof t === 'string' ? t : '' }
  }
  const text = typeof value === 'string' ? value : ''
  return () => text          // volatile seam 之下就是普通存储值
}
```

配套示例（系统提示段的活文本）见
`dsh-plugin-robust-mount/references/system-prompt-section.md`。

## 跨代兼容：候选插槽降级

宿主世代不同，同一个落点的槽名不同。**不要写死一个槽名**——按「首选 → 备选 → 旧线」列候选，
用 `ctx.slots.spec(name)` 探测实际声明，取第一个真的可用的：

```
candidates = [ settings.section,  settings.plugins.tab,  settings.plugin.item ]
                   ↑ 首选              ↑ 备选                 ↑ 0.1.x 旧线
```

- `ctx.slots.spec(key)` 在**未声明**时返回 `undefined`，声明后返回 `{ kind, scope }`
- 逐候选 `inject`，以 `spec(k)?.kind === candidate.kind` 且 `scope` 相符作为「可用」判据
- 老宿主没有 `spec` 这个函数 → 退化成「把除首选外的候选都注册上」，由各自宿主消费
  （**不能因为新槽永不渲染就撤掉旧卡片**）

完整适配器（`queueMicrotask` 合并、`INACTIVE_EFFECT` 处理、回落）见
[references/slot-fallback-adapter.md](references/slot-fallback-adapter.md)。

## 坑（Gotchas）

| 现象 | 原因 |
|---|---|
| 左栏根本没有你的条目 | 注册写在了宿主半（`index.js`）。插槽属于**客户端半**，且 `package.json` 要有 `dsh.client` 段 |
| 启动即报 `slot "settings.section" is not declared` | 宿主没声明该槽（老宿主），或注册早于声明者加载 |
| 条目在，点开空白 | 组件没渲染内容；或 `inject` 的面在服务未就绪时抛错（服务可能**晚到**，别在 `apply` 时只捕获一次） |
| 标题空一行 | `label` 缺省且没有 `locale` → `resolveSlotLabel` 得到空串 |
| 图标是齿轮，和邻居不搭 | 宿主只认 5 个内置 `id`；第三方没有专属图标，这是设计 |
| 设置页读写回来全是默认值 | 字段没标 `.volatile()`（0.1.7+ 门禁） |
| 写入被拒或抛 `SettingsConflictError` | 没带 `revision` 做乐观并发；`update` 第三参要传读到的 `descriptor.revision` |
| 切语言后标题不变 | `label` 是字符串常量，不是 `() => t(key)` |
| 插件加载不了，日志里 fiber `INACTIVE` | `inject` 名单里有不存在的服务名；改用 `ctx.get("全名")` |
| 换宿主版本后入口消失 | 写死了单一槽名；改用候选降级适配器 |
| 改了偏好设置但没生效 | 该字段没标 `.volatile()`，宿主只提交 volatile 字段 —— 而它又没重挂载，改动被丢弃 |
| 改了绑定字段但行为没变 | 反过来：字段标了 `.volatile()`，于是不重挂载，可代码在 `apply()` 时已经读过了 |
| 升级后插件起不来 | 老版本写进存储的枚举值已被删除，字段缺 `.loose()` |
| 设置里出现两个你的入口 | 自定义页与 `autoGenerate` 自动页同时生效；不需要自动页就 `configure({ auto: false })` |
| 同一轮槽变化后多出一个重复入口 | 未把若干次声明变化合并成一次切换，重复 `id` 会抛错 |

## 自检清单

- [ ] 应用入口在客户端半，`package.json` 有 `dsh.client`（`platform: "web"`）
- [ ] 注册走 `ctx.slots.inject(slot, () => ctx.slots.register(...))`，不是裸注册
- [ ] `id` 稳定；`order` 与邻居不冲突；`label` 是 `() => t(key)` 且带 `locale`
- [ ] 需要兼容多代宿主时用了候选降级，而不是写死槽名
- [ ] 宿主半注册了同名 settings 命名空间
- [ ] 字段按双轨分过类：`apply()` 期间读的 = 绑定字段（不标 volatile）；渲染时才读的 = 偏好字段（标 volatile）
- [ ] 偏好字段带 `.loose()`（陈旧/类型不对的持久值退化为默认而不是炸 entry）
- [ ] `.volatile()` 经 `volatileField()` 特性探测包裹，没有按版本号分支
- [ ] 消费偏好字段时按活引用读（thunk），不是取一次快照
- [ ] 写入带 `revision`；读到「服务不可用」时降级而不是崩
- [ ] 每个 effect 都返回清理函数（`activeConfig` 复位、disposer 回收）
- [ ] 卸载插件后左栏条目确实消失
- [ ] 不需要自动页时显式 `configure({ auto: false })`

## 参考实现

| 用途 | 位置 |
|---|---|
| 候选插槽降级 + 左栏页（**最完整范例**） | `<dsh-home>\profiles\desktop\node_modules\dsh-grafana\client.js`（0.18.1，注册段 857–935 行） |
| 左栏页 + 用 `children` 声明子槽 | `<harness-checkout>\packages\client\ui-settings-plugins\src\client\index.ts`（`id: 'plugins'`, `order: 15`） |
| 左栏页 + 主题面板 + 服务降级取用 | `<dsh-home>\profiles\desktop\node_modules\dsh-mindmap\client.js`（0.17.0，注册段 5243 行） |
| 宿主半命名空间双代注册 | `…\node_modules\dsh-grafana\index.js`（291–310 行）、`…\dsh-mindmap\index.js`（674–700 行） |
| 最小 `settings.section` 注册（最短范例） | `<dsh-home>\profiles\desktop\node_modules\@deepseek-ai\dsh-client-bg\lib\client.js`（498 行，`id: 'background'`, `order: 12`） |
| 「内置插件」页签路径 | `…\node_modules\dsh-outline\client.js`（542 行）、`…\dsh-localsend\client.js`（375 行） |
| 同时注册 section + 旧线卡片 | `…\node_modules\dshmarket\client\client.js`（15169 行，`id: 'market'`, `order: 40`） |
| 宿主侧自动页策略（`autoGenerate`） | `…\node_modules\dsh-localsend\index.js`（`configure({ auto: true })` 及其 0.2.0 迁移注释） |
| volatile 双轨 + `.loose()` + `volatileField()` 特性探测 | `<dsh-context-checkout>\src\host\config.ts`（75 行，整篇可读） |
| 偏好字段的活引用消费（`liveText`） | `…\dsh-context-main\src\host\promptInjection.ts` |
| 插槽声明唯一事实来源 | `…\packages\client\ui-settings\src\client\contract\slots.ts` |
| 导航行派生 + 图标映射 | `…\packages\client\ui-settings-general\src\client\index.ts`、`SettingsRoot.tsx` |
| `inject` / `spec` / `register` 语义 | `…\packages\client\ui-renderer\src\client\registry.ts`、`ui-slots\src\index.ts` |

> 路径前缀：`…\packages\client` = `<harness-checkout>\packages\client`（0.1.7-rc.2 检出）。
> 已安装版本的代码才是运行时事实——本机 `dsh-grafana` 0.18.1 / `dsh-mindmap` 0.17.0 比
> `<plugins-dir>\` 下的本地检出（0.15.0 / 0.5.1）新，读代码时先看已安装副本。

配套 skill：控件落位（按钮/面板/浮层放哪、`order` 量级、fixed 宿主层）见
`dsh-client-slot-placement`；会话标签页见 `dsh-conversation-view-tab`；
「同服务多实例 + 每源独立凭据」的数组配置见 `dsh-multi-source-config`。

配套 skill（宿主半侧）：从零建双半边插件、客户端 bundle 构建链、React/Tailwind 打包与
平台模块白名单见 `dsh-plugin-dual-half-skeleton`；宿主半把会话数据流给浏览器见
`dsh-session-projection`；宿主侧按需路由与冷读治理见 `dsh-plugin-fetch-route`；
宿主跨版本探测与基线降级见 `dsh-harness-compat-gate`（`.volatile()` 的特性探测是它
「探测能力而非版本」原则下的一个实例）；可选服务缺席时的延迟注入与优雅降级见
`dsh-plugin-robust-mount`。

volatile 双轨的完整语义（含 `.loose()` 兜陈旧值、活引用消费）见
[references/volatile-two-track.md](references/volatile-two-track.md)。

总览与索引见 `dsh-plugin-dev-guide`。
