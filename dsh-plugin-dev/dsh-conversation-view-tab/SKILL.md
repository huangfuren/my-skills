---
name: dsh-conversation-view-tab
description: >-
  Use when adding, changing, debugging, or reviewing a tab in the DSH conversation
  view tab bar (对话 / 轨迹 / 上下文 / 编队) — that is, a client plugin that renders its
  own full-pane surface next to Chat. Covers the 'conversation.view' slot contract,
  the ctx.slots.inject + ctx.slots.register recipe, per-session inject props,
  store-gated show/hide, the "fewer than 2 views hides the whole tab bar" rule,
  label localization via a thunk, and the ViewMap data plumbing a real view needs.
  Includes the gotchas that make a tab silently never appear.
license: MIT
compatibility: >-
  DSH client plugins (dsh.client.platform = "web"). Applies to the Web and desktop
  profiles; a headless/CLI profile has no conversation surface. Field names verified
  against dsh 0.2.0-rc.2 (@deepseek-ai/dsh-client-ui-conversation).
---

# DSH 对话标签页（conversation.view）实现

第三方插件与官方包走**同一条契约**。`ui-trajectory`（轨迹）和 `dsh-context`（上下文 / 编队）
是两个可对照的真实实现。

## 一句话结论

对话标签栏里的每个标签 = 一次 **`'conversation.view'` 插槽注册**。
DSH 没有独立的"标签 API"，也没有"把按钮塞进标签栏"的专用接口。

## 插槽契约

`@deepseek-ai/dsh-client-ui-conversation` 声明：

```ts
'conversation.view': { kind: 'list'; scope: 'session'; owner: ConvViewOwnerProps }
```

- `kind: 'list'` —— 多个插件可同时注册，外壳把它们排成一排标签
- `scope: 'session'` —— 每个会话各自一份状态（含"当前选中哪个标签"）
- 外壳把每个注册项投影成 `ViewTab { id, label }`

## 最小可跑范例

```ts
import type { Context } from '@deepseek-ai/cordis'
// 仅类型 import：把 'conversation.view' 的 SlotMap 行拉进程序，否则 register 过不了类型检查
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type { PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'

const NS = 'my-plugin'
const zh = { 'tab.mine': '我的面板' }
const en = { 'tab.mine': 'My panel' }

export const inject = ['slots', 'locale']

export function apply(ctx: Context): void {
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'my-plugin: dictionaries')
  const t = ctx.locale.bind(NS)

  ctx.slots.inject('conversation.view', () => ctx.slots.register({
    name: 'conversation.view',
    id: 'mine',                  // 稳定标识：同时是 target id 与"上次选中"的持久化键
    order: 40,                   // 标签顺序（升序）
    locale: NS,
    label: () => t('tab.mine'),  // 必须是 thunk，不能是字符串
  }, MyPanel))
}

function MyPanel(props: PropsRuntime<'conversation.view'>) { /* React 组件 */ }
```

第三个参数就是视图组件，普通 React 组件即可。

## 注册字段速查

| 字段 | 必填 | 作用 |
|---|---|---|
| `name` | ✅ | 固定 `'conversation.view'` |
| `id` | ✅ | 稳定标识。**缺了会被外壳直接跳过**，标签不出现 |
| `order` | — | 标签顺序，升序；不填按注册顺序 |
| `label` | — | 标签文字，写成 `() => t(key)`；缺省回退到 `id` |
| `locale` | — | 让 `label` 的 thunk 跟随当前语言 |
| `children` | — | 本视图内部再开子插槽 |
| `inject` | — | `(sessionId) => props`，逐会话数据交给组件 |

## 外壳如何投影标签栏

来自 `ui-conversation` 的 `viewTabs()` 与 `apply.ts`：

1. **跳过没有 `id` 的注册项**；`label` 取 `resolveSlotLabel(options.label) ?? id`
2. **订阅 `conversation.view` + locale + developerTools**，任一变化即重投影
   —— 这就是"切语言标签跟着变、注册/注销即时生效"的来源
3. **可用视图少于 2 个时，整条标签栏隐藏**。只注册一个视图的插件，用户看不到标签栏
   —— 这是设计，不是 bug
4. **选中规则**：持久化偏好 → 已注册的 `chat` → 不渲染。
   **绝不选第一个已注册的视图**

## 显示 / 隐藏：用 store 门控注册

`ctx.slots.inject(slot, factory)` 返回的 disposer 会被当作 effect 的清理函数：
**插件卸载、插槽重声明都会自动撤销标签**。

要把开关交给用户偏好，就把注册包在跟随偏好的 effect 里：

```ts
ctx.slots.inject('conversation.view', () => {
  let dispose: (() => void) | undefined
  const sync = (): void => {
    const want = store.getSnapshot().showTab
    if (want && dispose === undefined) {
      dispose = ctx.slots.register({
        name: 'conversation.view', id: 'mine', order: 40, label: () => t('tab.mine'),
      }, MyPanel)
    } else if (!want && dispose !== undefined) {
      dispose()
      dispose = undefined
    }
  }
  sync()
  const off = store.subscribe(sync)
  return () => { off(); dispose?.() }
})
```

`dsh-context` 的「编队」标签就是这么做的：注册项 `id: 'fleet'`、`order: 30`、
`label: () => t('tab.fleet')`，外面套一层 `fleetTab() === 'show'` 的门控，
所以用户关掉偏好后标签立即消失。

## 视图要显示真实数据

只注册插槽 = 一个空壳标签。要让视图有数据，还要接进 **ViewMap**（对话组装层）：
声明快照类型 → 注册 target 快照 builder → 在 `inject` 里取 target。

完整步骤与 API 见 [references/viewmap-contract.md](references/viewmap-contract.md)。

## 坑（Gotchas）

| 现象 | 原因 |
|---|---|
| 标签完全不出现 | 注册项漏了 `id`，被 `viewTabs()` 跳过 |
| 标签不出现 | 全库只有你一个视图，未满 2 个 → 整条标签栏隐藏 |
| 只装了插件没写代码 | 插槽注册在**客户端半**（`dsh.client`），只出 host 半没有 UI |
| 标签文字不跟语言切换 | `label` 写成了字符串常量，而不是 `() => t(key)` |
| 切语言后标签消失/错位 | 字典没注册（`ctx.locale.register`）就调 `label` 的 thunk |
| 注册了但点开空白 | 只注册了插槽，没注册 ViewMap 的 target builder |
| 卸载插件后标签还在 | 注册没走 `ctx.slots.inject` 的 effect 包装，disposer 没被回收 |
| 想改顺序没生效 | 改的是 `order` 之外的字段；`order` 只在重新注册时生效 |

## 自检清单

- [ ] `inject` 里声明了 `slots`（和 `locale`，若用字典）
- [ ] 注册项有稳定的 `id`，且与 ViewMap 的 `target` 一致
- [ ] `label` 是 thunk `() => t(key)`
- [ ] 用 `ctx.slots.inject(slot, () => ctx.slots.register(...))` 而非裸注册
- [ ] 需要在会话里拿数据时，已注册 target builder 并在 `inject` 中取 target
- [ ] 确认这个部署里**至少还有另一个视图**，否则标签栏不显示
- [ ] 卸载插件后标签确实消失（disposer 生效）

## 参考实现

- `@deepseek-ai/dsh-client-ui-trajectory` —— 官方范例，
  `src/client/index.ts` 是完整的注册入口（带 `children`、`inject`、标准 prop）
- `dsh-context` —— 第三方范例，一个包注册两个标签（`id: 'context'` / `id: 'fleet'`），
  且带偏好门控；`lib/client.js` 是压缩产物，搜索 `conversation.view` 即可定位

配套 skill：这个标签页放哪、`order` 怎么排、全高面板怎么不被裁见
`dsh-client-slot-placement`；标签页要展示的宿主侧数据从哪里来见 `dsh-session-projection`；
从零建双半边插件见 `dsh-plugin-dual-half-skeleton`；标签页里要按需拉的重数据见
`dsh-plugin-fetch-route`；标签页出现**两份**（双挂载）见 `dsh-plugin-robust-mount`。

总览与索引见 `dsh-plugin-dev-guide`。
