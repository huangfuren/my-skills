# `stateVersion` 语义与跨版本差异

这份文件回答三件事：什么时候必须 bump `stateVersion`；升级/降级时框架怎么处置旧数据；
两代宿主（0.1.7-rc.2 / 0.2.0-rc.2）在契约上到底差在哪。

---

## 1. `stateVersion` 的三种语义

| 情形 | 行为 |
|---|---|
| 同 key + **同** `stateVersion` | 共享一个 cell，`refs` 计数 +1（同一插件挂 N 个 agent preset 就是 N 次） |
| 同 key + **异** `stateVersion` | **抛错**：`is already registered at stateVersion X; refusing to share it with stateVersion Y` |
| `stateVersion` 非「非负安全整数」 | **抛错**：`stateVersion must be a non-negative integer, got …` |
| 已持久化的行 `ver` ≠ 当前单元 `stateVersion` | **丢弃该行**，从日志重新折叠 |

它的真实身份是**持久化缓存的失效键**。改状态字段却不 bump 的后果最隐蔽：

> 旧行被当作**有效前缀**继续前向折叠 → 产出**静默错误的值**，不报错。

---

## 2. 什么时候必须 bump

| 改动 | bump？ |
|---|---|
| 增/删/改 `stateSchema` 的字段、类型、可选性 | ✅ 必须 |
| 改 `apply` 的折叠语义（同一事件现在折出不同状态） | ✅ 必须 |
| 改 `init` 的初值（影响空日志与会话头语义） | ✅ 必须 |
| 改 `key` 名 | 不需要（那是新单元）；但旧 key 的行会成为孤儿 |
| 只改 `wire.view` / `viewSchema` | ❌ 不需要（wire 不落缓存） |
| 只改注释、重命名局部变量 | ❌ 不需要 |
| 改 `init` 只影响 fork 继承行为 | ✅ 保险起见 bump |

**判定口诀**：只要「同一份事件序列在新旧代码下折叠出的 `state` 不同」或「旧 `state` 在新
`stateSchema` 下不合法」→ bump。只影响下发形状（wire）不影响状态 → 不用。

---

## 3. 升级 / 降级时框架怎么处置

`dsh-context` 的降级单元把这条路径写得最清楚（`src/host/fallback.ts` 头注释语义）：

> `stateVersion` **固定在 1**：一次**降级**会重折叠 timeline 键、并把 headers 键**剥离成空状态**
> 播种（gate 从不去读它）；**升回**时则丢弃或拒绝那些降级行，两者都从日志重折叠。

抽象成规则：

| 方向 | 框架行为 |
|---|---|
| 升版（新 `ver` > 旧行 `ver`） | 旧行**不匹配 → 丢弃**，从日志重折叠。安全，只是冷启动慢一次 |
| 降版（新 `ver` < 旧行 `ver`） | 旧行同样不匹配 → 丢弃。所以「降级 = 回到日志重折叠」，不会读到新格式的状态 |
| `stateSchema` 校验失败的旧行 | 丢弃（不抛），从日志重折叠 |
| 行 `seq` 越过存储日志末尾 | 丢弃（防「声称折了不存在的事件」） |

关键推论：**`stateVersion` 只增不减**。你可以从 1 → 2 → 3，但不要回退数字 ——
回退本身不会崩（行仍会因不匹配被丢弃），但会与别人撞号时更难排查。

---

## 4. 两代宿主的差异：**全在类型层，运行层一致**

### 0.1.7-rc.2：`register` 有**两个重载**

（第一手核实：`deepseek-harness-master/packages/session/session-projection/src/index.ts:233-255`）

```ts
// 重载 A：有线单元 —— wire 被显式收窄成「必填」
register<K extends keyof SessionProjectionMap, S extends SessionProjectionStateMap[K]>(
  definition: Omit<ProjectionDefinition<K, S>, 'wire'> & {
    wire: NonNullable<ProjectionDefinition<K, S>['wire']>
  },
): () => void

// 重载 B：host-only 单元 —— key 被显式收窄成「不在 SessionProjectionMap 里」
register<K extends Exclude<keyof SessionProjectionStateMap, keyof SessionProjectionMap>, S extends SessionProjectionStateMap[K]>(
  definition: Omit<ProjectionDefinition<K, S>, 'wire'>,
): () => void
```

由此推出**两条 0.1.7 特有的类型约束**：

1. **描述成「`wire?` 可选」的 def 两个重载都匹配不上** → 编译报错。
   这正是 `dsh-context` 要自己镜像一份 `ProjectionDefinition`（`src/host/compat.ts`）的原因，
   它的注释原话：*"the installed dsh types pin the oldest supported surface (0.1.7-rc.2),
   whose optional `wire?` fails the registry's wired-register overload"*。
2. **host-only 的 key 不能声明在 `SessionProjectionMap` 里**，只能出现在
   `SessionProjectionStateMap`（重载 B 的 `Exclude<…>`）。

### 0.2.0-rc.2：单个 `register`，`wire` 用条件类型表达

（第一手核实：已装 `lib/index.js:68` 只有**一个** `register(definition)` 实现）

```ts
wire?: K extends keyof SessionProjectionMap ? { viewSchema; view } : never
```

两条约束都**放宽**了：

1. def 的类型可以直接写成 `wire?` 可选，不必再镜像；
2. 一个 **client-visible 的 key（在 `SessionProjectionMap` 里）也可以注册成 host-only**
   （省略 `wire` 即可，类型上 `wire` 是 optional）。

### 运行层：两代**逐行相同**

比对两代的实现体（0.1.7 源码 256–291 行 vs 已装 0.2.0 的 `lib/index.js` 68–101 行），
下列语义**完全一致**：

- 同一个 `stateVersion` 非负安全整数检查（连报错文案都一样）
- 同 key 异版本抛错（文案一样）
- 共享 cell + `refs` 计数 + 最后一个卸载才 delete key
- `ctx.effect(…, 'sessionProjections.register()')` 的 effect 名
- `wire` 包一层 `(state) => wire.view(state)`

**实务结论**：写单元时不必为两代分叉代码；只在**类型**上留意 —— 若要同时支持两代且用
TypeScript，就把契约镜像成自己的接口（照 `compat.ts` 的做法），否则在 0.1.7 上会编译失败。

---

## 5. pre-0.1.1：顶层 `schema` / `view` 别名

更老的注册表读的是**顶层** `schema` + `view`，而不是 `stateSchema` + `wire`。
只在**基线以下**的宿主上才需要（那时降级单元本身就是插件的全部行为）：

```ts
interface LegacyDefinitionShape<V> {
  schema: ZodType<V>
  view(state: FallbackState): V
}

const view = (): MyView => fixedValue
return {
  key, stateSchema, init, apply,
  wire: { viewSchema, view },
  schema: viewSchema,   // ← pre-0.1.1 注册表读这个
  view,                 // ← 同上
  stateVersion: 1,
}
```

在基线以上的宿主上这两个字段**被忽略**，是无害的兼容尾巴。

---

## 6. 低于基线时的降级单元

配合 `dsh-harness-compat-gate`：探测到版本低于基线时，**注册空单元而不是真单元**，
让客户端「渲染空卡片 + 升级提示」而不是崩：

```ts
const fallbackStateSchema = z.object({})   // 不透明空状态
type FallbackState = z.infer<typeof fallbackStateSchema>

function fallbackDefinition(key, wireSchema, value) {
  const view = () => value              // 固定零值
  return {
    key,
    stateSchema: fallbackStateSchema,   // 任何缓存行都能播种它（strip 模式，不抛）
    init: () => ({}),
    apply: state => state,              // 恒等：什么也不折叠
    wire: { viewSchema: wireSchema, view },
    stateVersion: 1,
  }
}

// 零值里带上 gate 记录，客户端据此显示升级提示
createFallbackTimelineDefinition(currentVersion) => ({
  ok: true,
  unsupported: { current: currentVersion, minimum: BASELINE_DSH_VERSION },
  current: { /* 全 0 */ },
  requests: [], events: [], nodes: [],
})
```

四个设计点：

1. `stateSchema` 用 `z.object({})` —— **不透明**，所以任何形态的旧缓存行都能播种（strip 而非抛）
2. `apply` 是恒等 —— 低于基线的日志形状不在兼容矩阵内，不解析才是安全做法
3. 零值携带 `unsupported: { current, minimum }` —— 客户端据此渲染提示，而不是空白
4. `stateVersion` 钉在 1 且不随真单元变 —— 降级/升回都走「丢弃 + 重折叠」

**探测不到版本时不要走这条路**：fail open，按正常组合注册真单元。

---

## 7. `@deepseek-ai/dsh-session-projection/types` 这个出口

类型表有两个入口，**符号身份相同**（re-export 保留）：

| 入口 | 用途 |
|---|---|
| 包根 `@deepseek-ai/dsh-session-projection` | 宿主半：连同 `ctx.sessionProjections` 的 cordis `Context` 合并一起引入 |
| `…/types` | **客户端聚合**：只拿类型表，**不拖进宿主侧的 cordis Context 合并**（`dsh-agent → dsh-session` 那条链） |

所以在 `src/shared/` 里声明合并时，用 `/types` 出口：

```ts
// 好：客户端也能安全引入
declare module '@deepseek-ai/dsh-session-projection/types' { /* … */ }
```

而不是从包根引入（会把宿主侧的 cordis 合并带进浏览器 bundle）。

> 已装副本的注释原话：*"Domain packages may declare-merge through either the package root or
> this outlet — re-export preserves symbol identity, so both land on the same table."*

---

## 8. 交叉引用

- 契约字段与读取面全文 → [contract.md](contract.md)
- 可复制骨架 → [skeleton.md](skeleton.md)
- 版本探测与门控 → skill `dsh-harness-compat-gate`
- 该仓的文档工程实践（「规则/限制/检查/流程」四段式 + **源码优先于文档**）
  → `…\dsh-context-main\docs\compatibility.md`，可作候选 4 的附例参考
