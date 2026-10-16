---
name: dsh-session-projection
description: >-
  Use when a plugin's host half needs to derive per-session state from the committed session
  event log and hand it to the browser — conversation stats, todo/goal snapshots, any
  log-derived read model. Covers the ctx.sessionProjections unit contract (key / stateSchema /
  init / apply / wire / stateVersion), the three load-bearing rules (pure transition returning
  the SAME reference for ignored events, no `wire` means host-only, everything synchronous),
  registration lifetime and shared-key refcounting, the read faces (snapshot / onChanged /
  stateOf / checkpoint), the slim-wire discipline, and the client-side `useProjection` seat.
license: MIT
compatibility: >-
  Host-half DSH plugins on dsh 0.1.7-rc.2 and 0.2.0-rc.2. Contract verified against the installed
  dsh 0.2.0-rc.2 copy of @deepseek-ai/dsh-session-projection (lib/index.js + README.zh.md).
---

# DSH 会话投影单元

目标：让插件的宿主半把**会话日志折叠成一个值**，框架负责驱动、缓存、把值推给浏览器 ——
你不用自己订阅事件、不用自己开 RPC 通道、不用自己重放日志。

一句话分工：**框架负责驱动，领域负责计算。**

## 什么时候用 / 不用

| 场景 | 处置 |
|---|---|
| 客户端要看到逐会话状态（统计、待办、目标、进度） | ✅ 注册一个**带 `wire`** 的单元 |
| 宿主内部记账，浏览器不需要读 | ✅ 注册一个**不带 `wire`** 的单元（host-only） |
| 只需要读日志、不需要持续更新的值 | ❌ 直接读会话日志 / `sessionQuery`，别注册投影 |
| 重集合（几千条明细）也要给浏览器 | ⚠️ 投影只下发**瘦头**，重集合走按需路由（配套 skill `dsh-plugin-fetch-route`） |

不加 `wire` 就是 host-only —— 这是**设计好的开关**，不是「忘了写」。

---

## 契约六字段

```ts
interface ProjectionDefinition<K extends keyof SessionProjectionStateMap, S> {
  key: K
  stateSchema: ZodType<S>
  init(header: SessionHeader, inheritedEventCount: SessionLogOffset): S
  apply(state: S, event: SessionEvent): S
  wire?: {
    viewSchema: ZodType<SessionProjectionMap[K]>
    view(state: S): SessionProjectionMap[K]
  }
  stateVersion: number
}
```

| 字段 | 要点 |
|---|---|
| `key` | 本单元拥有的投影键（`SessionProjectionStateMap` 的条目）。**进程级唯一**，见下 |
| `stateSchema` | 校验持久化状态后才用它播种折叠。**状态必须是 plain JSON** |
| `init` | 拿到会话头 + **精确的 fork 继承切点**。不得从 `firstLiveSeq` 或 `session/end-seed` 反推该切点 |
| `apply` | 纯同步转移：前状态 + 一条已提交事件 → 后状态 |
| `wire` | 客户端视图。**省略 = host-only**（值永不下发浏览器） |
| `stateVersion` | 非负整数。状态字段或折叠语义变了就 +1 |

三个 Zod schema 的分工别搞混：`stateSchema` 校验**内部**状态（持久化缓存播种用），
`wire.viewSchema` 校验**下发**载荷（离开宿主前）。

---

## 三条铁律

### ① 忽略的事件必须返回**同一个引用**

```ts
apply: (state, event) => event.type === 'todo/upsert'
  ? { items: event.data.items }
  : state,                    // ← 返回 state 本身，不是 {...state}
```

框架用 `Object.is` 比较：**引用不变 → 零下游工作**。返回结构相同的新对象算**变化**，
会白白触发一次 view 计算 + 一次发布。

同一条铁律在 `wire.view` 上也成立：对象/数组值若要在「仅内部 state 变化」时抑制发布，
就必须**复用 view 的引用**（live drive 保留前后两个原始 view 做 `Object.is` 比较）。

### ② 一切必须同步

`apply` 和 `wire.view` 都不能 async。返回 Promise 的 view 会被
`wire.viewSchema.parse` 拒绝 —— 这是**机制**层面的拦截，不是约定。

同步也是快照一致性的前提：载体在切出页面切片的**同一 tick** 内读 `snapshot()`，
`asOfSeq` 之所以是一个一致切面正系于此。

### ③ 携带状态的事件必须携带**完整后状态**，绝不带裸增量

这条是写日志一侧的规则（whole-value event rule），但决定了你的 `apply` 能有多简单：
每条事件自带完整新值，`apply` 就是「照抄」。若日志给的是 delta，你的单元就要自己维护
累加逻辑，一旦中间漏一条事件就永久偏了。

---

## 注册与生命周期

```ts
const dispose = ctx.sessionProjections.register(definition)
```

| 语义 | 说明 |
|---|---|
| 注册是 **effect** | disposer 挂在**调用方的 fiber** 上；最后一个注册方卸载 → key 及其缓存 cell 一起消失 |
| 同 key 同 `stateVersion` | **共享一个 cell**，`refs` 计数 +1。同一插件被挂到 N 个 agent preset 就是 N 次注册，key 活到最后一个卸载 |
| 同 key 不同 `stateVersion` | **抛错**。`refusing to share it with stateVersion …` |
| `stateVersion` 非法 | 非负安全整数之外一律**抛错** |
| cell 惰性构建 | 注册晚于事件流、或会话早于注册表，都在首次触达时折叠 `init` 补齐 |

**注册必须发生在服务存在时**，否则 Cordis 会让插件一直 **PENDING**。两种写法：

```ts
// a) 必需：声明进顶层 inject，服务缺席就明确失败
export const inject = ['sessionProjections']

// b) 可选贡献：服务后到也能生效
ctx.inject(['sessionProjections'], (sctx) => {
  sctx.sessionProjections.register(def)
})
```

宿主**读取方**同理：要么声明 `sessionProjections` 依赖，要么在注册表/所需 key 缺席时明确失败 ——
不要静默拿 `undefined` 当空数据用。

---

## 读取面

| 方法 | 用途 | 关键点 |
|---|---|---|
| `snapshot(session)` | 对**所有客户端可见单元**读一个一致切面 | 返回 `{ asOfSeq, values }`；没有可见单元时 `values` 为空；**不含 host-only 单元** |
| `onChanged(listener)` | 订阅逐变更通知 | 只在原始 view 引用变了时回调，`seq` 是致因事件的 seq |
| `stateOf(session, key)` | 读**单个**单元的实时宿主状态 | **不计算无关视图**；key 未注册返回 `undefined` |
| `checkpoint(session)` | 为持久缓存产出行 | 每个已注册 key 一行 `{ ver, seq, val }`，host-only 也一视同仁 |

活跃会话下，宿主侧读自己单元的状态优先走 `stateOf()` —— 它不会触发整轮 view 计算。

---

## 瘦 wire：投影不下发重集合

投影值会出现在**每个 tail page**，所以 wire 值必须是「UI 量级的全量状态」：

- 值本身小（几十到几百字节级），适合放在每一行会话摘要里
- 重集合（明细列表、逐事件记录）**不要**塞进 wire ——
  投影只下发一个**瘦头**，重集合走宿主自己的按需路由，按查看端拉取
- 这是已知限制而非 bug：目前**没有逐 key 的 opt-out 或惰性 key 请求形状**。
  若你的值注定很大，就该拆成「瘦头 wire + 按需路由」两个通道

另一个必须知道的限制：**单元表是进程级的，key 是否存在不能当作逐会话的能力信号**。
任何 agent preset 注册的 key 都会出现在**每个**会话的快照里 —— 客户端必须**读值**，
不能把「key 缺席」当功能缺席。

---

## 客户端怎么读

客户端**不 import** 任何东西，读的是槽位 props 里的标准座位：

```ts
interface SessionStandardProps {
  sessionId?: string
  useProjection?: (key: string) => unknown
  useChat?: UseChatLike
}
```

三个要点：

1. **它是 hook**：必须在组件顶层**无条件**调用，一个 key 一次调用，顺序稳定。
2. **它是可选座位**：先探测 `typeof props.useProjection !== 'function'` → 返回 null
   （能力缺席时降级渲染，不要抛）。
3. **边界收窄**：座位返回 `unknown`，进来就过一遍自己的窄化函数，别把宽值往下传。

```ts
function projectionOf<T>(props, key: string, narrow: (v: unknown) => T | null): T | null {
  if (typeof props.useProjection !== 'function') return null
  return narrow(props.useProjection(key))
}
```

---

## 常见偏差

| 偏差 | 后果 |
|---|---|
| `apply` 对无关事件返回 `{...state}` | 每条事件都触发 view 计算与发布，视图疯狂重渲染 |
| 忘了写 `wire`，却以为值会下发 | 值永远到不了浏览器，且**不报错** |
| `wire.view` 写成 async | `viewSchema.parse` 拒绝（返回的是 Promise） |
| 把重集合塞进 wire | 每个 tail page 变重，会话列表明显变慢 |
| 注册放在服务出现之前 | 插件停在 PENDING，投影不生效 |
| 改了状态字段却不 bump `stateVersion` | 旧的持久化行被继续**前向折叠**，产出垃圾值 |
| key 命名太通用（如 `stats`） | 与别的插件撞 key → 同 key 不同 `stateVersion` 直接抛错 |
| 客户端拿 key 缺席当能力缺席 | 判错：key 是进程级的，全会话都在 |
| 状态里放 Date / Map / class | 违反 plain-JSON 前提，持久化缓存写入受阻 |

## 自检清单

- [ ] `key` 带插件前缀，不会撞车
- [ ] `apply` 对每个无关分支都返回**同一个** `state` 引用
- [ ] 所有函数同步；`view` 里没有 `await` / Promise
- [ ] 状态是 plain JSON（无 Date / Map / Set / class 实例）
- [ ] 需要给浏览器 → 有 `wire`；不需要 → 明确不写并注释原因
- [ ] `wire.view` 对对象值复用引用以抑制无关发布
- [ ] `stateVersion` 是 `0` 或正整数；改状态字段/折叠语义时已 bump
- [ ] 注册写在 `inject` 保证之后，或包在 `ctx.inject(['sessionProjections'], …)` 里
- [ ] wire 值是小体积「全量头」，重集合另开按需通道
- [ ] 客户端用座位 `useProjection` 读值，并做了 `typeof` 探测与窄化
- [ ] 卸载插件后 key 从快照消失（disposer / refs 生效）

## 参考实现

| 用途 | 位置 |
|---|---|
| 契约与驱动的权威说明（中文） | 已装副本 `…\dsh-session-projection\README.zh.md` |
| 注册表实现（`Object.is` 双闸、refs 计数、checkpoint） | 已装副本 `…\dsh-session-projection\lib\index.js` |
| 官方可合并扩展的类型表 | `…\dsh-session-projection\lib\types\types.js` |
| 真实有线单元（含瘦头 wire + schema） | `<dsh-context-checkout>\src\host\timeline.ts` |
| 降级/空投影单元（低于基线时注册） | 同目录 `src\host\fallback.ts` |
| 契约的本地镜像（跨版本编译检查） | 同目录 `src\host\compat.ts` |
| 客户端读取座位 + 窄化 | 同目录 `src\client\services.ts` §`projectionOf` |
| 官方注册表源码 | `<harness-checkout>\packages\session\session-projection\src\index.ts` |

> 「已装副本」= `<dsh-home>\profiles\desktop\node_modules\@deepseek-ai\dsh-session-projection\`
> 或安装目录 `…\resources\app.asar` 内的 `dsh\node_modules\@deepseek-ai\dsh-session-projection\`。
> 本地源码树 `deepseek-harness-master` 是 **0.1.7-rc.2**，与已装 **0.2.0-rc.2** 不同线 ——
> 查**契约与运行时行为**一律以已装副本为准。

> 取材许可：结构与实例取自 `bowenliang123/dsh-context`（**Apache-2.0**）与官方
> `@deepseek-ai/dsh-session-projection`（**MIT**，其 `README.zh.md` 是契约的权威说明）。
> 文中代码均为**重写后的骨架**，非整文件搬运；引用处已标注来源。

契约全文、可复制骨架与跨版本差异见
[references/contract.md](references/contract.md)、
[references/skeleton.md](references/skeleton.md)、
[references/state-version-and-legacy.md](references/state-version-and-legacy.md)。

配套 skill：双半边骨架与构建链见 `dsh-plugin-dual-half-skeleton`；控件落位见
`dsh-client-slot-placement`；设置页入口见 `dsh-settings-page`。

配套 skill 补充：瘦 wire 的另一半 —— 宿主侧按需路由、冷读治理、缓存三元组见
`dsh-plugin-fetch-route`；版本探测与基线降级见 `dsh-harness-compat-gate`
（本 skill 的 `stateVersion` 与降级单元与它直接衔接）；可选服务缺席时的延迟注入见
`dsh-plugin-robust-mount`。

总览与索引见 `dsh-plugin-dev-guide`。
