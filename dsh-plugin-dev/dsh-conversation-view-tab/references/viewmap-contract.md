# ViewMap 契约：让对话视图拿到真实数据

`conversation.view` 插槽注册只负责**标签本身**。视图要渲染内容，还要接进
`ctx.uiConversation`（对话组装层，即 ViewMap）。两条线是分开的，缺一条就会
"标签在、点开空白"。

## 三步

### ① 声明本视图的快照类型（module augmentation）

```ts
declare module '@deepseek-ai/dsh-client-ui-conversation/client' {
  interface ConversationViewSnapshotMap {
    mine: MySnapshot        // key 必须等于插槽注册的 id
  }
}
```

### ② 注册 target 快照 builder

```ts
import type { ConversationViewDefinition } from '@deepseek-ai/dsh-client-ui-conversation/client'

export const myViewDefinition: ConversationViewDefinition<MyViewNode, MySnapshot> = {
  target: 'mine',                    // ← 与插槽 id 一致
  toolCallFocus: callId => callId,   // 可选：把工具调用 id 映射成本视图的焦点标识
  create: () => new MySnapshotBuilder(),
}

ctx.uiConversation.views.register(myViewDefinition)
```

`MySnapshotBuilder` 由你实现：消费会话事件流，产出本视图的快照。

### ③ 在 `inject` 里取本会话的 target

```ts
ctx.slots.inject('conversation.view', () => ctx.slots.register({
  name: 'conversation.view',
  id: 'mine',
  order: 40,
  label: () => t('tab.mine'),
  inject: (sessionId) => {
    const target = ctx.uiConversation.binding(sessionId).target('mine')
    return {
      hooks: {
        mine: {
          getSnapshot: () => target.getSnapshot() ?? EMPTY_MY_SNAPSHOT,
          subscribe: listener => target.subscribe(listener),
        },
      },
    }
  },
}, MyView))
```

`ui-trajectory` 用 `WeakMap<SessionBinding, ObservableSnapshot<T>>` 缓存这个 source，
避免逐会话重复构造。它还在会话不可用时**直接抛错**（`throw new Error(...)`）作为保护。

## 把 selector hook 变成标准 prop

组件里更顺手的写法是让外壳提供 `useMine`：

```ts
ctx.uiSession.provide({
  hooks: ['mine'],
  resolve: binding => ({ hooks: { mine: mySource(binding) } }),
})
```

再对 `SessionStandardProps` 做声明合并：

```ts
declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface SessionStandardProps {
    useMine: SnapshotSelectorHook<MySnapshot>
  }
}
```

## `ctx.uiConversation` 上可用的其他能力

| 成员 | 用途 |
|---|---|
| `views.register(def)` | View Definition 的唯一注册表；拒绝重复 key、保持注册顺序、返回幂等 disposer |
| `events.register(def)` | 事件 Definition 的唯一注册表 |
| `groups` | 为每个已注册 target 注册可选的业务 Group Definition（分组/分段规则） |
| `binding(idOrBinding)` | 拿 identity 稳定的 Conversation binding，不另开事件源 |
| `binding(id).target(targetId)` | 读该 Session 自有的 target source（`getSnapshot` / `subscribe`） |
| `binding(id).activate(viewId)` | 激活某个视图（外壳切标签时调它） |
| `imageUrl(sessionId, attachment)` | 解析经会话授权的图片 URL（随 binding 释放而撤销） |

**注册表行为**：roster 变化时重建现有 binding；View 注册被移除后其分组计算暂停并清空
已发布结果，但 Group Definition 保留，重新注册后从当前时间线重建。
**切换标签页不会移除 View Definition。**

## 选中状态存哪

`ConversationStoreState`（由 `ui-conversation` 拥有，逐会话持久化）：

```ts
interface ConversationStoreState {
  draft: string                          // 输入草稿
  view: string | null                    // 首选标签 id；null → 有 chat 就用 chat
  viewRequest: ConversationViewRequest | null   // 一次性焦点请求
}
```

`ConversationViewRequest = { view: string; focus: string }` —— 外壳可以要求某个视图
把焦点落到一个 target 自有的不透明标识上。

## 进一步阅读

- `@deepseek-ai/dsh-client-ui-conversation` 的 `README.zh.md`
  → 「Conversation 组装」一节讲 Definition / binding / 分组 / replacement window
- 该包 `src/client/apply.ts` 的 `viewTabs()` → 标签投影的确切实现
- 该包 `src/client/contract/views.ts` → `ViewTab` 与 `ConversationStoreState`
- `@deepseek-ai/dsh-client-ui-trajectory/src/` → 全套范例（事件定义、快照 builder、视图组件）
