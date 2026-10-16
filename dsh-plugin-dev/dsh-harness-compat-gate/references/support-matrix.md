# 声明层：支持矩阵怎么写、放哪、和谁对齐

## 1. 三处声明，各管一件事（别指望它们互相替代）

```jsonc
{
  "engines": {
    "node": "^22.19.0 || >=24.0.0",
    "dsh": ">=0.1.7-rc.2 || >=0.2.0-rc.2"     // ← 写了但宿主不校验
  },
  "peerDependencies": {
    "@deepseek-ai/cordis": "^4.0.4",
    "@deepseek-ai/dsh-session": ">=0.1.7-rc.2",       // ← 宿主真正强校验的是这些
    "@deepseek-ai/schemastery": "^3.18.2",
    "react": "^18.3.1"
  },
  "dsh": {
    "compatibility": {
      "dshReleases": { "0.1.7-rc.2": "compatible", "0.2.0-rc.2": "compatible" }
    }
  }
}
```

| 字段 | 谁读它 | 效果 |
|---|---|---|
| `engines.dsh` | **没人**（宿主不校验） | 纯声明，给人看 |
| `peerDependencies` 里的 `@deepseek-ai/dsh*` | **宿主，启动 + 安装时强制** | 不满足则插件**装不上/不加载** |
| `dsh.compatibility.dshReleases` | 插件市场 / 兼容性阅读器 | 展示用，不影响运行 |

**宿主侧校验的真实规则**（`dsh ≥ 0.1.7`）：对插件的 `@deepseek-ai/dsh*` peer 区间做 semver 校验，
**`includePrerelease: true`** —— 也就是说 `>=0.1.7-rc.2` 会接受 `0.2.0-rc.2` 这类预发布版本。
不满足时可用豁免命令 `dsh plugin allow-version` 放行。

这里的实际结论：**你想拦「太老/太新」的宿主，唯一有强制力的地方是 peer 区间**。
把它写成宽松的 `>=<你的底线>`，再用运行时的基线门控（见 `baseline-gate.md`）做精细处理 ——
两道闸的分工是：

| 闸 | 性质 | 拦什么 |
|---|---|---|
| peer 区间（宿主执行） | 硬性、装不上 | 明显不兼容的宿主线 |
| 运行时门控（插件自执行） | 软性、降级 | **pre-0.1.7 的老宿主**（它们根本没有 peer 校验这道闸，照样会加载插件） |

最后一条是运行时门控存在的**真正理由**：不能假设宿主一定会拦。

## 2. 支持集怎么定

**「支持」= 声明出来的那个集合，其余一律走降级。** 不是「大概都能跑」。

```md
1. **Support exactly `0.1.7-rc.2` and `0.2.0-rc.2`** — both the V4 durable-log generation.
   The floor is `0.1.7-rc.2` because it is the first `0.1.7`-line release with a complete npm
   dependency closure; anything older gets the fallback composition with an upgrade prompt,
   never a fold.
```

写法上的三个要点：

1. **给的是一组精确版本，不是一个范围** —— 范围会让人以为「范围内都验过了」
2. **说清底线**，以及底线为什么在那儿（这里是「第一个依赖闭包完整的 0.1.7 线版本」）
3. **说清外面的人会得到什么**（降级 + 升级提示，不是折叠）

## 3. 四段式：Rule / Limitation / Check / Procedure

这套写法让「支持矩阵」既能读也能验。**粗体领头的那句是不变量本身**，后面跟证据。

| 段 | 写什么 | 例 |
|---|---|---|
| **Rule**（编号） | 必须成立的不变量 | 「每个能力都走**可选** seam —— 延迟 `ctx.inject`，绝不硬 `inject`」 |
| **Limitation** | **接受的**缺口，明说是缺口 | 「图片卸载场景下计数会偏大，直到压缩把它清掉」 |
| **Check** | 这条怎么被证明 | 「compat vitest 项目在各 baseline tag 上起真源、探 seam、断言退役 seam **不存在**」 |
| **Procedure** | 怎么执行一类任务 | 「加一个 baseline：在 `tests/baselines.ts` 加一条 + 两个 workflow 的 fetch 步骤加 tag」 |

配套的两条总纲（直接决定文档质量）：

> **Law.** 只记别的工件没承载的东西；代码、测试、git 历史已经说了的，删掉。
> 行动前先对着 dsh 源码核实 —— **源码优先于本文档**。少永远更好。

> **Grammar.** 证据放尾括号（本仓路径，或宿主树里的 `dsh:` 路径），或紧跟规则下方的表格。
> 只有当代码无法表达时才写理由（rationale）。

**「源码优先于文档」是这类文档能长期存活的关键**：文档明确承认自己会过期，并指定了
权威来源。没有这一条，读者会在文档与代码冲突时二选一猜，通常猜错。

## 4. 分组方式

按**子系统**分节，不按版本分节：

```md
## 1 · Supported set        支持哪些、底线在哪
## 2 · Admission            插件到底装不装得上（宿主侧 peer / 插件侧门控 / 特性探测）
## 3 · Fold                 会话日志 → 投影状态（形状 / 全量性）
## 4 · Metering parity      插件打印的数字要和宿主一致
## 5 · Client surface       浏览器半可以依赖什么（seam / 边界）
## 6 · Projection cache     折叠态怎么到达既有安装（stateVersion / 缓存位）
## 7 · Packaging            看起来是死依赖但其实不是
## 8 · Verification         上面每一条怎么被证明
```

版本差异**写在节内**（作为证据或 Limitation），不单独开「版本差异」一节 —— 否则同一件事
会在两处维护，必然漂移。

## 5. 基线与 seam 面的钉法

支持矩阵要能被**自动验证**，做法是把每条的 seam 面钉进测试基线：

```ts
// tests/baselines.ts —— 每个基线一条：tag、vendored cordis、各 seam face
{ tag: '0.2.0-rc.2', cordis: '<路径>', faces: { ledger: ..., sessionNav: ... } }
```

验证时：按 baseline tag 取出宿主**真源码** → 把**构建产物**装进那个 tag 的真实注册表 →
探测宿主与客户端两侧的 seam → **断言退役的 seam 确实不存在**（例如被某次重构删掉的
`sessions.open(id)`）。

比「读文档」强的地方在于：**它证明的是「退役的东西真的没了」**，而不只是「新的东西在」。

## 6. 你项目里的最小版本

不必照搬全套。一个自用插件的最小支持矩阵只要四行：

| 项 | 最小内容 |
|---|---|
| 支持集 | 精确列出跑得通的版本 + 底线 + 底线外的行为 |
| peer 区间 | `>=<底线>`，让宿主拦明显不兼容的 |
| 门控 | 探测 + 低于基线出零值降级（`baseline-gate.md`） |
| 复核命令 | 一条命令能打印出当前宿主的真实版本（见 `version-probe.md` §7） |

「源码优先于文档」和「只记别处没有的」这两条总纲，无论文档多短都该写上。
