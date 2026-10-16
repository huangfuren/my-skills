# 客户端调用契约

宿主侧把数据端出来了，浏览器半这边要把它调对 —— 这一步的坑比宿主侧还多。

## 1. 路由常量必须在客户端重新声明

```ts
// 客户端不能 import 宿主模块：构建纯净门会直接失败，
// 而且就算绕过，两份值也可能漂移。
const ROUTE = '/api/my-plugin/detail'   // ← 与 host 侧的 ROUTE 常量一字不差
```

在两侧各写一份，用注释互指出处。这是**故意**的重复，不是待重构的坏味道。

## 2. 调用形态

```ts
const response = await fetch(ROUTE, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ sessionId }),
})
```

- 方法、header、body 编码三者必须与宿主侧 `requestBody: 'buffered'` 的约定一致
- **入参从宽到窄**：可选参数用条件展开而不是传 `undefined`
  ```ts
  body: JSON.stringify({
    ...(cwd === undefined ? {} : { cwd }),
    ...(sessionId === undefined ? {} : { sessionId }),
  }),
  ```
  宿主侧「逐字段类型校验」意味着一个 `undefined` 会被当成缺字段拒绝

## 3. 三层校验，一层都不能省

```ts
if (!response.ok) throw new Error(`my-plugin: HTTP ${response.status}`)   // ① 传输层
const body = asRecord(await response.json())
if (body === null || body.ok !== true) throw new Error('my-plugin: read failed')  // ② 业务信封
// ③ 载荷形状 —— 校验失败要整份拒绝，不许半采纳
const value = payloadOf(body.value)
if (value === null) throw new Error('my-plugin: malformed payload')
```

第 ③ 层的正确姿势是**「一个字段不合规就整份丢」**：

- 头字段（`rev`）缺失/NaN/负数 → 拒绝整个 payload，让调用方走「可重试」提示，
  **绝不部分合并**（合并出的半份数据比没有更危险）
- 可选子字段（比如一个附加的 head）不合规 → 只让那个字段消失，不拖垮整份

分层含义不同：头字段是**这个 payload 的坐标**，坐标不对就什么都别信；子字段是内容，
一个坏子项不该等于全部作废。

## 4. 竞态：代数（generation）+ 版本（revision）双游标

按需读天生有竞态：用户快速切会话、宿主在推送里刷新、前一次请求慢返回。
必须同时防三件事：

| 机制 | 防什么 |
|---|---|
| `generation` 自增计数 | **过期响应落地**：请求发出时记下代数，回来时代数变了就丢弃 |
| `acceptedRev` / `wantedRev` | **版本倒流**：只接受比已采纳版本更新的 payload（latest-wins） |
| `lastHeadRev` 下降检测 | **宿主重折叠**：head 的 rev 变小说明宿主重建了投影、revision 从 0 重新开始，此时必须接受「看起来更旧」的 payload |
| 单飞（`inFlight`） | 同一份数据的并发重复读；已有一发在飞就复用它 |
| 去抖（约 300ms） | 推送抖动导致的请求风暴 |

**「revision 变小 = 宿主重折叠」这一条最容易漏**：没有它，重折叠之后客户端会一直拒绝
新的（编号更小的）数据，表现为界面永久停在被删掉的那一代。

## 5. 失败处理：保留上一份好数据

```ts
interface Snap {
  detail: Detail | null      // 最后一次成功的数据，失败时不清空
  failed: boolean
  pending: boolean
}
```

- 读失败时**保留最后一份成功数据** + 置 `failed`：卡片不闪回 loading，用户看到的是
  「旧数据 + 一个错误提示」，比空白好
- 失败退避（连续失败次数递增间隔），避免对已死路由持续打请求
- **失败永不缓存**：重试必须真的重读（宿主侧的 `no-store` 也是为这个）

## 6. 页面关闭就停读

```ts
private parked = false   // 无视图持有此 store
```

- store 通常按 session 缓存在页面级 Map 里，生命周期比视图长
- 当没有视图持有它时 → **保持已缓存 payload（重开秒渲染），但不再 arm 任何读**
- 否则一个已关闭的面板会永远追着一个死路由

## 7. 接进 React

```ts
const snap = useSyncExternalStore(store.subscribe, store.getSnapshot)
```

- `getSnapshot` 必须返回**身份稳定**的对象：store 内部每次 transition 重建一次快照并缓存，
  不要在 `getSnapshot` 里现造对象（否则无限重渲染）
- 订阅集合用 `Set<() => void>`，`subscribe` 返回取消订阅函数

## 8. 排错对照

| 症状 | 先查 |
|---|---|
| 请求 404 | 路由没 arm（`ctx.inject` 的服务缺席）、或客户端常量与宿主不一致 |
| 请求 401/403 | 路径不在 `/api` 之下 |
| 一直 loading | 独立看 panel 的响应：`body.ok` 是否为 `true`、`value` 是否为 `null`（null = 宿主侧设计的空值，客户端应展示空态而非转圈） |
| 数据永远不刷新 | revision 倒流保护没做「重折叠」分支 |
| 切换会话串数据 | 少了 generation 检查；或 store 没按 sessionId 分键 |
| 偶发半份数据 | 形状校验在部分采纳而不是整份拒绝 |
