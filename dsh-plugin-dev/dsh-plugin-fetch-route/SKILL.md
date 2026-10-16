---
name: dsh-plugin-fetch-route
description: >-
  Use when a DSH plugin's browser half needs data only the host half can produce — a heavy
  collection kept out of the projection value, a machine-local path, a credentialed remote
  read — or when a plugin route 404s, lands outside the authenticated fence, or stalls the
  host on a large session log. Covers the ctx.connection.fetch.register seam (bind-at-
  extraction, c.effect disposer, refuse-quietly), the live-versus-cold session data paths,
  the (persistence, id, revision) cache trust tuple, the host-wide cold-read gate, and the
  yielding fold.
license: MIT
compatibility: >-
  DSH host halves that serve data on demand. Route registration and the cold-read gate were
  read from bowenliang123/dsh-context source (Apache-2.0); the /api fence and sessionQuery /
  sessionProjections faces were confirmed against the installed dsh 0.2.0-rc.2 runtime.
---

# DSH 宿主侧按需路由

目标：浏览器半要的数据，由宿主半在自己的进程里取、经**已认证的 `/api` 围栏**按需送过去。
不是把重数据塞进投影值，也不是自己起一个 HTTP server。

## 一句话决策：路由还是投影

| 数据的形状 | 走哪条 |
|---|---|
| 每条会话一条、小、要随会话列表一起到达 | **投影值流** → 配套 skill `dsh-session-projection` |
| 打开面板/弹窗才要、可能很大、或含不能下发的凭据 | **本篇的按需路由** |
| 两者都要 | 「瘦 wire + 重集合」：投影只下发瘦头，重集合走路由（`dsh-context` 的 `contextTimeline` 就是这么切的） |

判据只有一条：**这条数据会不会随每一次 `session.list` 推送和每一帧 push 一起走？**
会 → 它必须瘦到无所谓；不会 → 它不该占投影的位置。

---

## 一、唯一正确的 seam

宿主自己的文件上传路由、媒体引用路由，都挂在这同一个 seam 上：

```ts
interface ConnectionHostFace {
  fetch?: {
    register?(route: {
      path: string
      methods: readonly string[]
      requestBody: 'buffered'
      fetch: (request: Request) => Response | Promise<Response>
    }): () => void
  }
}
```

**自己起 HTTP server 是错的**：那条路不在认证围栏内，不随 profile 卸载，还得自己解决
会话鉴权。挂在 `register` 上的路由天然落在 `/api` 之下（`path` 直接写 `/api/<插件名>/<端点>`），
是宿主已经认证过的那一层。

三条铁律（每一条都对应一次线上事故）：

| 铁律 | 做法 | 不做会怎样 |
|---|---|---|
| **bind-at-extraction** | 取到方法立刻 `.bind(owner)`：`connection.fetch.register.bind(connection.fetch)` | 未绑定的函数交给别人调用时 `this` 丢失，路由静默失效 |
| **`c.effect()` 管 disposer** | 注册动作整个塞进 `c.effect(() => register({...}), label)` | 服务卸载后路由仍活着 → 悬空路由 |
| **refuse-quietly** | `register` 抛错时 `try/catch` 返回 `false` | 一个恶意/拒绝式的注册表把整个插件拖垮 |

统一封装（这是宿主侧所有路由的唯一入口，别在每处重写）：

```ts
export function registerPostRoute(
  c: EffectScope,
  connection: ConnectionHostFace | undefined,
  path: string,
  fetch: (request: Request) => Response | Promise<Response>,
  label: string,
): boolean {
  const register = typeof connection?.fetch?.register === 'function'
    ? connection.fetch.register.bind(connection.fetch)
    : undefined
  if (register === undefined) return false
  try {
    c.effect(() => register({ path, methods: ['POST'], requestBody: 'buffered', fetch }), label)
  } catch {
    return false          // 拒绝式的注册表不得让插件下线；路由保持缺席即可
  }
  return true
}
```

**注册必须发生在延迟注入里**，因为加载顺序不可假设：

```ts
ctx.inject(['connection'], (c) => {
  const ok = registerPostRoute(c, c.get('connection') as ConnectionHostFace | undefined, ROUTE, handler, 'my-plugin: route')
  if (!ok) return
  gate.live = true                                   // 供投影的 view 每次 serve 时读
  return () => { gate.live = false }                 // 卸载时关掉双形态
})
```

`gate.live` 这个布尔是「路由开了没有」的**唯一真相**：投影的 `view`（是否下发瘦头还是内联全量）
每次 `serve` 都读它，所以路由的生死会自动反映到 wire 形态上 —— 不需要重注册投影。

> 路由的 arm 顺序：如果插件同时有「版本基线门控」（配套 skill `dsh-harness-compat-gate`），
> **所有通道必须在门控的 early return 之前 arm**。通道读的是运行时实证过的接口，
> 门控两侧都要工作；门控只该决定「注册哪些投影单元」。

---

## 二、数据从哪来：活/冷双路径

同一份数据，两种会话状态，取法完全不同：

| | 活会话（本进程里开着） | 冷会话（只在磁盘上、被查看） |
|---|---|---|
| 判定 | `sessions.get(id)` 返回非空 | 同上返回空 |
| 取数 | `ctx.sessionProjections.stateOf(session, key)` | `ctx.sessionQuery.observeSession(id, opts)` |
| 特性 | **已是折叠好的当前态**，不二次折叠、绝不改它 | 返回不可变日志 + 一个 `revision`，需要自己折叠 |
| 收尾 | 无 | 有 `Symbol.dispose`，**必须调** |

```ts
const session = getSession(sessionId)
if (session !== undefined && session !== null) {
  const state = projections.stateOf(session as never, 'myKey')
  return state === undefined ? reply({ ok: true, value: null }) : reply({ ok: true, value: buildDetail(state) })
}
// 冷会话
const observe = /* ctx.get('sessionQuery').observeSession, bind 过 */
const observation = await observe(sessionId, { projectionMode: 'none' })
try { /* 折叠 observation.events */ }
finally { observation[Symbol.dispose]?.() }
```

**「活会话不要二次折叠」是性能与一致性的双重要求**：折叠一次已经在 registry 里了，
再折一次既浪费又可能和 registry 的当前态不一致。

所有「取不到」的分支都返回**同一形态的空值**（这里是一句 `{ ok: true, value: null }`），
不是 500、也不是省略字段 —— 客户端只需要处理一种「没数据」。

---

## 三、缓存与治理

冷折叠很贵（一个 10k 事件的日志要先整份解码，几百 MB 的对象图）。三件事必须做：

### 1. 缓存键是三元组，不是 sessionId

```ts
interface ColdPayload {
  persistence: unknown    // sessionPersistence 的实例
  revision: string        // observation 的 durable change token
  value: unknown
}
```

命中条件三条全等：`hit.revision === revision && hit.persistence === persistence`。
**少了 `persistence` 这一项，换后端之后旧缓存会冒充新数据** —— 这正是宿主自己的观察读取器
键缓存的方式，照抄它对。

两条附加规则：

- **没有 `revision` 就不缓存**（移动目标不许当键）
- **命中后 delete + set** —— 手工 LRU 刷新（上限 4 条足够；一条 payload 已被折叠边界限死）

### 2. 全宿主一个冷读闸

```ts
const gate = makeColdReadGate()   // 一处创建，所有冷读路径共享
const value = await gate.admit(async () => { /* 整份解码 */ })
```

- **FIFO 一次只放一个**（不许查看端叠加解码）
- **水位检查在队列前端执行**，不在入队时 —— 排队期间压力会变
- 水位 = 堆上限的 **2/3**，剩下 1/3 留给这次读自己 + 宿主自己的解码地板
- **探测异常 → 放行（fail open）**：计量器绝不能成为读的阻塞者
- 被跳过时返回 `undefined`，由调用方的「无数据」路径接管，**不是可见的失败**

### 3. 大折叠让出事件循环

```ts
let folded = 0
for (const ev of events) {
  state = apply(state, ev, bounds)
  if (++folded % 1000 === 0) await new Promise(resolve => setTimeout(resolve, 0))
}
```

1000 事件 ≈ 13ms 同步块 —— 任何宿主上都察觉不到；而 30k 事件的冷折叠不会成为一个
不可中断的一秒。**别把块大小调大**：这是一个预算（约 13ms），不是随意数。

---

## 四、响应形态与客户端契约

宿主侧：

```ts
const reply = (value: unknown) =>
  Response.json(value, { headers: { 'cache-control': 'no-store' } })

const failure = (code: string, message: string) =>
  reply({ ok: false, error: { code, message } })
```

- **`no-store` 不是可选的** —— 按需数据的正确性靠 revision 管，不靠 HTTP 缓存
- `body` 解析失败 / `sessionId` 缺失 → `{ ok: false, error: { code, message } }`，
  `code` 带插件前缀（`my-plugin/bad-request`）、兜底 `gateway/internal`
- **参数只从 body 读**，且逐字段类型校验；不信任任何客户端输入

浏览器侧（细节见 [references/client-call-site.md](references/client-call-site.md)）：

```ts
const response = await fetch(ROUTE, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ sessionId }),
})
if (!response.ok) throw new Error(`my-plugin: HTTP ${response.status}`)
const body = asRecord(await response.json())
if (body === null || body.ok !== true) throw new Error('my-plugin: read failed')
// 再对 body.value 做形状校验 —— 拒绝「半合并」的数据，绝不部分采纳
```

**客户端必须重新声明一遍路由常量**：浏览器半不能 `import` 宿主半的任何值（构建纯净门），
所以 `const ROUTE = '/api/my-plugin/detail'` 在两边各写一份，靠注释互指。

---

## 常见偏差

| 偏差 | 后果 |
|---|---|
| 自己 `http.createServer` | 落在认证围栏外、不随 profile 卸载 |
| 忘了 `.bind(owner)` | 路由注册静默失效（`this` 丢失） |
| 注册动作没进 `c.effect()` | 服务卸载后悬空路由 |
| `register` 抛错就往外扔 | 插件随之一并失效 |
| 冷读忘了 `Symbol.dispose` | 观察句柄泄漏 |
| 缓存键少了 `persistence` | 换后端后命中陈旧数据 |
| 移动目标（无 revision）也缓存 | 永远读到旧的 |
| 大折叠不让出事件循环 | 查看一个大日志 = 宿主卡 1 秒 |
| 把冷读闸做成「压力大就失败」 | 查看端看到莫名报错；应当静默走无数据路径 |
| 客户端不做 `body.ok` 二次校验 | 把错误对象当数据渲染 |
| 客户端 `import` 宿主模块拿路由常量 | 构建失败（纯净门）或两份值漂移 |

## 落地检查清单

- [ ] 路由走 `ctx.connection.fetch.register`，`path` 在 `/api/` 之下
- [ ] 取方法处 `.bind(owner)`
- [ ] 注册动作包在 `c.effect(() => register(...), label)` 里
- [ ] `register` 抛错被 catch 且返回 `false`（refuse-quietly）
- [ ] 注册发生在 `ctx.inject(['connection'], …)` 内
- [ ] 若插了版本门控：通道 arm 在 early return **之前**
- [ ] 活/冷双路径都实现，且返回同一种空值形态
- [ ] 冷读调了 `Symbol.dispose`
- [ ] 缓存键含 `(persistence, id, revision)` 三元组；无 revision 不缓存
- [ ] 冷读走共享的 `admit()` 闸；闸的探测异常放行
- [ ] 折叠每 1000 事件 `await setTimeout(0)`
- [ ] 响应带 `cache-control: no-store`
- [ ] 错误用 `{ ok: false, error: { code, message } }`，`code` 带插件前缀
- [ ] 客户端声明了自己的 `ROUTE` 常量 + `ok` 双重校验 + 形状校验后才采纳

## 参考实现

| 用途 | 位置（`<dsh-context-checkout>`） |
|---|---|
| seam 封装 + 三条铁律（**最简范例**） | `src/host/connection.ts`（49 行，整篇可读） |
| 活/冷双路径 + 缓存三元组 + 让出折叠（**最完整范例**） | `src/host/detail.ts` |
| 冷读闸全文 | `src/host/coldRead.ts`（56 行） |
| 出网 + 凭据 + 单飞（第二种路由形态） | `src/host/balance.ts` |
| 带 sessionId 授权的资源路由 | `src/host/attachment.ts` |
| 客户端调用侧 | `src/client/timelineSource.ts`、`src/client/attachmentSource.ts`、`src/client/skills.ts` |
| 宿主真实部署形态 | `…\.dsh\profiles\desktop\node_modules\dsh-context\lib\index.js`（grep `/api/dsh-context/`） |

> 取材许可：结构与关键语义取自 `bowenliang123/dsh-context`（**Apache-2.0**）。
> 文中代码均为**重写后的骨架**，非整文件搬运。

骨架代码与逐字段语义见
[references/connection-seam.md](references/connection-seam.md)、
[references/data-paths.md](references/data-paths.md)、
[references/client-call-site.md](references/client-call-site.md)。

配套 skill：把会话数据流给浏览器（投影侧）见 `dsh-session-projection`；
宿主跨版本探测与基线降级见 `dsh-harness-compat-gate`；从零建双半边插件与客户端构建链见
`dsh-plugin-dual-half-skeleton`；控件落位见 `dsh-client-slot-placement`；
可选服务缺席时的延迟注入与响应式降级见 `dsh-plugin-robust-mount`。

总览与索引见 `dsh-plugin-dev-guide`。
