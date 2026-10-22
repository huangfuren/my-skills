# 运行时契约：接口、可选能力、会话隔离

循环体不直接暴露给产品层，中间隔一层接口。这篇讲接口怎么写、哪些能力该标成可选、以及多标签并行时怎么防止事件串轮。

## 一、为什么必须隔一层

不隔层的写法是把循环写成一个大函数，产品层直接调它。问题是：

| 问题 | 表现 |
|---|---|
| 换实现要改调用方 | 从 A 框架换到 B 框架，产品层跟着改 |
| 无法为测试替换 | 单测只能跑真模型，或干脆不写 |
| 生命周期散落 | 停止、清理、换绑各写一遍，行为不一致 |

隔一层接口之后，产品层只依赖契约，实现可替换，测试可以塞一个假实现。

## 二、契约的最低内容

```ts
interface AgentRuntime {
  /** 启动新一轮：同步点火，发起级错误同步抛，执行期错误走事件流 */
  startTask(
    tabId: string,
    task: string,
    maxSteps: number,
    binding: Bridge | null,
    callbacks: Callbacks,
    options?: StartOptions
  ): Promise<void>

  /** 续跑：重置预算基准，从上一轮收尾处继续 */
  continueTask(tabId: string, additionalSteps: number, options?: ContinueOptions): Promise<void>

  /** 停止：取消在途请求，并禁止后续命令下发 */
  stop(tabId: string): void

  removeTab(tabId: string): void
  isRunning(tabId: string): boolean
  updateCallbacks(tabId: string, callbacks: Callbacks): void

  updateAllowWrite?(tabId: string, allowWrite: boolean): void
  updateConfig?(config: Config): void
}
```

四个写法上的决定：

**1. 逐 tab 隔离，不是全局单例**

接口每个方法都带 `tabId`。这决定了「同一时刻能跑几个循环」是可扩展的，而不是写死成一个。

**2. 同步点火语义要写明**

`startTask` 返回 `Promise<void>`，但它的语义是「点火完成」，不是「任务完成」。这个区分必须写在注释里，否则调用方一定会 `await` 之后以为任务结束了。

**3. 执行期错误走回调，不走返回**

错误分两类：发起级（参数非法、绑定无效）同步抛；执行期（模型失败、连接断开）通过回调上报。混在一起会造成「有时要 try/catch，有时要听事件」的混乱。

**4. 停止后禁止复活**

接口注释里应当明确：`stop()` 之后，已中止的轮次不允许被后续事件恢复。实现上用 `stopped` 标志或等价机制保证。

## 三、可选能力：用 `?` 而不是空函数

```ts
updateAllowWrite?(tabId: string, allowWrite: boolean): void
updateConfig?(config: Config): void
```

为什么不用「所有实现都实现，不支持的写空函数」？

因为**空函数会让调用方产生错误的安全感**。

设想 `updateAllowWrite(tabId, false)` 用于运行中把权限降为只读。如果实现是空函数，调用方以为权限已经降了，实际上模型下一步照样能写。这是一个**静默的安全失效**，比崩溃严重得多。

用可选方法后，调用方必须写：

```ts
if (runtime.updateAllowWrite) runtime.updateAllowWrite(tabId, false)
else /* 明确知道该实现不支持运行中降权，走停机或提示 */
```

分支是显式的，失效可被发现。

**判定哪些能力该标可选**：无法在所有实现上等价完成的。典型是「运行中热更新」——有的实现能在下一步生效，有的必须重启轮次，后者的正确做法是不实现，而不是假装实现。

## 四、会话隔离：用可升级的盒子，不用布尔标记

多个标签并行时，会出现一类时序问题：

> 上一轮被替换掉的旧会话，它的回调在新一轮里迟到了，被误当成当前轮的结果。

后果很隐蔽：**上一步的输出被当作这一步的成功依据**。

解法是给会话一个「归属盒」：

```ts
interface SessionBox {
  allowedUid: number | null   // 当前轮允许的 uid
}

// 合法续用时，显式升级
if (legitReuse) box.allowedUid = turn.uid

// 事件到达时校验
if (box.allowedUid !== event.uid) return   // 丢弃陈旧事件
```

关键在于**盒子是可升级的，而标记是二值的**：

| 做法 | 问题 |
|---|---|
| `isStale: boolean` | 一旦置真就永久失效，续用时无法恢复 |
| `allowedUid: number` | 只接受当前轮，续用时升级即可 |

「隔离」和「仍在服役」是两种状态，布尔标记表达不了。

### 与终端锁的配合

如果循环持有某个消费端（终端、连接、会话）的独占权，隔离盒要和锁一起用：

- 锁决定**谁现在能发命令**；
- 盒子决定**谁的回调算数**。

只有锁没有盒子：能防并发写，防不住陈旧回调。
只有盒子没有锁：能防陈旧事件，防不住两个人同时写。

## 五、状态上报的形状

回调里至少要能表达三件不同的事，不要混成一个 `onUpdate`：

| 回调 | 表达 | 频率 |
|---|---|---|
| `emitMessage` | 中间过程（思考、工具调用、输出片段） | 高，流式 |
| `emitStateChange` | 循环状态机（运行 / 等待 / 收尾） | 低，变化时 |
| `onStepComplete` | 一步结束的结构化结果（步骤 + 结论 + 终态） | 每步一次 |

分开的理由：界面对三者的处理完全不同——消息是追加，状态是替换，步骤是落盘。混成一个回调，前端必须自己猜类型。

`onStepComplete` 里还要带一个容易漏的字段：

```ts
turnCompleted?: boolean   // 对话轮次已结束，但不代表任务成功
```

**「这一轮说完了」和「任务完成了」是两件事。** 没有这个字段，前端只能从终态推断，而终态里 `COMPLETED` 与「说完了」在用户视角容易混淆。

## 六、检查表

- [ ] 循环体与产品层之间隔了接口
- [ ] 每个方法带 `tabId`，不做全局单例
- [ ] 点火语义与完成语义在注释里区分清楚
- [ ] 发起级错误同步抛，执行期错误走回调
- [ ] `stop()` 后已中止轮次不可复活
- [ ] 无法等价实现的能力标 `?`，不用空函数
- [ ] 会话隔离用可升级的 uid 盒，不用布尔标记
- [ ] 独占权需要「锁 + 盒子」两层
- [ ] 消息、状态、步骤三类上报分开
- [ ] 有「轮次结束 ≠ 任务成功」的显式字段
