---
name: dsh-agent-loop-discipline
description: >-
  Use when a DSH plugin owns its own agent loop — when the model drives tools that touch
  real machines, and the plugin must decide when a round ends, when a single step counts as
  done, how much budget each dimension gets, and what to report when the outcome is unknown.
  Covers four named stop reasons with a fixed priority order, the deliberately narrow
  definition of acceptable failure, three separate budgets (steps, reads, output size), the
  single shared finish path, the runtime contract with optional capabilities, and the
  spec-numbered comment convention that keeps behaviour traceable to requirements.
license: MIT
compatibility: >-
  Loop discipline abstracted from guhanfei-ai/zterm (MIT), verified against its
  src/main/services/agentRuntime.ts, agentCompletionPolicy.ts, agentStepBudget.ts and the
  finishTurn path of piAgentRuntime.ts. Code here is a rewritten skeleton, not a copy.
---

# 循环纪律：终止、预算、收尾

插件自己跑多步循环时，最难的不是让 AI 做事，而是**判断它到底做完了没有**。

判断错了，用户看到的是「AI 说已完成」，而机器上什么都没变。

## 这篇覆盖什么

宿主已经提供了对话与工具调用。但如果插件自己起一个多步执行循环（典型场景：让 AI 连着跑几条命令排障），就等于接管了四件事：

| 接管的事 | 出错的后果 |
|---|---|
| 什么时候停 | 无限试错，烧钱且拖时间 |
| 算不算成功 | 报「完成」，实际未生效 |
| 试几次 | 一个简单任务耗掉整轮预算 |
| 结果不明怎么报 | 未知状态被当成成功，后续判断全错 |

四件事没有明确约定，循环就是不可审计的。这篇给的是**可以逐条检查的约定**。

## 第一原则：终止必有名

终态不能只有「结束」和「出错」两种。至少四个：

| 终态 | 含义 | 对用户的话术 |
|---|---|---|
| `COMPLETED` | 目标已达成，且**有验证证据** | 「已完成，依据是……」 |
| `ROUND_LIMIT` | 步数用尽，**未达成** | 「未完成，卡在第 N 步」 |
| `USER_INTERRUPT` | 人主动停止 | 「已按你的要求停止」 |
| `ERROR` | 执行期错误，无法继续 | 「出错停止，原因是……」 |

外加一个空态（尚未结束）。

关键区别在 `COMPLETED` 与 `ROUND_LIMIT`：**步数用尽绝对不能映射成完成**。这是最常见的一种错误，因为循环写起来很自然是 `for (step < max)` 结束后就返回成功。

## 三条优先级规则

这三条决定「同时命中多个终态时，报哪一个」。顺序不能换。

**1. 未知优先于资源耗尽**

> 结果不明的严重性高于预算用尽。

如果最后一步的执行结果没拿到（超时、连接断开、没有退出码），而步数恰好也用完了，必须报「结果不明」，不能报「轮次上限」。因为前者需要人去核查，后者只是没做完——**用人去核查一个其实没事的机器，代价远小于漏掉一个可能已出事的机器**。

**2. 完成不可伪造**

> 预算耗尽、被截断、被中断，都不许映射成完成。

「完成」只能由验证证据产生，不能由循环正常退出产生。

**3. 收尾单一路径**

> 正常路径与异常路径共用同一段收尾代码。

两套收尾代码一定会漂移：改了一边忘了另一边，于是异常退出时的上报格式和正常退出不一致。收尾逻辑集中到一个函数，两条路径都调它。

## 什么算失败：窄判定

判定要窄，不能宽。以「命令不存在」为例：这是一种**可以接受的调查结果**，但只在下述四条同时成立时才接受：

| 约束 | 理由 |
|---|---|
| 当前是只读模式 | 写操作失败永远是失败 |
| 退出码恰为 127 | 只认这一个码，不问其他非零 |
| 该步是本轮最后一步 | 中间步骤的 127 说明方向错了 |
| 输出里确实是「命令未找到」 | 防 127 被别的原因复用 |
| 之前至少有过一次成功 | 防整轮从头到尾没跑通过 |

四条叠加的结果是：**极少数情况被接受为「环境缺件」，其余全部算失败**。

反过来做的典型错误是「非零退出但输出看着正常就算过」——这会把半成功、部分写入、脚本中途退出全部误判为成功。

## 三层预算，分开计

| 维度 | 典型值 | 耗尽后 |
|---|---|---|
| 步数 | 默认 100，上限 1000 | 终态 `ROUND_LIMIT` |
| 读次数 | 与步数独立 | 单独标记，不并入步数 |
| 输出长度 | 按步截断 | 打「已截断」标记，保留行号 |

分层的理由：**「AI 试太多次」和「AI 读太多」是两种不同的失控**。前者是方向错，后者是信息过载。合并成一个总预算，就分不清该收紧哪一个。

步数预算应当是**每轮读取配置**，而不是进程启动时读一次——用户中途调小要能立刻生效。

## 契约与实现分离

循环体不直接暴露给产品层，中间隔一个接口：

```ts
interface AgentRuntime {
  startTask(chatTabId, task, maxSteps, bridge, callbacks, options?): Promise<void>
  continueTask(chatTabId, additionalSteps, options?): Promise<void>
  stop(chatTabId): void
  removeTab(chatTabId): void
  // 可选能力：不支持的实现可以不实现
  updateAllowWrite?(chatTabId, allowWrite: boolean): void
  updateConfig?(config): void
}

function createAgentRuntime(config): AgentRuntime {
  return new PiAgentRuntime(config)   // 换实现只改这一行
}
```

两个要点：

- **可选方法用 `?` 标记**，而不是让每个实现都写空函数。空函数会让调用方以为「已经生效」，实际什么都没发生。
- **契约里写明同步与异步语义**：点火是同步的（发起级错误同步抛），执行期错误走事件流。这两条不写清楚，调用方一定会写错重试逻辑。

## 规格可追溯

代码注释锚定到编号化的需求条目：

```ts
// 会话策略(R05): reuse = 追问沿用上下文; rebuild = 新任务重建会话
// 预算耗尽(R06): ROUND_LIMIT → stepLimitReached，不被 COMPLETED 覆盖
// 共享收尾(S02): 正常与异常路径共用
```

好处很直接：**改代码时知道自己在改哪一条需求**，而不是「这段为什么要这么写」只能靠猜。没有编号体系时，至少要在注释里写清楚「这个行为是为了解决哪个故障」，否则半年后没人敢动。

## 反模式清单

| 反模式 | 为什么会犯 | 后果 |
|---|---|---|
| 只有 `stop` / `error` 两态 | 接口简单 | 分不清「做完了」和「没做完」 |
| 循环自然结束即返回成功 | 代码最顺 | 步数耗尽的半成品被当完成 |
| 正常与异常两套收尾 | 后加的异常处理 | 上报格式不一致，前端解析出错 |
| 「看着正常」就算过 | 想减少误报 | 半成功、部分写入被误判成功 |
| 单一总预算 | 省事 | 分不清方向错还是读太多 |
| 结果不明直接重试 | 想快点出结果 | 在状态未知的机器上重复执行写操作 |

## 落地检查表

写循环前逐条确认，全部为「是」才算合格：

- [ ] 终态有独立的四个名字，且每个都有对应话术
- [ ] 预算耗尽**不会**产生「完成」
- [ ] 结果不明**优先于**预算耗尽上报
- [ ] 正常与异常共用同一个收尾函数
- [ ] 「可接受的失败」有明确的窄条件，不是「非零但输出正常」
- [ ] 步数 / 读次数 / 输出长度分开设限
- [ ] 循环体与产品层之间隔了接口，换实现只改一行
- [ ] 可选能力用可选方法标记，不用空函数占位

## 取材与边界

规则来自对 `guhanfei-ai/zterm` 的源码抽象，该仓为 **MIT**。文中代码是重写骨架，非整文件搬运。

需要说清楚的是：它证明了**「知道该怎么管」**，没有证明**「管得好」**——该仓 README 自述端到端验收需自行完成，没有评测集或轨迹回放。所以这篇给的是**纪律**，不是**效果承诺**。效果要靠你自己的任务集去验。

终止态判定与优先级细节见
[references/termination-semantics.md](references/termination-semantics.md)、
三层预算与截断策略见
[references/budget-and-context.md](references/budget-and-context.md)、
运行时契约与可选能力见
[references/runtime-contract.md](references/runtime-contract.md)。

配套 skill：可选依赖缺席时的降级与单活挂载见 `dsh-plugin-robust-mount`；
跨宿主版本的能力探测与门控见 `dsh-harness-compat-gate`；
把执行记录推给界面的值流写法见 `dsh-session-projection`。

总览与索引见 `dsh-plugin-dev-guide`。
