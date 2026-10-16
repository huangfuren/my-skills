# 注入语义：硬 inject、延迟 inject、即时 get

## 1. 三者对照（完整版）

| 维度 | 顶层 `inject = [...]` | `ctx.inject([...], cb)` | `ctx.get(name)` |
|---|---|---|---|
| 声明位置 | 模块导出（宿主半）/ `module.exports.inject`（浏览器半） | `apply` 内部 | 任意位置 |
| 语义 | **硬闸门** | 延迟注入 + 生命周期绑定 | 即时读取 |
| 服务已存在 | 立即可用 | cb 立即执行 | 返回该服务 |
| 服务**后到** | —— | **cb 那时执行** | 返回 `undefined`，**永不重试** |
| 服务缺席 | 插件 fiber 停在 INACTIVE，**无报错** | cb 不执行，插件其余照常 | 返回 `undefined` |
| 服务卸载 | 插件卸载 | cb 的返回值被当 disposer 调用 | 无感知（可能拿到已失效的引用） |
| 返回值 | —— | **被当作 disposer** | 服务对象或 `undefined` |

**一句话记法**：

> 顶层 inject 说「没有它我就不活」；`ctx.inject` 说「它来了我就做，走了我就收」；
> `ctx.get` 说「现在给我，没有就算了」。

## 2. 顶层 inject：只写确定存在的

```ts
// 宿主半（ESM）
export const inject = ['sessionProjections']

// 浏览器半（CJS）
module.exports = { name: 'my-plugin', inject: ['slots', 'locale'], apply }
```

`sessionProjections` / `slots` / `locale` 属于宿主内核，任何支持的部署上都在。

**写错的代价**：`inject: ['sesssionProjections']`（拼错）→ fiber 停在 INACTIVE →
**插件完全不加载，控制台也没有错误**。这是本项目里最难定位的一类故障，
所以新增顶层 inject 项时，先在已装宿主里确认这个服务名真的存在。

> 具体的服务名清单以**本机已装宿主**为准：读
> `…\profiles\desktop\node_modules\@deepseek-ai\` 与宿主包的 `lib/types/*.d.ts`，
> 不要凭记忆写。

## 3. `ctx.inject`：可选依赖的唯一正确姿势

```ts
ctx.inject(['connection'], (c) => {
  const connection = c.get('connection') as ConnectionHostFace | undefined
  if (connection === undefined) return
  /* …注册… */
  return () => { /* 卸载 */ }        // ← 这个返回值就是 disposer
})
```

三个必须知道的点：

1. **cb 的参数 `c` 是子 fiber**，它身上只能看到你声明的那些服务（外加父级服务）。
   在 cb 内部用 `c.get(name)` 读兄弟服务，用**外层 `ctx`** 读全局其他服务
2. **cb 的返回值被当作 disposer**：在服务卸载时调用。所以「注册 → 返回注销函数」
   是这套 API 的天然形态
3. **服务后到也能生效**：这是它区别于 `ctx.get` 的核心价值

## 4. 多服务依赖：一个数组，不要拆开

```ts
// ✅ 一次声明全部依赖：任一缺席就整段不 arm
ctx.inject(['connection', 'sessions'], (c) => { /* … */ })

// ❌ 拆成多次：先后到达时可能出现「路由已注册但数据源还没到」的半残状态
ctx.inject(['connection'], (c) => { /* 注册路由 */ })
ctx.inject(['sessions'], (c) => { /* 绑定数据源 */ })
```

判据：**这些依赖是「全都到齐才能真正工作」还是「各自独立」**。
真前者的（路由需要连接 + 会话），放一个数组；互相独立的，才拆开。

## 5. 形状校验：变量存在 ≠ 类型正确

```ts
// 三层都要问：对象在不在 → 是不是函数 → 绑定拥有者
const sessions = c.get('sessions') as SessionsHostFace | undefined
const getSession = typeof sessions?.get === 'function' ? sessions.get.bind(sessions) : undefined
if (getSession === undefined) return
```

- 宿主面要按**结构**声明（`interface X { method?(): T }`），字段全可选。
  这既是类型安全，也是**文档**：读代码的人立刻知道哪些是可选的
- 常见的校验形态：
  ```ts
  if (svc === null || svc === undefined || typeof svc.section !== 'function') return
  ```
- **绑定拥有者对象**，不是外围变量：
  ```ts
  query.observeSession.bind(query)     // ✅
  query.observeSession.bind(ctx)       // ❌ this 错
  ```

## 6. disposer 的三种来源

| 来源 | 形态 | 用于 |
|---|---|---|
| `ctx.inject` 的 cb 返回值 | `return () => {…}` | 「服务在上时存在」的一切 |
| `c.effect(fn, label)` | `fn` 返回 disposer | 自有资源、注册动作、绑到 fiber 的清理 |
| `ctx.slots.inject(name, cb)` | **返回值就是注册的 disposer** | 插槽注册 |
| `forms.whileServed([ns], cb)` | 服务「服务期间」钩子 | 只在某服务在位时有意义的注册 |

组合起来的惯用法（客户端注册设置卡片）：

```ts
c.effect(() => forms.whileServed([NS], () =>
  c.slots.inject('plugins.bundle.config', () =>
    c.slots.register({ name: 'plugins.bundle.config', key: NS, locale: NS, inject: cardFace }, render)) as () => void
), 'my-plugin: plugins-page card')
```

读法：**effect 兜底 → 服务在位时 → 注册插槽 → 返回 disposer**。

## 7. 生命周期速查

```
插件 apply()
  │
  ├─ 顶层 inject 全部满足？
  │     否 → fiber INACTIVE（静默）── 插件不工作
  │     是 ↓
  ├─ ctx.inject([A,B], cb)
  │     ├─ 现在就齐 → cb 立刻跑
  │     └─ 之后才齐 → 服务到达时 cb 跑
  │            └─ 返回的 disposer 在服务卸载时调用
  └─ c.effect(...)  → fiber 卸载时调用其 disposer
```

## 8. 排错对照

| 症状 | 先查 |
|---|---|
| 插件毫无动静、也没有报错 | 顶层 `inject` 的**服务名拼写** |
| 首屏正常，稍后功能消失 | 某个服务卸载了；检查 disposer 是否被误用 |
| 某个可选能力在部分部署上缺失 | 是不是用 `ctx.get` 而不是 `ctx.inject` 读的 |
| 偶发「半残」状态（路由在、数据源不在） | 多服务依赖被拆成了多次 `ctx.inject` |
| 方法调用报 `this` 相关错误 | 取方法时忘了 `.bind(拥有者)` |
| 卸载后仍在跑 | 注册没包进 `c.effect`，或注册与注销分开写了 |
