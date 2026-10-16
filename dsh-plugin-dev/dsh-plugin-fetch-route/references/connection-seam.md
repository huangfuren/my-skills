# 路由 seam 逐字段语义与封装骨架

## 1. 宿主面的结构形状

不要 `import` 宿主的类型。宿主面按**结构**声明，字段全部可选，运行时逐项实证：

```ts
export interface ConnectionHostFace {
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

为什么全可选：这是「严格全局读」惯用法 —— 一个部署可能没有这个服务、可能有但版本更老，
所以每一层都先问「它是不是函数」，是才走。

| 字段 | 取值 | 含义 |
|---|---|---|
| `path` | `'/api/<插件名>/<端点>'` | 已在认证围栏内，**不要**写成不带 `/api` 的裸路径 |
| `methods` | `['POST']` | 按需读一律 POST。用 body 传参而不是 query（sessionId 等不落日志、不落 Referer） |
| `requestBody` | `'buffered'` | 宿主先把 body 读全再交给 handler，handler 里直接 `await request.json()` |
| `fetch` | 你的 handler | 返回标准 `Response`，别返回裸对象 |
| 返回值 | `() => void` | 注销函数。**别自己存起来手动调** —— 交给 `c.effect()` |

## 2. bind-at-extraction

```ts
function fetchRouteRegistrar(connection: ConnectionHostFace | undefined) {
  return typeof connection?.fetch?.register === 'function'
    ? connection.fetch.register.bind(connection.fetch)
    : undefined
}
```

三点：

1. `typeof … === 'function'` 是**形状校验**，不是防空 —— 恶意或不完整的面可能给了个不是函数的 `register`
2. `.bind(connection.fetch)` 绑定的是**拥有者对象**，不是 `connection`。绑错对象同样丢 `this`
3. 绑定发生在**取出的那一刻**（extraction），之后这个函数可以自由传递

同一条规则适用于所有跨边界传递的宿主方法：`sessions.get`、`sessionQuery.observeSession`、
`credentials.resolve` —— 凡是要交给别人调用的，都在取用处 bind。

## 3. c.effect：disposer 的归属

```ts
interface EffectScope {
  effect(effect: () => () => void, hint?: string): unknown
}
```

- `effect` 收到一个**返回 disposer 的函数**；Cordis 在 fiber 卸载时调这个 disposer
- `hint` 是给日志/调试用的标签，写成 `'<插件名>: <用途>'`
- **注册整个动作**放进 effect，而不是「注册 + 手动注册 disposer」：后者一定会漏

## 4. refuse-quietly

```ts
try {
  c.effect(() => register({ path, methods: ['POST'], requestBody: 'buffered', fetch }), label)
} catch {
  return false   // 路由保持缺席，插件继续活着
}
return true
```

**为什么 catch 要吞**：注册表是宿主实现的，可能拒绝、可能在特殊部署下抛错。
一个插件的可选数据通道缺席，不该等于整个插件失效。返回 `false` 让调用方知道
「路由没上」，并据此关掉依赖它的形态（见下节 gate）。

## 5. gate.live：路由生死 → wire 形态的唯一真相

当插件同时有「瘦 wire + 重集合」两态时，用一个可变布尔把路由的生死传给投影的 `view`：

```ts
export interface DetailChannelGate { readonly live: boolean }

export function watchDetailChannel(ctx, bounds, coldReads): DetailChannelGate {
  const gate = { live: false }
  ctx.inject(['connection', 'sessions'], (c) => {
    /* … 准备 handler … */
    if (!registerPostRoute(c, c.get('connection') as ConnectionHostFace | undefined, ROUTE, handler, 'label')) return
    gate.live = true
    return () => { gate.live = false }
  })
  return gate
}
```

注册处：

```ts
const gate = watchDetailChannel(ctx, resolveBounds(config), coldReads)
ctx.sessionProjections.register(createTimelineDefinition(config, () => gate.live))
```

要点：

1. **`view` 每次都读 `gate.live`**（传的是 thunk `() => gate.live`，不是当时的值）——
   路由后到，wire 形态自动从内联切到瘦头，投影**不需要重注册**
2. `ctx.inject([...])` 的返回值就是 disposer：`gate.live = false` 让形态退回内联
3. 依赖多个服务时全部列进 inject 数组（`['connection', 'sessions']`），**任一缺席就整段不 arm**：
   在服务不全时注册一个注定失败的 handler，比不注册更糟

## 6. 依赖的其他宿主面

按需路由除了 `connection`，通常还要读这些（全部结构声明 + 形状校验 + bind）：

| 服务 | 拿它做什么 |
|---|---|
| `sessions.get(id)` | 判定活会话 |
| `sessionProjections.stateOf(session, key)` | 活会话的当前折叠态 |
| `sessionQuery.observeSession(id, { projectionMode: 'none' })` | 冷会话的不可变日志 + revision |
| `sessionPersistence`（实例） | 缓存信任三元组里的 identity 那一项 |
| `credentials.resolve(ref)` | 取凭据（**绝不下发浏览器**） |
| `settings.describe()` | 读插件自己的配置行（拿 endpoint / 凭据 ref） |

## 7. 完整封装骨架

```ts
const ROUTE = '/api/my-plugin/detail'

export function watchChannel(ctx: Context, bounds: Bounds, reads: ColdReadGate): Gate {
  const gate = { live: false }
  const payloads = new Map<string, ColdPayload>()   // 闭包内，随 effect 生命周期自然释放

  ctx.inject(['connection', 'sessions'], (c) => {
    const sessions = c.get('sessions') as SessionsHostFace | undefined
    const getSession = typeof sessions?.get === 'function' ? sessions.get.bind(sessions) : undefined
    if (getSession === undefined) return

    const handler = async (request: Request): Promise<Response> => { /* 见 data-paths.md */ }

    if (!registerPostRoute(c, c.get('connection') as ConnectionHostFace | undefined, ROUTE, handler, 'my-plugin: detail route')) return
    gate.live = true
    return () => { gate.live = false }
  })

  return gate
}
```

**缓存放进 `ctx.inject` 的闭包**（而不是外层函数作用域）：配置变更会重跑 watch，
新闭包 = 新缓存 ⇒ 换了折叠边界的 payload 永远不会被旧配置的读命中。

## 8. 本机复核命令

```bash
# 插件注册了哪些路由
grep -o "/api/[a-z-]*/[a-z-]*" "<插件>/lib/index.js" | sort -u

# 宿主侧自己的路由长什么样（对照 /api 围栏）
grep -rn "connection.fetch.register" "<harness-checkout>/packages" --include=*.ts | head
```
