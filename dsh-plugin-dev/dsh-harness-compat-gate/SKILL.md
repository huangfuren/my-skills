---
name: dsh-harness-compat-gate
description: >-
  Use when a DSH plugin must survive more than one harness release — when a feature silently
  blanks on an older dsh, when a config field only exists on some harnesses, when a persisted
  value from an older version crashes the entry, or when you need to declare a support
  matrix. Covers the fail-open version probe (two anchors: the running module tree with an
  isInside guard, and the home mirror), the release-channel-aware version compare, the
  baseline gate that registers zero-value fallback projection units below the baseline, the
  pre-0.1.1 legacy aliases, and the feature-detected field modifiers that let one schema
  serve every harness.
license: MIT
compatibility: >-
  Any DSH plugin with a host half. Probe, compare and gate logic read from
  bowenliang123/dsh-context source (Apache-2.0). Concrete baseline numbers here are that
  plugin's own (0.1.7-rc.2); your plugin declares its own.
---

# 跨版本生存：探测、门控、降级

一个 DSH 插件迟早要面对「宿主不止一个版本」。这一篇只解决一件事：
**让插件在不认识的宿主上退化，而不是崩掉或变成白屏。**

## 第一原则：fail open

贯穿全篇，无例外：

> **探测不确定 / 解析失败 / 服务缺席 → 一律按「支持」处理。**

理由很直接：**误判的代价不对称**。

| 误判方向 | 后果 |
|---|---|
| 误判为「太老」→ 关掉功能 | 一个本来完全可用的部署**变成空白**（用户视角：插件坏了） |
| 误判为「支持」→ 照常跑 | 最多是某个新特性没生效（用户视角：少了点东西） |

所以凡是「拿不准」的分支，全部导向「继续跑」。

## 三层结构

| 层 | 干什么 | 出错时 |
|---|---|---|
| **声明层** | `package.json` 的 `dsh.compatibility.dshReleases` | 不影响运行，是给市场和兼容性阅读看的 |
| **探测层** | 运行时读宿主包清单，得出一个版本号 | 任何失败 → `undefined` |
| **门控层** | 比较版本，决定注册「真单元」还是「零值降级单元」 | `undefined` 视为满足 |

---

## 一、探测：双锚点，且不许 import

**核心约束：探测不许为了读版本而 import 宿主包。** 一旦 import，插件的依赖图就被绑上了
那个包，探测本身反而成了兼容性负担。所以走**解析清单文件**这条路。

两个锚点，按序尝试，先答者胜：

### 锚点 1：运行模块树（优先级高）

```ts
import.meta.resolve(specifier)
```

用**进程自己解析那些 import 的那条流水线**去解析宿主包 —— 好处是：如果宿主外壳重定向了
插件的 import 路径，探测会被同样地重定向，两者永远一致。

两个必须的守卫：

1. **`isInside` 守卫** —— 运行树里解析到的「见证」如果落在**插件自己的包目录**内，
   那是插件自己的依赖闭包，不是宿主。丢掉它：

   ```ts
   function isInside(root: string, candidate: string): boolean {
     const rel = relative(root, candidate)
     return !rel.startsWith('..') && !isAbsolute(rel)   // 跨盘符时 relative 返回绝对路径
   }
   ```
   两个条件都要：`..` 开头是往上级逃逸；跨盘符时 `relative()` 直接返回绝对路径（也逃逸）。

2. **ownPackageRoot 用自引用定位**：用 `import.meta.resolve('<包名>/package.json')` 定自己
   的根（源码树和打包安装下都得到正确答案）；解析不了就退化到本文件所在目录 ——
   守卫覆盖变小，但**仍然不会把自己的 `node_modules` 认成宿主**。

### 锚点 2：home 镜像

```ts
const homePath = ctx.get('dshHomePath')             // 应用启动期提供的 home 解析器
const req = createRequire(homePath('profiles', '<插件名>-version-probe.cjs'))
const version = req.resolve('@deepseek-ai/dsh/package.json')   // 之类
```

`profiles/node_modules` 镜像记录了**最后一次自愈过它的那次安装**。
`@deepseek-ai/dsh` 这个 CLI 包**只走这个锚点** —— 插件从来不 import 它。

### 读版本的两种手法

| 手法 | 何时用 |
|---|---|
| `resolve(pkg + '/package.json')` 然后读 | 首选；但导出表可能不暴露这个子路径 |
| `resolve(pkg)` 拿入口 → 逐级向上找同名的 `package.json` | 兜底；打包成可执行文件的代理只导出入口桩，但版本是真的 |

向上找时**必须校验 `name` 匹配**，否则会误读到某个祖先目录的无关清单。

任何一步失败 → `undefined`。**不要抛、不要兜一个默认版本号**。

---

## 二、门控：比较 + 零值降级单元

### 版本比较要认发布通道

`v?X.Y.Z[-(alpha|beta|rc)[.N]][+build]`，同 `X.Y.Z` 时按通道排序：
**正式版 > rc > beta > alpha**（分别 rank 4/3/2/1）。

```ts
export function meetsBaseline(version: string, baseline: string): boolean {
  const v = parseVersion(version)
  const b = parseVersion(baseline)
  if (v === null || b === null) return true      // ← FAIL OPEN
  return compareParsed(v, b) >= 0
}
```

**解析不出来的（dev / nightly 构建）返回 `true`**：只有「确实证明低于基线」才拦。

### 门控落点

```ts
const harnessVersion = detectHarnessVersion(ctx)
if (harnessVersion !== undefined && !meetsBaseline(harnessVersion)) {
  ctx.sessionProjections.register(createFallbackTimelineDefinition(harnessVersion) as never)
  ctx.sessionProjections.register(createFallbackHeadersDefinition() as never)
  ctx.sessionProjections.register(createFallbackActivityDefinition() as never)
  return     // ← 之后所有真单元都不注册
}
// …正常装配…
```

**降级单元的形状**（不是不注册，而是注册一个空壳）：

```ts
{
  key,
  stateSchema: z.object({}),        // 空对象 schema：任何缓存行都能 seed 它（strip 模式，不丢弃不抛错）
  init: () => ({}),
  apply: state => state,            // 恒等
  wire: { viewSchema, view: () => FIXED_VALUE },   // 固定零值
  stateVersion: 1,
}
```

固定零值里**带上一条 gate 记录**，让客户端能画出「不支持」的提示：

```ts
{ ok: true, unsupported: { current: harnessVersion, minimum: BASELINE }, /* …各计数全 0… */ }
```

这样做的三个收益：

1. **共享 key 的注册表不会因为缺 key 而空转** —— 零值单元占住了 key
2. 界面显示**成对的零值卡片 + 一句「宿主过旧」**，而不是空白或崩溃
3. `apply: state => state` 是恒等 —— **连事件都没解析**，所以老宿主的日志形状差异完全碰不到

## 三、legacy 别名（pre-0.1.1）

很老的宿主注册表读的是顶层 `schema` + `view`，而不是 `stateSchema` + `wire`。
降级单元上**同时挂两套**：

```ts
return {
  key,
  stateSchema: fallbackStateSchema,
  init, apply,
  wire: { viewSchema, view },
  schema: wireSchema,      // ← pre-0.1.1 读这个
  view,                    // ← 同上
  stateVersion: 1,
}
```

这**只服务于支持矩阵之外**的宿主 —— 在那些宿主上，这个降级单元就是插件的全部行为。
多挂两个字段的成本是零，收益是「在最老的环境里也画出一张说明卡而不是白屏」。

## 四、顺序铁律：通道先 arm，门控后判

```ts
export function apply(ctx, config) {
  const coldReads = makeColdReadGate()          // ① 共享资源
  watchBalanceChannel(ctx)                      // ② 所有可选通道先 arm
  watchSkillCatalog(ctx)
  watchFleetChannel(ctx, coldReads)
  watchAttachmentChannel(ctx, coldReads)

  const harnessVersion = detectHarnessVersion(ctx)   // ③ 再探测 + 门控
  if (harnessVersion !== undefined && !meetsBaseline(harnessVersion)) { /* fallback */ return }

  watchDetailChannel(...)                       // ④ 门控之后才是「真单元」相关装配
  ctx.sessionProjections.register(createContextTimelineDefinition(...))
  watchPromptInjection(ctx, config)
}
```

为什么：**通道读的是运行时实证过的接口**（`connection` 存在与否当场就能验），
它们**在基线两侧都应该工作**。门控只该决定「注册哪些投影单元」，不该顺手关掉整条数据通道。
把门控放在最前面 return，会让一个老宿主连「余额查询」这种与投影无关的能力都拿不到。

## 五、特性探测：一个 schema 服务所有宿主

**同一份代码在版本不同的宿主上，字段修饰器可能不存在。** 例如配置字段的「在线可编辑」
修饰器 `.volatile()` 只在较新宿主上提供。

不要写 `if (version >= X) schema.volatile() else schema`（到处撒版本判断），
而是**探测修饰器本身**：

```ts
export function volatileField<S>(field: S): S {
  const volatile = (field as unknown as { volatile?: () => S }).volatile
  return typeof volatile === 'function' ? volatile.call(field) : field
}
```

这样 schema 是**一份**，宿主是新是老都能装载；新宿主得到在线可编辑，老宿主得到普通字段。
语义细节与「双轨配置」见配套 skill `dsh-settings-page`。

同一条「探测能力而不是探测版本」的规则，适用于所有修饰器/可选方法：
**能问「它是不是函数」就不要去比版本号** —— 版本号是你猜的，函数存在是事实。

---

## 常见偏差

| 偏差 | 后果 |
|---|---|
| 探测失败时兜一个默认版本号 | 门控用假数据做判断，可能在好宿主上关掉功能 |
| 探测里 `import` 了宿主包 | 依赖图被绑死，探测本身成了兼容负担 |
| 忘了 `isInside` 守卫 | 插件自身的 `node_modules` 被当成宿主，读出错误版本 |
| `isInside` 只查 `..` 前缀 | 跨盘符时 `relative()` 返回绝对路径 → 守卫失效 |
| 向上找清单不校验 `name` | 误读祖先目录的无关 `package.json` |
| 比较时不区分 rc/beta/alpha | `0.2.0-rc.2` 与 `0.2.0` 被当作相等 |
| 低于基线就整个 `return`（含通道） | 老宿主上连与投影无关的功能也没了 |
| 低于基线时「不注册」而不是「注册零值」 | 共享 key 空转；界面空白而非提示 |
| 降级单元的 `apply` 也去解析事件 | 老宿主的日志形状差异立刻炸 |
| 到处写版本号分支而不是探测函数 | 每个新宿主版本都要改一遍代码 |

## 落地检查清单

- [ ] 声明了 `dsh.compatibility.dshReleases`（声明 ≠ 校验，但市场要读）
- [ ] 探测不 import 任何宿主包（只解析清单）
- [ ] 探测有 `isInside` 守卫（含跨盘符情形），且自我根目录由自引用定位
- [ ] 有 home 锚点兜底（经 `dshHomePath`）；`@deepseek-ai/dsh` 只走 home 锚点
- [ ] 向上找清单时校验 `name`
- [ ] 任何失败返回 `undefined`，不抛、不兜默认版本
- [ ] 比较认发布通道（正式 > rc > beta > alpha）
- [ ] 解析失败 → 视为满足（fail open）
- [ ] 低于基线时注册**零值降级单元**，且 `apply` 恒等
- [ ] 零值里带 `unsupported: { current, minimum }` 供客户端出提示
- [ ] 降级单元挂了 pre-0.1.1 的 `schema` / `view` 别名
- [ ] 可选通道 arm 在门控 return **之前**
- [ ] 可选修饰器一律走**特性探测**，不写版本号分支
- [ ] 基线值写成常量并让文档/声明与它一致（三处不许漂移）

## 参考实现

| 用途 | 位置（`<dsh-context-checkout>`） |
|---|---|
| 双锚点探测 + isInside + 清单解析（**核心范例**） | `src/host/version.ts`（157 行，整篇可读） |
| 版本比较 + 基线常量 | `src/shared/version.ts` |
| 门控落点与 arm 顺序 | `src/host/index.ts`（`apply` 全程 34 行） |
| 零值降级单元 + legacy 别名 | `src/host/fallback.ts`（75 行） |
| 特性探测的修饰器包装 | `src/host/config.ts`（`volatileField`） |
| 该仓自己的支持矩阵文档写法 | `docs/compatibility.md` |

> 取材许可：结构与关键语义取自 `bowenliang123/dsh-context`（**Apache-2.0**）。
> 文中代码均为**重写后的骨架**，非整文件搬运。
> 该仓的基线是 `0.1.7-rc.2`（它自己支持的最老版本）—— **你的插件要声明自己的**。

骨架与逐段语义见
[references/version-probe.md](references/version-probe.md)、
[references/baseline-gate.md](references/baseline-gate.md)、
[references/support-matrix.md](references/support-matrix.md)。

配套 skill：可选服务缺席时的优雅降级与延迟注入见 `dsh-plugin-robust-mount`；
在线可编辑字段与双轨配置见 `dsh-settings-page`；投影单元的 `stateVersion` 升降级语义见
`dsh-session-projection`；宿主侧按需路由见 `dsh-plugin-fetch-route`。

总览与索引见 `dsh-plugin-dev-guide`。
