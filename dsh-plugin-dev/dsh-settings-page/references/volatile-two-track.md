# volatile 双轨配置：逐字段语义与迁移

## 1. 宿主侧的策略（先理解它，才知道字段怎么标）

宿主从插件的 `Config` schema（schemastery，Standard Schema 面）生成 Plugins 页的在线表单：

- **命名空间 = entry id**
- **只有 `.volatile()` 标记的字段会被「服务」且可编辑**
- 非 volatile 字段的编辑走另一条路：**重挂载 entry**

于是同一个 schema 里两类字段的编辑语义天然分叉：

| | 绑定字段（不标 volatile） | 偏好字段（标 `.volatile()`） |
|---|---|---|
| 表单里能不能改 | 能，但改完**重挂载 entry** | 能，**就地提交** |
| 生效方式 | `apply()` 重新执行，新值进闭包 | 无需重挂载；消费方按活引用读到新值 |
| 适合谁 | 影响**装配**的：折叠边界、扫描范围、采集端点、并发上限 | 影响**渲染/每次请求**的：显示位置、排序方式、趋势模式、文案前缀 |
| 代价 | 重挂载（有一次性成本，缓存清空） | 无重挂载，但**要求消费方按活引用读** |

**判定标准（唯一一条）**：

> 这个值是否在 `apply()` 期间被读进闭包、注册项、或构造函数里？

- **是** → 绑定字段。标了 volatile 会让「编辑」不再重挂载，而代码早已读过旧值 → 表现为设置无效
- **否**（只在 `view()` / 渲染 / 每请求时读） → 偏好字段。不标 volatile 会导致「改不动」

## 2. 完整 schema 骨架

```ts
import z from '@deepseek-ai/schemastery'

/** 特性探测：`.volatile()` 存在就用，不存在原样返回 —— 一份 schema 服务所有宿主。 */
export function volatileField<S extends z>(field: S): S {
  const volatile = (field as unknown as { volatile?: () => S }).volatile
  return typeof volatile === 'function' ? volatile.call(field) : field
}

function count(defaultValue: number) {
  return z.number().min(1).step(1).default(defaultValue)
}

export const Config = z.object({
  // ── 绑定字段：不标 volatile，改了重挂载 entry ──
  maxRequestSteps: count(1500),
  maxKeptTurns: count(300),
  maxEvents: count(400),
  maxNodes: count(2000),

  // ── 偏好字段：volatile + loose，就地生效、陈旧值不炸 ──
  defaultPlacement: volatileField(z.union(['all', 'tab', 'sidebar']).default('all').loose()),
  defaultGranularity: volatileField(z.union(['step', 'turn']).default('step').loose()),
  defaultTrendMode: volatileField(z.union(['total', 'delta']).default('total').loose()),
  defaultToolSort: volatileField(z.union(['size', 'count', 'name']).default('count').loose()),
  insightsEntry: volatileField(z.union(['show', 'hide']).default('show').loose()),
  promptPrefix: volatileField(z.string().default('').loose()),
})
```

**两个修饰器的顺序**：`.default(…).loose()` —— 先给默认值再标 loose。
`volatileField(...)` 包在最外层（它要访问字段对象本身的 `.volatile` 方法）。

**每个偏好字段都要给 `.default()`**：偏好字段参与表单渲染，没有默认值就没有初始态。

## 3. `.loose()` 解决的那个具体问题

场景：你的 v0.3 把 `defaultPlacement` 的枚举从 `['all','tab']` 改成了 `['all','tab','sidebar']`，
但用户存储里可能留着旧值 —— **或者反过来，v0.2 的存储里有一个 v0.3 已删除的值**。

没有 `.loose()` 时：schema 校验失败 → **entry 装载失败** → 插件起不来，用户不明所以。

有了 `.loose()`：不合规的值**退化为默认**，entry 正常装载。

**给所有「枚举 / 字符串 / 会被人工编辑」的字段都加 `.loose()`**：

```ts
promptPrefix: volatileField(z.string().default('').loose()),   // 非字符串值也退化为 ''
```

成本为零，收益是「升级永不因配置炸掉」。

## 4. 消费侧：活引用

**标记了 volatile 的字段，从 config 里解析出来的是一个带 `get()` 的引用对象**，
不是普通的字符串/数字。原因：加载器在偏好编辑时**就地改写这个引用**，从而避免重挂载。

```ts
/** 一个配置字段背后的活文本。volatile 字段 → `{ get }` 引用（加载器就地改写）；
 *  volatile seam 之下 → 普通存储字符串。 */
function liveText(value: unknown): () => string {
  if (value !== null && typeof value === 'object' && typeof (value as { get?: unknown }).get === 'function') {
    const get = (value as { get: () => unknown }).get
    return () => { const t = get(); return typeof t === 'string' ? t : '' }
  }
  const text = typeof value === 'string' ? value : ''
  return () => text
}
```

要点：

1. **探测 `get` 是不是函数**，不要假设「volatile 字段一定是引用」—— 老宿主上它就是普通值
2. **返回 thunk**，在消费点（`view()` / 每次请求 / 渲染）才读
3. **不要在 `apply()` 时 `get()` 一次存起来** —— 那就等于把它变回了绑定字段

同型消费（非字符串偏好值）：

```ts
const mode = liveValue(config.defaultTrendMode, 'total')   // 同样返回 thunk
```

## 5. 三类字段的对照实例

| 字段 | 类型 | 为什么 |
|---|---|---|
| `maxEvents`（折叠时保留的事件上限） | 绑定 | 折叠函数在 `apply()` 时拿到它并进闭包 |
| `defaultPlacement`（默认显示在哪） | 偏好 | 每次渲染时决定 |
| `promptPrefix`（提示前缀） | 偏好 | 每个模型步骤组装提示词时读 |
| 采集端点 / 凭据 ref | 绑定 | 服务的构造需要它 |
| 并发上限 / 超时 | 视情况 | 若进的是长期存在的对象 → 绑定；若每次请求都新建 → 偏好 |

最后一行的判据仍然是那一句：**「apply 时读了吗」**，而不是「它看起来像不像配置」。

## 6. 迁移场景清单

| 场景 | 该做什么 | 不该做什么 |
|---|---|---|
| 枚举删掉一个值 | 保留 `.loose()`（已有则无需改动） | 什么都不做 —— 没 loose 会炸 |
| 绑定字段改成偏好字段 | ① 标 `.volatile()` ② 消费点从「apply 时读」改成「thunk 读」 | 只标 volatile，不改消费点 |
| 偏好字段改成绑定字段 | ① 去掉 `.volatile()` ② 消费点改回 apply 时读 | 只去 volatile（宿主会重挂载，但代码还在 thunk 读，值不会变） |
| 新增字段 | 给默认值；按双轨判定要不要 volatile | 忘记默认值（表单无初始态） |
| 宿主可能很老 | `volatileField()` 包裹 | 写版本号分支 |

## 7. 自测点

- [ ] 在设置页改**偏好字段** → 界面立刻变化，且**没有**重挂载（行为无闪烁）
- [ ] 在设置页改**绑定字段** → entry 重挂载，新值生效（可能需要重新打开面板）
- [ ] 手工把存储里的枚举值改成不存在的值 → 插件仍能装载，该字段回落默认
- [ ] 把 `.volatile()` 从某个字段上临时去掉 → 设置页里它应该变得不可编辑（验证门禁确实按 volatile 走）
- [ ] 老宿主（宿主无 `.volatile()`）上装载 → 不报错，字段退化为普通字段
