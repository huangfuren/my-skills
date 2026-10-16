# 系统提示段注入（副作用能力）

> **先说性质**：这是「插件改写送给模型的系统提示词」的能力。做之前要清楚：它比注册一个
> 插槽重得多。所以本篇的全部设计都围绕两个词 —— **默认无副作用** 与 **可审计**。

## 1. 完整骨架（可直接改造）

```ts
import type { Context } from '@deepseek-ai/cordis'

/** 消费的 `ctx.systemPrompt` 面；特性探测，缺这个服务的组合退化为 no-op。 */
export interface SystemPromptFace {
  section(section: {
    name: string
    order: number
    text: string | ((context: unknown) => string)
    interpolate?: boolean
  }): () => void
  getSectionOrder(name: string): number
}

/** 固定净距：离宿主自己的 order 锚点足够远，落在所有已分配槽位之外。 */
const ORDER_CLEARANCE = 1000

export function watchPromptInjection(ctx: Context, config: Config): void {
  // 延迟注入：无论提示词注册表早于还是晚于本 entry 挂载都能生效；
  // 没有这个服务的组合让子 fiber 保持 pending，本 entry 退化为 no-op。
  ctx.inject(['systemPrompt'] as never, (inner: Context) => {
    const systemPrompt = (inner as { systemPrompt?: SystemPromptFace | null }).systemPrompt
    if (systemPrompt === null || systemPrompt === undefined
      || typeof systemPrompt.section !== 'function'
      || typeof systemPrompt.getSectionOrder !== 'function') return

    systemPrompt.section({
      name: 'my-plugin:prompt-prefix',
      // 排在所有已分配槽位之前，锚在宿主自己的 order 注册表上：
      // 宿主做一次集中重排序，前缀依然是第一个。
      order: systemPrompt.getSectionOrder('HARNESS_IDENTITY') - ORDER_CLEARANCE,
      text: sectionText(liveText(config.promptPrefix)),
      // 字面文本：用户的 `{{...}}` 绝不能被严格变量插值解析到。
      interpolate: false,
    })
    systemPrompt.section({
      name: 'my-plugin:prompt-suffix',
      order: systemPrompt.getSectionOrder('DEPLOYMENT_PERSONA_SUFFIX') + ORDER_CLEARANCE,
      text: sectionText(liveText(config.promptSuffix)),
      interpolate: false,
    })
  })
}
```

## 2. 三个辅助函数（各自解决一个问题）

### 2.1 `liveText` —— 让偏好编辑不用重挂载

```ts
/** 一个配置字段背后的活文本：volatile 标记的字段解析成 `{ get }` 引用，
 *  加载器在偏好编辑时就地改写它；volatile seam 之下，值就是普通存储字符串。 */
function liveText(value: unknown): () => string {
  if (value !== null && typeof value === 'object' && typeof (value as { get?: unknown }).get === 'function') {
    const get = (value as { get: () => unknown }).get
    return () => {
      const text = get()
      return typeof text === 'string' ? text : ''
    }
  }
  const text = typeof value === 'string' ? value : ''
  return () => text
}
```

- 在线可编辑字段（volatile）在运行时是**一个带 `get()` 的引用对象**，不是字符串
- 探测它、返回 thunk，**文本就变成活的**：用户改偏好 → 下一个模型步骤生效 → **不重挂载 entry**
- 老宿主上它就是普通字符串，thunk 返回常量 —— 一份代码两种宿主都对

`volatile` 与双轨配置的完整语义见配套 skill `dsh-settings-page`。

### 2.2 `sectionText` —— 空 = 关闭

```ts
/** 段文本提供者：纯空白即视为禁用（宿主的 renderPrompt 会丢掉空段），其余文本逐字节保留。 */
function sectionText(read: () => string): (context: unknown) => string {
  return () => {
    const text = read()
    return text.trim().length === 0 ? '' : text
  }
}
```

**这是「默认无副作用」的落点**：默认值为空串 → `trim()` 后为空 → 返回空 → 宿主丢弃该段。
于是**什么都没装的时候，提示词与没有这个插件时逐字节相同**。

用 `trim()` 而不是 `=== ''`：用户把设置清空后留下的一串空格，也应该被当作「关闭」。

### 2.3 order 锚点

```ts
order: systemPrompt.getSectionOrder('HARNESS_IDENTITY') - ORDER_CLEARANCE
```

- **绝不要写死数字** —— 宿主自己的 section order 会变，写死必然漂移
- `± 1000` 是「离得足够远」：落在所有已分配槽位之外，同时不会溢出/退化为负值区间冲突
- 前缀锚在第一个宿主段之前，后缀锚在最后一个之后；两者用的锚点名要选**宿主一定注册了的**

## 3. 必须明示的连带效果

宿主**按步骤装配提示词**，并把渲染结果投影进会话日志。由此：

| 效果 | 含义 |
|---|---|
| 每个新会话从第一轮就带该文本 | 不是「下次重启生效」，是**立即** |
| 编辑会改写**已打开会话**的有效提示词 | 通过宿主自己的投影，无需重启，但你的修改会作用于正在进行的工作 |
| 文本在会话日志里可见 | **这是可审计性的基础** —— 出问题能回查实际生效的内容 |

**结论**：默认值必须为空，且要告知使用者「填了字会作用于所有会话（含已打开的）」。

## 4. 一个必须知道的限制

> **`complete` 段会顶掉一切。** 某个部署如果注册了 `complete` 类型的系统提示段，
> 宿主**只保留那一段**（注册表设计如此）—— 此时你注册的前缀/后缀段会被丢弃。

所以：**不要依赖前缀/后缀一定生效**。它是一项增强，不是契约。
真正关键的行为不要放在提示词注入里。

## 5. 与其他「副作用能力」的共通规则

任何改写宿主行为的注册（提示段、工具、钩子），都照这套走：

| 规则 | 说明 |
|---|---|
| **默认空 / 关闭** | 装上插件不改变任何行为；只有用户显式配置才生效 |
| **特性探测而非版本判断** | `typeof fn === 'function'`；缺面就 no-op |
| **锚定而非写死** | 顺序、优先级都从宿主自己的注册表推导 |
| **不做隐式解析** | `interpolate: false` 这类「关掉魔法」的开关要主动关 |
| **可审计** | 效果要能在会话日志/设置页里被看到 |
| **在文档里明说** | 这是一项会改动模型输入的能力，不是普通 UI |

## 6. 排错对照

| 症状 | 先查 |
|---|---|
| 填了没效果 | 宿主是否注册了 `complete` 段（见 §4）；或 `getSectionOrder` 的锚点名不存在 |
| 提示词被莫名加了内容 | 默认值是否为**空串**；`sectionText` 是否做了 trim |
| 改了设置要重启才生效 | 文本是不是直接取了字符串而不是 `liveText()` 的活引用 |
| 用户的 `{{...}}` 被替换掉了 | 漏了 `interpolate: false` |
| 段的位置跑偏 | `order` 写死了数字，或锚点段在宿主里不存在 |
