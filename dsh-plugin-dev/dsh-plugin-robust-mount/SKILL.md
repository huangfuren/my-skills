---
name: dsh-plugin-robust-mount
description: >-
  Use when a DSH plugin must coexist with services and plugins it does not control — when a
  plugin silently never loads because a hard `inject` named an absent service, when a service
  arrives after the plugin and the registration is missed, when a bundle is mounted twice and
  every seat paints two copies, or when a plugin registers a system-prompt section. Covers
  the ctx.inject deferred-injection versus ctx.get immediate-read semantics, the hard-inject
  gate, the re-prove-and-bind boundary rule, the slot-ledger single-mount guard, service
  teardown cleanup, and the system-prompt section contract with its order anchors.
license: MIT
compatibility: >-
  Any DSH plugin. Deferred-inject, slot-ledger and system-prompt section semantics read from
  bowenliang123/dsh-context source (Apache-2.0) and the installed dsh 0.2.0-rc.2 client shell.
---

# 插件互操作与副作用

一个插件从来不是孤岛：它依赖别人的服务、和别的插件共处一个页面、还可能改写系统的行为。
这一篇解决三件事：**服务来晚了怎么办、被挂了两次怎么办、改动了什么要说清**。

## 第一原则：仍然 fail open

和兼容篇一致，这里也贯穿一条：

> **任何可选依赖缺席 → 这段静默 no-op，插件其余部分照常工作。**

绝不出现「因为某个可选服务不在，所以整个插件不加载」。

---

## 一、`ctx.inject([...])` vs `ctx.get()` —— 本篇最重要的一条

同样是「拿一个服务」，两种写法语义完全不同，用错会**静默降级**：

| | 顶层 `inject = [...]` | `ctx.inject([...], cb)` | `ctx.get(name)` |
|---|---|---|---|
| 性质 | **硬闸门** | **延迟注入** | **即时读取** |
| 服务缺席时 | 整个插件停在 INACTIVE，**无报错** | 这段 cb 不跑，插件其余照常 | 返回 `undefined` |
| 服务**后到**时 | —— | **cb 会在服务到达时执行** | **拿不到**（当时是 undefined，且不会重试） |
| 服务卸载时 | 插件卸载 | cb 的返回值被当 disposer 调用 | 无感知 |
| 用途 | 插件缺它就毫无意义的服务 | 可选能力 | 在 cb 内部 / 事件回调里读当前值 |

三条可直接落地的规则：

1. **顶层 `inject` 只列「确定存在」的服务**（`sessionProjections`、`slots`、`locale` 这类宿主内核）。
   名字写错或该服务在某个部署里缺席 → **「什么都不发生，也没有任何报错」**，这是最难 debug 的故障形态。
2. **任何可能缺席的服务一律走 `ctx.inject([...], cb)`** —— 它同时解决了「来晚了」和「没有」两种情况。
3. **`ctx.get()` 只在「已经确定它存在」的上下文里用**（例如在 `ctx.inject` 的 cb 内部取兄弟服务，
   或在每次请求时读取当前实例）。**不要用 `ctx.get()` 去做「等待服务到达」** —— 它不会等。

```ts
// ✅ 可选服务：来晚了也能生效，没有就 no-op
ctx.inject(['configForms'], (c) => {
  const forms = c.configForms
  if (forms === undefined || typeof forms.get !== 'function') return   // 形状校验，不是断言
  c.effect(() => settings.attach(forms.get(NS)), 'my-plugin: config forms')
})

// ❌ 想让可选服务「等一等」而用 get
const forms = ctx.get('configForms')          // 服务后到时永远拿到 undefined
```

**依赖多个服务时全部列进同一个数组**：`ctx.inject(['connection', 'sessions'], cb)` ——
任一缺席就整段不 arm。在服务不全时注册一个注定失败的 handler，比不注册更糟
（会留下悬空路由/半残状态）。

## 二、跨边界：形状校验 + bind

宿主面按**结构**声明，字段全部可选，运行时逐项实证。**取到就 bind**：

```ts
const sessions = c.get('sessions') as SessionsHostFace | undefined
const getSession = typeof sessions?.get === 'function' ? sessions.get.bind(sessions) : undefined
if (getSession === undefined) return
```

- `typeof x === 'function'` 是**形状校验**：变量存在 ≠ 类型正确
- `.bind(owner)` 绑定的是**拥有者对象**（`sessions`），不是外围的 `c`
- 这条规则对所有跨边界传递/延后调用的宿主方法适用（详见 `dsh-plugin-fetch-route` 的 `connection-seam.md`）

## 三、同一 bundle 被挂两次

**症状**：每个座位画出两份组件 / 两个标签页 / 两个按钮。

**根因**：客户端插件运行器会给**每一次注册**强分配一个新的 shadowing priority，
于是 slot 注册表那套「同优先级重复守卫」在「同一 bundle 被挂两次」时**永远不会触发**。

**对策**：在挂载前读 slot **原始账本**，看这个 id 是不是已经坐上了：

```ts
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
    return false       // fail open：读不到就照常挂，绝不因为守卫本身失败而白屏
  }
}
```

```ts
if (entrySeated(ctx, 'conversation.view', 'mine')) return   // 已经坐上，什么都不做
ctx.slots.inject('conversation.view', () => ctx.slots.register({ name: 'conversation.view', id: 'mine', ... }, C))
```

要点：

- `entries?.(name)` 是**可选方法**：老宿主的面上没有它 → 没有守卫，但照常挂载
- 比对的是**注册时给的 `id`**，所以每个 `register` 都必须带一个稳定的 `id`
- **try/catch 一律 false**：守卫是「尽力而为」，不是「先决条件」

## 四、服务下沉时清理

注册动作必须挂在会随服务卸载而回收的东西上：

| 场景 | 写法 |
|---|---|
| 注册插槽 | **`ctx.slots.inject(name, cb)` 的返回值就是注册的 disposer**，直接交给 `c.effect` |
| 服务「服务期间」才有意义 | `forms.whileServed([NS], () => 注册动作)` —— 服务下沉时自动清理 |
| 任何自有资源 | `c.effect(() => { ...; return () => cleanup() }, 'label')` |

```ts
c.effect(() => forms.whileServed([NS], () => {
  // slots.inject 的 disposer 就是这次注册的 disposer
  return c.slots.inject('plugins.bundle.config', () =>
    c.slots.register({ name: 'plugins.bundle.config', key: NS, locale: NS, inject: cardFace }, render)) as () => void
}), 'my-plugin: plugins-page card')
```

**别把「注册」和「注销」分开写**：分离的清理一定会漏，而且漏了不报错。

## 五、副作用：系统提示段注入

有一类能力性质上更重 —— **插件要改写送给模型的系统提示词**。做这件事的时候，
「默认无副作用」和「可审计」是硬要求。

```ts
ctx.inject(['systemPrompt'], (inner) => {
  const sp = inner.systemPrompt
  // 形状校验：三个面都要在
  if (sp === null || sp === undefined
    || typeof sp.section !== 'function'
    || typeof sp.getSectionOrder !== 'function') return

  sp.section({
    name: 'my-plugin:prompt-prefix',
    order: sp.getSectionOrder('HARNESS_IDENTITY') - ORDER_CLEARANCE,   // 锚定到宿主自己的序上
    text: sectionText(liveText(config.promptPrefix)),
    interpolate: false,     // 字面文本：用户的 {{...}} 绝不能被当变量插值
  })
})
```

四条约定：

| 约定 | 理由 |
|---|---|
| **默认值为空串，且 `sectionText()` 对纯空白返回空** | 宿主渲染时直接丢弃空段 → **默认状态对提示词零影响** |
| **`order` 用 `getSectionOrder(锚点名) ± 常量` 算** | 宿主重排序时仍然排在正确位置；写死数字必然漂移 |
| **`interpolate: false`** | 用户的 `{{...}}` 是字面文本，不能被严格变量插值解析 |
| **text 用 thunk + 可变的活引用** | 偏好编辑立即生效，且**不需要重挂载 entry** |

**必须知道的连带效果**：宿主按步骤装配提示词并把渲染结果投影进会话日志。所以
① 每个新会话从第一轮就带上该文本，② 编辑会通过宿主自己的投影改写**已打开会话**的
有效提示词。这是「可审计」的基础 —— 万一有疑问，会话日志里能看到实际生效的文本。

细节（含 `liveText` 的 volatile 引用探测）见
[references/system-prompt-section.md](references/system-prompt-section.md)。

---

## 常见偏差

| 偏差 | 后果 |
|---|---|
| 顶层 `inject` 写了可能缺席的服务 | 整个插件 INACTIVE，**无任何报错** |
| 用 `ctx.get()` 去等一个还没到的服务 | 永远拿不到，且不会重试 |
| 形状不校验直接调用 | 对面的实现变了就抛在插件里 |
| 取出的方法没 bind | 调的时候 `this` 丢失（尤其在延迟注入的 cb 里） |
| 多服务依赖拆成多次 `ctx.inject` | 先后到达时半残状态；应放进同一个数组 |
| `register` 不带稳定 `id` | 无法做单活守卫，双挂载画两份 |
| 单活守卫写成 fail closed | 守卫本身失败时白屏 —— 必须 fail open |
| 注册与注销分开写 | 泄漏注册，且不报错 |
| 提示段 `order` 写死数字 | 宿主重排后位置跑偏 |
| 提示段没用 `interpolate: false` | 用户文本被当模板解析 |
| 提示段默认值非空 | 每个会话都被悄悄加上前缀 |

## 落地检查清单

- [ ] 顶层 `inject` 里每一项都是**确定存在**的内核服务
- [ ] 所有可选服务走 `ctx.inject([...], cb)`，且用一个数组列全
- [ ] **没有**用 `ctx.get()` 去等一个可能后到的服务
- [ ] 每个宿主面都做了 `typeof === 'function'` 形状校验
- [ ] 每个跨边界方法都 `.bind(拥有者对象)`
- [ ] 每个 `slot.register` 都带稳定 `id`
- [ ] 挂载前跑单活守卫；守卫 try/catch → false（fail open）
- [ ] 注册动作挂在 `c.effect` / `whileServed` / `slots.inject` 的 disposer 上
- [ ] 若注册提示段：默认空、空文本返回空、`interpolate: false`、order 由锚点算
- [ ] 提示段的效果在会话日志里可见（可审计）

## 参考实现

| 用途 | 位置（`<dsh-context-checkout>`） |
|---|---|
| 延迟注入 + 形状校验（宿主侧范例） | `src/host/balance.ts`、`src/host/detail.ts`（`ctx.inject(['connection','sessions'], …)`） |
| 延迟注入 + `whileServed` 清理（客户端范例） | `src/client/index.ts`（`ctx.inject(['configForms'], …)`） |
| 单活挂载守卫 | `src/client/services.ts`（`entrySeated`） |
| 提示段注入全文（含 volatile 活引用） | `src/host/promptInjection.ts`（81 行，整篇可读） |
| 硬 inject 与软 inject 的分工 | `src/host/index.ts`（`export const inject = ['sessionProjections']`） |

> 取材许可：结构与关键语义取自 `bowenliang123/dsh-context`（**Apache-2.0**）。
> 文中代码均为**重写后的骨架**，非整文件搬运。

骨架与逐条语义见
[references/inject-semantics.md](references/inject-semantics.md)、
[references/single-mount-guard.md](references/single-mount-guard.md)、
[references/system-prompt-section.md](references/system-prompt-section.md)。

配套 skill：跨版本探测与基线降级见 `dsh-harness-compat-gate`（同样以 fail open 为第一原则）；
宿主侧按需路由见 `dsh-plugin-fetch-route`；控件落位与插槽契约见 `dsh-client-slot-placement`；
会话标签页见 `dsh-conversation-view-tab`；设置页入口见 `dsh-settings-page`；
插件自己跑多步循环时的终止态、预算与收尾纪律见 `dsh-agent-loop-discipline`。

总览与索引见 `dsh-plugin-dev-guide`。
