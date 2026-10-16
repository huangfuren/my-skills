# 单活挂载守卫

## 1. 症状与根因

**症状**：同一个页面里，插件在每个座位上画了**两份**（两个标签、两个按钮、两张卡片）。

**根因**（宿主侧机制，不是你的 bug）：

客户端插件运行器会给**每一次注册**强分配一个新的 shadowing priority。
slot 注册表里那套「同优先级重复注册就跳过」的守卫，因此**跨双挂载永远不会触发** ——
两次注册拿到的优先级不同，注册表认为它们是两件不同的事。

再叠加一个常见诱因：同一个 bundle 被两种路径装载（例如插件被 `dsh.client.inject`
预加载了一次，页面自己又注册了一次）。

## 2. 守卫的实现

挂载前读 slot 的**原始账本**（注册表内部的 entries 视图），看这个 id 是否已经坐上：

```ts
/**
 * 页面的 slot 账本里是否已经坐着 `id`。
 * 读的是**原始账本**（会话头部实际渲染用的那个视图），所以「坐上的」就是宿主会画出来的 ——
 * 正是第二次挂载不该再添加的东西。
 * Fail open：面缺席、形状变了、或者是敌意的 → 一律 false，于是挂载照常进行，绝不白屏。
 */
export function entrySeated(ctx: ClientCtx, name: string, id: string): boolean {
  try {
    const entries = ctx.slots.entries?.(name)
    if (!Array.isArray(entries)) return false
    for (const entry of entries) {
      const options = asRecord(asRecord(entry)?.options)
      if (options !== null && options.id === id) return true
    }
    return false
  } catch {
    return false
  }
}
```

调用点：

```ts
if (entrySeated(ctx, 'conversation.view', 'mine')) return   // 已经坐上 → 本次挂载整段跳过
ctx.slots.inject('conversation.view', () =>
  ctx.slots.register({ name: 'conversation.view', id: 'mine', order: 20, label: () => t('tab.mine') }, View))
```

## 3. 面上的三层形状

```ts
interface SlotsService {
  inject(name: string, callback: () => unknown): unknown
  register(registration: SlotRegistration, component: (props) => unknown): unknown
  /** slot 账本的原始 entries 视图（`SlotCore.entries`）：坐上的每个 entry 一条记录，
   *  其 `options` 携带注册时的 id/order/…。可选：更老的面没有它就照常挂载。 */
  entries?(name: string): unknown
}
```

要点：

- `entries?` 是**可选方法** —— 老宿主面上没有它，守卫自然退化为「没有守卫」（fail open）
- 返回值是 `unknown`，必须**逐层 narrow**：数组？ → 元素是对象？ → `entry.options` 是对象？ → `options.id` 相等？
- 比对的是**注册时给的 `id`**，所以每个 `register` 都必须带一个稳定、唯一的 `id`

## 4. 四条设计约束

| 约束 | 理由 |
|---|---|
| **比对 `options.id`** | 这是注册表自己记录的登记项，不依赖任何私有字段 |
| **一律 `try/catch → false`** | 守卫读的是**宿主内部视图**形状，跨版本可能变；守卫失败绝不能变成白屏 |
| **`entries` 缺席 = 无守卫** | 「没有守卫」等价于「和以前一样」，是安全的默认 |
| **读原始账本，不读渲染视图** | 你关心的是「注册表认为坐上了什么」，而不是「此刻画出来了什么」 |

## 5. 这条模式可以推广到哪些地方

凡是「同页面可能被挂载多次」的注册，都值得加同型守卫：

| 场景 | 守卫目标 |
|---|---|
| 会话视图标签页 | `conversation.view` 上的自有 id |
| 设置页入口 / 卡片 | `settings.*` 对应 slot 上的自有 key |
| 侧边栏面板 | 对应 list slot 上的自有 id |
| 全局浮层宿主 | 页面级 DOM 节点的存在性（`document.querySelector('[data-my-plugin-root]')`） |

最后一类不在 slot 系统里，但逻辑同型：**先问「是不是已经有了」，再决定要不要创建**，
且「问不出来」时选择「创建」（fail open 意味着宁可重复也不缺席 —— 但注意这里的权衡：
对纯 UI 节点，重复是可接受的，缺失是不可接受的；如果你判断重复更糟，那就把守卫做成
「查不到就不挂」，但要在注释里写明这是有意的取舍）。

## 6. 为什么不能「挂载后去重」

另一种看似可行的做法是挂载后扫描已有 DOM 再删除重复。**不要这么做**：

- React 树已经建立，删除 DOM 会造成托管状态与实际 DOM 不一致（下一次渲染又回来）
- 组件的 effect 可能已经注册了监听器/定时器，删 DOM 不回收它们
- 顺序不稳定：你删掉的那个可能才是持有正确订阅的那个

**在挂载前决定，而不是挂载后修复。**

## 7. 排错对照

| 症状 | 先查 |
|---|---|
| 每个座位两份 | 是否走两条装载路径（`dsh.client.inject` + 页面注册） |
| 守卫没生效 | `register` 是否真的带了 `id`；`id` 是否每次都不同 |
| 加了守卫后完全不显示 | 守卫写成了 fail closed，或 `entries()` 的形状 narrow 错了 |
| 只有某些宿主上双份 | 老宿主的 `entries` 缺席（此时没有守卫，属预期）；考虑改用 DOM 标记兜底 |
