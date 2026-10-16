# 数据路径：活/冷双路、缓存三元组、冷读闸、让出折叠

## 1. 完整 handler 骨架（可直接改造）

```ts
const FOLD_YIELD_EVENTS = 1_000   // 约 13ms 同步块
const PAYLOAD_CACHE_MAX = 4

const handler = async (request: Request): Promise<Response> => {
  // ① 入参：只从 body 读，逐字段校验
  let sessionId: unknown
  try {
    const body: unknown = await request.json()
    sessionId = body !== null && typeof body === 'object' ? (body as { sessionId?: unknown }).sessionId : undefined
  } catch {
    return failure('my-plugin/bad-request', 'body is not JSON')
  }
  if (typeof sessionId !== 'string' || sessionId === '') {
    return failure('my-plugin/bad-request', 'missing sessionId')
  }

  try {
    // ② 活会话：registry 的当前态，不二次折叠
    const session = getSession(sessionId)
    if (session !== undefined && session !== null) {
      const state = projections.stateOf(session as never, 'myKey')
      if (state === undefined) return reply({ ok: true, value: null })
      return reply({ ok: true, value: buildDetail(state, bounds) })
    }

    // ③ 冷会话：观察 + 折叠
    const query = ctx.get('sessionQuery') as SessionQueryFace | undefined
    const observe = typeof query?.observeSession === 'function' ? query.observeSession.bind(query) : undefined
    if (observe === undefined) return reply({ ok: true, value: null })

    const value = await reads.admit(async () => {
      const observation = await observe(sessionId, { projectionMode: 'none' })
      try {
        // ④ 缓存：三元组命中则直接复用
        const persistence: unknown = ctx.get('sessionPersistence')
        const revision = revisionOf(observation)
        if (revision !== undefined) {
          const hit = payloads.get(sessionId)
          if (hit !== undefined && hit.revision === revision && hit.persistence === persistence) {
            payloads.delete(sessionId); payloads.set(sessionId, hit)   // LRU 刷新
            return hit.value
          }
        }
        // ⑤ 折叠（让出事件循环）
        const events = (observation as { events?: unknown } | null)?.events
        if (!Array.isArray(events)) return null
        let state = createState()
        let folded = 0
        for (const ev of events) {
          state = apply(state, ev as never, bounds)
          if (++folded % FOLD_YIELD_EVENTS === 0) await new Promise(resolve => setTimeout(resolve, 0))
        }
        const detail = buildDetail(state, bounds)
        // ⑥ 回填缓存（只在有 revision 时）
        if (revision !== undefined) {
          payloads.delete(sessionId)
          payloads.set(sessionId, { persistence, revision, value: detail })
          for (const oldest of payloads.keys()) {
            if (payloads.size <= PAYLOAD_CACHE_MAX) break
            payloads.delete(oldest)
          }
        }
        return detail
      } finally {
        // ⑦ 一定释放观察句柄
        const dispose = (observation as { [Symbol.dispose]?: unknown } | null)?.[Symbol.dispose]
        if (typeof dispose === 'function') dispose.call(observation)
      }
    })

    return reply({ ok: true, value: value ?? null })   // 被闸跳过 = 同一种空值
  } catch (err) {
    return failure('gateway/internal', err instanceof Error ? err.message : String(err))
  }
}
```

## 2. 为什么活会话不许二次折叠

`stateOf()` 返回的是 registry 里**当前正被维护**的那份折叠态：

- 再折一遍 = 白烧 CPU，而且是从日志重放，**可能落后于 registry 的实时态**
- 若为了「顺便更新」而改动它 → 破坏了投影契约（`apply` 必须是纯转移、状态不可外泄修改）

活会话路径下 `stateOf` 返回 `undefined` 是正常情况（该 key 还没被注册/还没初始化），
此时给空值，不要回落到冷路径重折 —— 活会话的权威就在 registry。

## 3. 冷会话的观察对象

```ts
interface SessionQueryFace {
  observeSession?(id: string, options: unknown): Promise<unknown>
}
```

- `options` 传 `{ projectionMode: 'none' }`：**只要原始事件，不要宿主再折一遍**
- 返回值里用到的三个东西（全部要形状校验，不能直接信）：
  - `revision`：durable change token，**字符串且非空**才算数
  - `events`：数组；不是数组 = 无数据
  - `[Symbol.dispose]`：可能是函数，**调用时必须 `call(observation)`** 保住 `this`

```ts
function revisionOf(observation: unknown): string | undefined {
  const revision = (observation as { revision?: unknown } | null)?.revision
  return typeof revision === 'string' && revision !== '' ? revision : undefined
}
```

> 宿主自己的观察读取器就用 `(identity, id, revision)` 这个三元组键它的缓存 —— 照抄，
> 别自己发明一套。**注**：三元组里的两项来源不同：`persistence` 是实例身份（当前服务对象），
> `revision` 是数据版本。只比 revision 会在「换了一个 persistence 后端但 revision 字符串撞上」时出错。

## 4. 冷读闸（coldRead.ts 全文语义）

```ts
export interface ColdReadGate {
  admit<T>(read: () => Promise<T>): Promise<T | undefined>
}

const HIGH_WATER = 2 / 3
```

```ts
export function makeColdReadGate(reading: () => HeapReading = v8Reading): ColdReadGate {
  const clear = (): boolean => {
    try {
      const { used, limit } = reading()
      if (!Number.isFinite(used) || !Number.isFinite(limit) || limit <= 0) return true
      return used < limit * HIGH_WATER
    } catch {
      return true          // 探测炸了 → 放行
    }
  }
  let tail: Promise<unknown> = Promise.resolve()
  return {
    admit<T>(read: () => Promise<T>): Promise<T | undefined> {
      // 水位检查跑在队列前端，不在入队时 —— 排队期间压力会变
      const run = tail.then(() => (clear() ? read() : undefined))
      tail = run.then(() => {}, () => {})       // 队列不断链
      return run
    },
  }
}
```

设计要点，逐条都有理由：

| 设计 | 理由 |
|---|---|
| FIFO 串行 | 一次只解码一份大日志，查看端不能叠加 |
| 队列前端查水位 | 入队时压力 ≠ 执行时压力 |
| 2/3 水位 | 剩 1/3 给这次解码本身 + 宿主自己的地板 |
| 探测异常放行 | 计量器绝不能变成读的阻塞者（fail open） |
| 跳过 → `undefined` | 调用方的「无数据」路径接管，**不是可见失败** |
| `reading` 可注入 | 测试用；生产走 `getHeapStatistics()` |

`v8Reading`：

```ts
import { getHeapStatistics } from 'node:v8'
function v8Reading(): HeapReading {
  const stats = getHeapStatistics()
  return { used: stats.used_heap_size, limit: stats.heap_size_limit }
}
```

**一个宿主进程一个闸**，所有冷读路径（详情路由、编队、预热、附件预览）共享同一个实例。
在 `apply()` 顶部创建一次然后往下传。

## 5. 让出事件循环

```ts
if (++folded % FOLD_YIELD_EVENTS === 0) await new Promise(resolve => setTimeout(resolve, 0))
```

- 预算：**约 13µs/事件 × 1000 ≈ 13ms** 同步块。任何宿主上都低于可感知阈值
- 反例：30k 事件的冷折叠不让出 = 一次不可中断的**近一秒**卡顿，落在某个查看请求里
- **调大块 = 调大最大卡顿**，不要因为「await 有开销」就调大到 10000
- 用 `setTimeout(0)` 而不是 `setImmediate`/`queueMicrotask`：需要的是让出到宏任务队列，
  微任务不让出

## 6. 缓存生命周期

- 缓存放在 `watchChannel` 内的 `ctx.inject` 闭包里（见 `connection-seam.md` §7）：
  配置重挂载 = 新闭包 = 新缓存
- 上限 4 条：一条 payload 已被折叠边界限死（约 ≲1MB），4 条足够覆盖「来回翻几个会话」
- 页面重载会重新请求 —— 缓存的目的正是「别重折整份日志」，不是持久化
- 缓存值必须是**已完成形状校验**的最终 payload（别缓存中间态）
