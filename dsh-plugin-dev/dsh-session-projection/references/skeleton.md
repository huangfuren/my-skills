# 可复制骨架：一个投影单元

按此骨架写，得到：一个**给浏览器看的**单元（带瘦 wire）+ 一个**宿主自己用的**单元
（无 wire）+ 注册时机 + 两侧读取代码。示例插件名统一用 `my-plugin`。

> 结构参考 `bowenliang123/dsh-context` v0.72.0（`src/host/timeline.ts` / `fallback.ts` /
> `src/client/services.ts`，Apache-2.0）。下面是**重写后的最小骨架**，不是搬运。

## 1. 类型表要先「声明合并」出你的 key

投影键有类型约束（`SessionProjectionStateMap` / `SessionProjectionMap`）。
按官方 `types.ts` 的方式声明合并：

```ts
// src/shared/projection.ts
// 用 /types 出口，不要用包根：包根会把宿主侧的 cordis Context 合并带进浏览器 bundle
declare module '@deepseek-ai/dsh-session-projection/types' {
  interface SessionProjectionStateMap {
    'myPlugin/todo': MyTodoState        // 内部状态（plain JSON）
  }
  interface SessionProjectionMap {
    'myPlugin/todo': MyTodoView         // 下发给浏览器的值
  }
}
```

`key` 一带插件前缀，就同时解决了「撞 key 直接抛错」和「读代码时不知道谁注册的」两个问题。

> host-only 的 key 是否要写进 `SessionProjectionMap`，两代宿主规则不同 ——
> 详见 [state-version-and-legacy.md](state-version-and-legacy.md) §4。

## 2. 声明状态 schema

```ts
import { z } from 'zod'

const stateSchema = z.object({
  items: z.array(z.object({ id: z.string(), text: z.string(), done: z.boolean() })),
  rev: z.number().int().nonnegative(),
})
type MyTodoState = z.infer<typeof stateSchema>

// 下发前校验（strict：不允许漂移）
const viewSchema = z.object({
  total: z.number().int().nonnegative(),
  open: z.number().int().nonnegative(),
  head: z.array(z.object({ id: z.string(), text: z.string() })),
}).strict()
type MyTodoView = z.infer<typeof viewSchema>
```

`stateSchema` 校验**内部状态**，`viewSchema` 校验**下发载荷** —— 两者都不要 `.passthrough()`
或宽松模式：**多出字段（schema 漂移）应当直接失败**。

## 3. 单元 A：带 wire（给浏览器）

```ts
import type { SessionEvent } from '@deepseek-ai/dsh-session'

export const todoDefinition = {
  key: 'myPlugin/todo' as const,
  stateSchema,
  stateVersion: 1,

  init: (header, _inheritedEventCount) => ({ items: [], rev: 0 }),

  apply: (state: MyTodoState, event: SessionEvent): MyTodoState => {
    if (event.type !== 'todo/upsert') return state      // ← 铁律①：返回同一引用
    const items = event.data.items as MyTodoState['items']
    return { items, rev: state.rev + 1 }                // 只有变化时才造新对象
  },

  // 瘦头：只下发 UI 量级的小值，明细另走按需路由
  wire: {
    viewSchema,
    view: (state: MyTodoState): MyTodoView => ({
      total: state.items.length,
      open: state.items.filter(i => !i.done).length,
      head: state.items.slice(0, 5).map(i => ({ id: i.id, text: i.text })),
    }),
  },
}
```

要点：

- `apply` 的每个「不关心」分支都 `return state`（不是 `return {...state}`）
- 内部状态（`rev`）变化不影响下发值时，可以在 view 里**复用引用**进一步抑制发布；
  简单的标量重算不必强求
- 明细（`items` 全量）**不进 wire** —— 见 SKILL.md 的「瘦 wire」

## 4. 单元 B：无 wire（host-only）

宿主自己记账、浏览器不需要读的：

```ts
export const bookkeepingDefinition = {
  key: 'myPlugin/ledger' as const,
  stateSchema: z.object({ calls: z.number().int().nonnegative() }),
  stateVersion: 1,
  init: () => ({ calls: 0 }),
  apply: (state, event) => event.type === 'my-plugin/call'
    ? { calls: state.calls + 1 }
    : state,
  // 刻意不写 wire：这是 host-only 单元，值永不下发浏览器
}
```

**不写 `wire` 是能力开关**，不是遗漏。写一句注释说明「这里的值是宿主内部记账」。

## 5. 注册

```ts
export const name = 'my-plugin'
// 必需：服务缺席就明确失败（别静默降级）
export const inject = ['sessionProjections']

export function apply(ctx, config) {
  ctx.sessionProjections.register(todoDefinition)
  ctx.sessionProjections.register(bookkeepingDefinition)

  // 宿主侧的读取：用 stateOf 拿自己单元的活状态，不触发整轮 view 计算
  const openCount = (session) =>
    ctx.sessionProjections.stateOf(session, 'myPlugin/todo')?.items.filter(i => !i.done).length ?? 0
}
```

**可选贡献方**（服务可能缺席的老宿主）改成延迟注入：

```ts
export const inject = []           // 不把 sessionProjections 写成硬依赖
export function apply(ctx) {
  ctx.inject(['sessionProjections'], (sctx) => {
    sctx.sessionProjections.register(todoDefinition)
  })
}
```

## 6. 宿主侧订阅变更

```ts
ctx.effect(() => {
  const off = ctx.sessionProjections.onChanged((session, key, value, seq) => {
    if (key !== 'myPlugin/todo') return
    // value 已经过 viewSchema 校验；seq 是致因事件的水位
  })
  return off
}, 'my-plugin: todo change feed')
```

## 7. 客户端读取（槽位标准座位）

```ts
interface SessionStandardProps {
  sessionId?: string
  useProjection?: (key: string) => unknown
}

function narrowTodo(value: unknown): MyTodoView | null {
  if (value === null || typeof value !== 'object') return null
  const v = value as Record<string, unknown>
  if (typeof v.total !== 'number' || !Number.isFinite(v.total)) return null
  return v as MyTodoView
}

export function TodoBadge(props: SessionStandardProps) {
  // hook：顶层无条件调用，一个 key 一次，顺序稳定
  const seat = props.useProjection
  const view = typeof seat === 'function' ? narrowTodo(seat('myPlugin/todo')) : null
  if (view === null) return null         // 能力缺席 → 降级为不渲染，不抛
  return h('span', null, `${view.open}/${view.total}`)
}
```

注册这个组件时把 `locale` 与 label thunk 一起给（见配套 skill `dsh-conversation-view-tab`）。

## 8. 落地顺序

1. 先只写单元 A 与注册，在宿主侧用 `stateOf(session, 'myPlugin/todo')` 打印，确认**折叠正确**
   （这一步排除 schema 与 `apply` 引用问题，不要一上来就接 UI）
2. 加 `snapshot(session)`，确认 `values['myPlugin/todo']` 出现且随事件更新
3. 客户端只渲染一个计数，确认座位取到值
4. 最后再加单元 B 与按需明细路由

## 9. 常见偏差

| 偏差 | 后果 |
|---|---|
| `init` 里读了 `firstLiveSeq` / `session/end-seed` 反推 fork 切点 | fork 会话的初始状态错位（切点由入参给） |
| `apply` 造新对象但不改值 | 每条事件都发布一次，UI 抖 |
| `stateSchema` 用 `.passthrough()` | schema 漂移被吞，持久缓存里混进未知字段 |
| 一个单元既想 host-only 又想下发 | 拆成两个单元，别在 `wire` 里做条件分支 |
| `stateVersion` 从 1 改成 0 或负数 | 注册直接抛错 |
| 客户端把 hook 放进 `if` / 循环里 | React hook 顺序错乱 |
| 客户端没做 `typeof` 探测 | 老宿主上直接抛，整视图炸掉 |
