# 契约全文：`ctx.sessionProjections`

核实方式：从**已装** dsh `0.2.0-rc.2` 的 `app.asar` 内提取
`dsh/node_modules/@deepseek-ai/dsh-session-projection/lib/index.js`（437 行，压缩前）
与 `README.zh.md`（144 行），逐条比对。行号引用的是该提取副本。

包身份：`@deepseek-ai/dsh-session-projection` `0.2.0-rc.2`，license MIT，
peer 依赖 `@deepseek-ai/dsh-session@0.2.0-rc.2` + `@deepseek-ai/cordis@~4.0.4`。

---

## 1. 服务声明

```ts
declare module '@deepseek-ai/cordis' {
  interface Context {
    sessionProjections: SessionProjectionRegistry
  }
}

export class SessionProjectionRegistry extends Service { /* … */ }
```

注册表本身是一个 Cordis `Service`，所以它和其他服务一样**有出现先后**：
服务不到，你的协议行拿不到 `ctx.sessionProjections`。

---

## 2. 单元契约（原文语义）

```ts
export interface ProjectionDefinition<
  K extends keyof SessionProjectionStateMap,
  S extends SessionProjectionStateMap[K] = SessionProjectionStateMap[K],
> {
  key: K
  stateSchema: ZodType<S>
  init(header: SessionHeader, inheritedEventCount: SessionLogOffset): NoInfer<S>
  apply(state: NoInfer<S>, event: SessionEvent): NoInfer<S>
  wire?: K extends keyof SessionProjectionMap ? {
    viewSchema: ZodType<SessionProjectionMap[K]>
    view(state: NoInfer<S>): SessionProjectionMap[K]
  } : never
  stateVersion: number
}
```

逐字段的设计意图（源码注释语义）：

| 字段 | 注释要点 |
|---|---|
| 整体 | 「一个领域的**状态驱动计算单元**：纯同步折叠 + 声明 + 可选客户端视图 —— **绝不是不透明的 getter**。框架在每个已提交事件上驱动 `apply`；领域不持有任何订阅，只拥有计算。所有函数**必须同步**（异步单元会撕开载体的连续性切面），且 `state` 必须是 plain JSON（持久化缓存的前提）」 |
| `key` | 「本单元拥有的投影键（它的 `SessionProjectionStateMap` 条目）」 |
| `stateSchema` | 「在播种折叠之前校验持久化状态」 |
| `init` | 「空日志及其不可变 Session 元数据的状态」。参数 `inheritedEventCount` 是**精确的 fork 继承前缀长度** |
| `apply` | 「纯转移：前状态 + 一条已提交事件 → 后状态。**对不关心的事件 MUST 返回同一个状态引用** —— 引用不变（`Object.is`）产生零下游工作」 |
| `wire` | 「客户端视图。host-only 单元省略」 |
| `stateVersion` | 「持久化缓存的失效版本：序列化状态字段或折叠语义变化时递增，让旧单元的持久化 `(sessionId, key, ver, seq, val)` 行被**丢弃**而不是被前向折叠成垃圾。非负整数」 |

### `wire.view` 的特殊约定

> live drive 保留**两个最新的原始结果**并用 `Object.is` 比较；
> 对象值的 view **必须复用引用**才能在仅内部 state 变化时抑制发布。

即：`view` 每次返回**同一个对象**时视为未变化；返回结构相同的新对象**仍然算变化**。

---

## 3. 驱动机制（`Object.is` 双闸）

每个已提交事件按注册顺序驱动每个已注册单元；两层闸门：

```
state 引用不变（Object.is） → 跳过 view 计算          ← 第一层
view  原始结果引用不变       → 抑制发布 / 不通知变更流 ← 第二层
```

其它实现事实：

| 事实 | 含义 |
|---|---|
| 注册表只订阅**一次** `session/event` | 主动驱动（eager），不是拉取 |
| cell **惰性构建** | 「注册晚于事件已流动的单元，或早于注册表的会话」在**首次触达**（事件或读取）时把 `init` 折叠到内存日志上 |
| `UnitCell = { state, observedSeq, views: [上一个, 当前] }` | `observedSeq` 是「**经过** `apply` 的最后一个事件」，**不论是否变化** |
| `Registration = { def, cells: WeakMap<Session, UnitCell>, refs }` | 一个 def 服务所有会话（cells 按 `Session` 键）；注册方是**逐会话**的 |
| `refs` 存在的理由 | 一个 agent preset 会把同一个工具包挂到每个 agent 上 → N 个会话注册同一个 key N 次。没有计数，第一个注册方就会拿走 disposer，它那个会话结束会把 key 从**所有**活跃会话剥掉 |

---

## 4. `register()`

```ts
const dispose = ctx.sessionProjections.register(definition)
```

实现（提取副本 68–101 行）：

```js
register(definition) {
  const wire = definition.wire
  const erased = {
    key, stateSchema, init, apply,
    wire: wire === void 0 ? void 0 : {
      viewSchema: wire.viewSchema,
      view: (state) => wire.view(state),   // ← 包一层，保证 view 里 this 不丢
    },
    stateVersion: definition.stateVersion,
  }
  if (!Number.isSafeInteger(definition.stateVersion) || definition.stateVersion < 0)
    throw new Error(`session projection ${JSON.stringify(definition.key)} stateVersion must be a non-negative integer, got ${String(definition.stateVersion)}`)
  // …
  if (existing !== undefined) {
    if (existing.def.stateVersion !== erased.stateVersion)
      throw new Error(`session projection key ${JSON.stringify(key)} is already registered at stateVersion ${String(existing.def.stateVersion)}; refusing to share it with stateVersion ${String(erased.stateVersion)}`)
    existing.refs += 1
    // …
  }
  // 卸载：
  live.refs -= 1
  if (live.refs === 0) this.registrations.delete(key)
}
```

关键点：

- 返回的是 **disposer**，且注册被包成 effect，名字是 `"sessionProjections.register()"`
- **同 key 同版本 → 共享**；**同 key 异版本 → 抛错**；`stateVersion` 非负安全整数之外的任何值 → 抛错
- `erase` 时把 `wire.view` 又包了一层（`(state) => wire.view(state)`）—— 所以你的 `view`
  里不要依赖 `this`

> 实务结论：**key 一定要带插件前缀**。撞 key 的代价不是覆盖，是**直接抛错让插件挂掉**。

---

## 5. 读取面

| 方法 | 签名 | 语义 |
|---|---|---|
| `snapshot(session)` | `→ { asOfSeq, values }` | 「对每个已注册的**客户端可见**单元读一个一致切面」。`asOfSeq` 是所有值共同反映到的最后一个事件的 seq（空日志为 `-1`）。**跳过 `wire === undefined` 的单元**；`values` 在没有选中单元时为空对象 |
| `onChanged(listener)` | `listener(session, key, value, seq)` | 「每个原始 view 按 `Object.is` 变化的客户端可见单元、每条已提交事件回调一次」。`value` 是**已过 schema 校验**的输出；`seq` 是单元在发出时的水位（致因事件的 seq） |
| `stateOf(session, key)` | `→ S \| undefined` | 「在读游标处**物化每一个已注册单元**之后，读**单个**单元的当前宿主状态。**不产出无关的 wire 视图**」。key 未注册 → `undefined` |
| `checkpoint(session)` | `→ Record<string, {ver, seq, val}>` | 「每个已注册 key 一行」（host-only 也包含）。`ver` = 单元 `stateVersion`；`seq` = 折叠进 `val` 的最后一个事件（空日志 `-1`） |
| `restoreFloor(session, …)` | | 「把尾部读取锚定在最低可用水位之前一个事件处」，**使缩短的日志可被检出** |
| `restore(session, …)` | | 「把持久行在存储后缀上重新折叠，**丢弃任何 `ver` 不匹配、或声称越过存储末尾的行**」 |

两类游标不要混：

- `SessionSeqCursor` —— 检查点水位（**空日志为 `-1`**），用于「值反映到哪」
- `SessionLogOffset` —— 回放起点（**从 0 起**），用于「从哪重放」

`ProjectionSnapshot.asOfSeq` 的类型就是 `SessionSeqCursor`。

---

## 6. 持久化缓存与行

```ts
interface ProjectionCheckpointRow {
  ver: number    // 注册单元的 stateVersion
  seq: number    // 折叠进 val 的最后一个事件；空日志 -1
  val: unknown   // 单元的**内部**状态（plain JSON）
}
```

> 一行**从不是权威**，只是折叠捷径：`restore` 在版本不匹配、或该行声称的事件越过了
> 存储的日志末尾时**丢弃它**。

所以 `stateVersion` 的角色是**缓存失效键**：如果你改了状态字段却不 bump，
旧行会被当作有效前缀继续前向折叠 —— 产出的是**静默错误的值**，不是报错。

---

## 7. 已知限制（当前包的约束，不是待办）

| 限制 | 实务含义 |
|---|---|
| **每个尾页携带每个 client-visible key** | 尚无极细粒度的惰性 key 请求形状。值都是 UI 量级时可接受；某领域的值变大就该重议 —— 这也是「瘦 wire + 按需路由」存在的原因 |
| **单元表是进程级的** | 「任何 agent preset 注册的 key 都会出现在每个会话的快照里」。**客户端必须读值，不能把 key 缺席当功能缺席** |
| **主动驱动逐事件触达每个单元** | 按构造开销很低（全量值规则 + 两级引用闸门）。若出现热点路径，可加按单元的事件类型预过滤 |
| **cell 只活在内存里** | 重启后首次触达时靠折叠日志重建；挂了 `dsh-session-projection-cache` 的组合改由持久行播种该折叠 |
| **同步纪律只有部分可机械把关** | `wire.viewSchema.parse` 能拒绝返回 Promise 的 view；但**阻塞的 `apply`**、或读取撕裂的非会话状态的 `apply`，只能靠评审把关 |

---

## 8. 在你本机复核（可重跑）

```bash
# 1) 确认已装版本（必须是 0.2.0-rc.2 这条线）
node -e "console.log(require('<dsh-home>/profiles/desktop/node_modules/@deepseek-ai/dsh-session-projection/package.json').version)"

# 2) 若不在 profile 下，从安装目录提取
cd <workspace>
node _asar.mjs cat "<install-dir>/resources/app.asar" \
  "dsh/node_modules/@deepseek-ai/dsh-session-projection/lib/index.js" > /tmp/proj.js

# 3) 关键语义自证
grep -n "stateVersion must be\|refusing to share\|Object.is\|refs === 0\|wire === void 0" /tmp/proj.js

# 4) 中文契约说明
node _asar.mjs cat "<install-dir>/resources/app.asar" \
  "dsh/node_modules/@deepseek-ai/dsh-session-projection/README.zh.md" | head -70
```

> ⚠️ 本地源码树 `<harness-checkout>` 是 **0.1.7-rc.2**（旧线）。
> 它的 `src/index.ts` 读起来一样，但 `wire` 的可选性与注册重载**不同** ——
> 见 [state-version-and-legacy.md](state-version-and-legacy.md)。
