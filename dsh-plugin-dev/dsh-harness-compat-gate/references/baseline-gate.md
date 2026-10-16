# 基线门控：比较、零值降级单元、升降级

## 1. 版本解析与比较（整段可抄）

```ts
export const BASELINE_DSH_VERSION = '0.1.7-rc.2'   // ← 你的插件声明自己的

function channelRank(channel: 'alpha' | 'beta' | 'rc'): number {
  return channel === 'rc' ? 3 : channel === 'beta' ? 2 : 1
}
const RELEASE_RANK = 4

export interface ParsedVersion { major: number; minor: number; patch: number; rank: number; serial: number }

/** 解析 `v?X.Y.Z[-(alpha|beta|rc)[.N]][+build]`；其它通道（nightly/dev…）不解析。 */
export function parseVersion(version: string): ParsedVersion | null {
  const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)(?:\.(\d+))?)?(?:\+[0-9a-z.-]+)?$/i.exec(version.trim())
  if (match === null) return null
  const channel = match[4]?.toLowerCase() as 'alpha' | 'beta' | 'rc' | undefined
  return {
    major: Number(match[1]), minor: Number(match[2]), patch: Number(match[3]),
    rank: channel === undefined ? RELEASE_RANK : channelRank(channel),
    serial: match[5] ? Number(match[5]) : 0,
  }
}

function compareParsed(a: ParsedVersion, b: ParsedVersion): number {
  if (a.major !== b.major) return a.major - b.major
  if (a.minor !== b.minor) return a.minor - b.minor
  if (a.patch !== b.patch) return a.patch - b.patch
  if (a.rank !== b.rank) return a.rank - b.rank
  return a.serial - b.serial
}

/** FAIL OPEN：不可解析的版本（dev/nightly）不得让可用部署变空白。 */
export function meetsBaseline(version: string, baseline: string = BASELINE_DSH_VERSION): boolean {
  const v = parseVersion(version)
  const b = parseVersion(baseline)
  if (v === null || b === null) return true
  return compareParsed(v, b) >= 0
}
```

四个设计决定：

| 决定 | 说明 |
|---|---|
| 同 `X.Y.Z` 比**通道 rank** | 否则 `0.2.0-rc.2` 会被判为等于/高于 `0.2.0`（rc 是预发布，必须更低） |
| 通道内再比 `serial` | `rc.2` > `rc.1` |
| `+build` 忽略 | 构建元数据不参与优先级（语义化版本规范） |
| 解析失败 → `true` | fail open 的落点 |

**比较函数与基线常量放 `shared/`**：宿主半拿来探测与门控，浏览器半拿同一份常量显示
「需要 X 以上」的提示 —— 两边不许各写一份。

## 2. 门控安装

```ts
export function apply(ctx: Context, config: Config): void {
  // ① 共享资源
  const coldReads = makeColdReadGate()

  // ② 所有「与投影无关」的可选通道先 arm（两侧都要工作）
  watchBalanceChannel(ctx)
  watchSkillCatalog(ctx)
  watchFleetChannel(ctx, coldReads)
  watchAttachmentChannel(ctx, coldReads)

  // ③ 探测 + 门控
  const harnessVersion = detectHarnessVersion(ctx)
  if (harnessVersion !== undefined && !meetsBaseline(harnessVersion)) {
    ctx.sessionProjections.register(createFallbackTimelineDefinition(harnessVersion) as never)
    ctx.sessionProjections.register(createFallbackHeadersDefinition() as never)
    ctx.sessionProjections.register(createFallbackActivityDefinition() as never)
    return
  }

  // ④ 真装配
  const attribution = createToolAttribution(ctx)
  const gate = watchDetailChannel(ctx, resolveBounds(config), coldReads)
  ctx.sessionProjections.register(createContextTimelineDefinition(config, () => gate.live))
  watchActivityBackfill(ctx, coldReads)
  watchPromptInjection(ctx, config)
}
```

**判定条件的写法本身就是 fail open**：

```ts
if (harnessVersion !== undefined && !meetsBaseline(harnessVersion))
```

`undefined`（探测无应答）走**否定分支** → 不进门控 → 正常装配。
两个条件用 `&&` 而不是「先判 undefined 再判版本」，就是为了让「未知 = 通过」在代码里可见。

## 3. 零值降级单元（完整骨架）

```ts
import { z } from 'zod'

/** 不透明的空状态：门控什么都不折，所以任何缓存行都能 seed 它（strip 模式，不丢弃不抛错）。 */
const fallbackStateSchema = z.object({})
type FallbackState = z.infer<typeof fallbackStateSchema>

/** pre-0.1.1 注册表契约的字段。 */
interface LegacyDefinitionShape<V> {
  schema: z.ZodType<V>
  view(state: FallbackState): V
}

function fallbackDefinition<K extends 'keyA' | 'keyB' | 'keyC'>(
  key: K,
  wireSchema: z.ZodType<WireValueMap[K]>,
  value: WireValueMap[K],
): ProjectionDefinition<K, FallbackState> & LegacyDefinitionShape<WireValueMap[K]> {
  const view = (): WireValueMap[K] => value
  return {
    key,
    stateSchema: fallbackStateSchema,
    init: () => ({}),
    apply: state => state,               // ← 恒等：连事件都不看
    wire: { viewSchema: wireSchema, view },
    schema: wireSchema,                   // ← pre-0.1.1
    view,                                 // ← pre-0.1.1
    stateVersion: 1,
  }
}
```

固定值里带上门控记录：

```ts
export function createFallbackTimelineDefinition(current: string) {
  return fallbackDefinition('contextTimeline', contextTimelineSchema, {
    ok: true,
    unsupported: { current: current, minimum: BASELINE_DSH_VERSION },   // ← 客户端据此出提示
    current: { system: 0, tools: 0, user: 0, /* … */ total: 0 },
    requests: [], events: [], nodes: [], droppedNodes: 0, archive: [],
  })
}
```

### 为什么必须「注册」，不能「不注册」

| 做法 | 后果 |
|---|---|
| 低于基线 → **什么都不注册** | 与别的插件共享 key 的注册表空转；界面拿不到这个 key 的值 → 空白或渲染异常 |
| 低于基线 → **注册零值单元** | key 被占住且值合法 → 客户端画出「全 0 + 宿主过旧」的说明卡 |

**成本几乎为零**：`apply` 恒等意味着事件完全不解析，所以老宿主的日志形状差异碰不到任何代码。

要点：

- `stateSchema: z.object({})` 是**空对象**而不是 `z.never()`：缓存里可能残留旧版写的行，
  空 schema 能 seed（strip 掉多余字段），`never` 会抛错
- `stateVersion: 1` 固定：见下节
- 类型上是 `ProjectionDefinition`，但注册时因为状态类型不匹配需要 `as never` 绕过
  （注释里写清「门控不折任何东西，空状态是有意的」）

## 4. `stateVersion` 的升降级语义

降级单元 `stateVersion` 钉在 1，配合注册表的迁移规则：

| 方向 | 注册表行为 | 结果 |
|---|---|---|
| 老宿主 → 升级到新宿主 | 缓存行的版本低于当前 → 重新折叠 | 真单元从日志重建，正确 |
| 新宿主 → 降级到老宿主 | 缓存行版本高于当前 → strip 到空状态（或丢弃/拒绝） | 降级单元拿到空状态（它本来也不读状态） |

**所以降级单元不需要任何迁移代码**：它的状态本来就是空的、`apply` 恒等、`view` 返回常量。
选 1 而不是 0：1 是最低的有效版本号，任何旧缓存行都不会被认为「比它更旧而需要丢弃」。

投影侧的升降级完整语义（bump 时机、strip vs discard vs throw）见配套 skill
`dsh-session-projection` 的 `references/state-version-and-legacy.md`。

## 5. 与「通道」的边界

最后再强调一次本篇的核心分工：

| 组件 | 在门控的哪一侧 |
|---|---|
| 余额查询、技能目录、编队、附件预览等**通道** | **前**（两侧都 arm） |
| 投影单元（真单元 / 零值单元二选一） | **后**（门控决定用哪套） |
| 与配置相关的装配（提示注入、工具归属） | **后** |

判据：**这个组件需不需要解析会话日志、或依赖投影契约？**
不需要 → 放前面，别让老宿主白丢一个能用功能。
