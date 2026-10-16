---
name: dsh-plugin-dev-guide
description: >-
  Entry point for DSH plugin development. Use when starting a new DSH plugin, when you need
  to know which skill covers a given plugin task (mount a control, add a settings page, stream
  session data, serve host-side data on demand, survive a harness upgrade, stop a double mount),
  or when a plugin silently does nothing. Maps every development task to the skill that owns it,
  gives the reading order for a plugin built from scratch, pins the authoritative sources of
  truth, and collects the cross-cutting anti-patterns.
license: MIT
compatibility: >-
  Index over the DSH plugin-development skill set in this directory. Facts live in the
  individual skills; this page only routes. Verified against the installed dsh 0.2.0-rc.2
  runtime and the 0.1.7-rc.2 source checkout.
---

# DSH 插件开发 · 总览与索引

这是一套自用 skill 库的入口。**不知道从哪篇读起时，先读这里。**

## 库地图

九篇正文 + 一篇导航，按「你正在问什么」分成四组：

| 组 | 回答的问题 | 篇目 |
|---|---|---|
| **骨架** | 怎么从零建起来、怎么打包 | `dsh-plugin-dual-half-skeleton` |
| **数据通道** | 数据从哪来、怎么送到界面 | `dsh-session-projection`（投影值流）· `dsh-plugin-fetch-route`（按需路由）· `dsh-multi-source-config`（多实例 + 每源凭据） |
| **界面落位** | 控件放哪、怎么进设置页 | `dsh-client-slot-placement` · `dsh-conversation-view-tab` · `dsh-settings-page` |
| **生存与互操作** | 换宿主版本怎么办、和别人怎么不打架 | `dsh-harness-compat-gate` · `dsh-plugin-robust-mount` |

## 任务 → 该读哪篇

| 你遇到的情况 | 读这篇 |
|---|---|
| 从零建一个带 UI 的插件 | `dsh-plugin-dual-half-skeleton` |
| 客户端构建失败 / react 被打进包 / 白屏 | `dsh-plugin-dual-half-skeleton`（+ `references/bundle-purity.md`） |
| **插件完全没动静，也没有报错** | `dsh-plugin-robust-mount`（顶层 `inject` 硬闸门） |
| 服务比插件晚到，注册没生效 | `dsh-plugin-robust-mount`（`ctx.inject` vs `ctx.get`） |
| 同一 bundle 被挂两次，每个座位两份 | `dsh-plugin-robust-mount`（单活挂载守卫） |
| 要改写系统提示词 | `dsh-plugin-robust-mount`（+ 副作用明示） |
| 按钮 / 面板 / 浮层放哪、被裁切、不出现 | `dsh-client-slot-placement` |
| 在会话视图里加一个标签页 | `dsh-conversation-view-tab` |
| 设置弹窗里加一页 / 一个配置卡片 | `dsh-settings-page` |
| 配置在设置页里改不动 / 改了没生效 | `dsh-settings-page`（volatile 双轨） |
| 同一个服务有多套实例（prod / staging） | `dsh-multi-source-config` |
| 把会话日志变成界面上的数据 | `dsh-session-projection` |
| 数据很大 / 打开面板才要 / 含凭据不能下发 | `dsh-plugin-fetch-route` |
| 路由 404、越权、自己起 HTTP server | `dsh-plugin-fetch-route`（认证围栏） |
| 查看一个大日志时宿主卡住 | `dsh-plugin-fetch-route`（冷读闸 + 让出事件循环） |
| 插件在某个宿主版本上行为异常 | `dsh-harness-compat-gate` |
| 要声明「我支持哪些宿主版本」 | `dsh-harness-compat-gate`（+ `references/support-matrix.md`） |
| 插槽在某个宿主世代不存在 | `dsh-settings-page`（候选槽降级适配器） |
| 升级后插件起不来（陈旧配置值） | `dsh-settings-page`（`.loose()`） |

## 从零到上线的阅读顺序

1. **骨架** → `dsh-plugin-dual-half-skeleton`：把 `package.json`、两个半边、构建链摆正
2. **数据** → 先答一个问题：*这份数据会不会随每次 `session.list` 推送走？*
   会 → `dsh-session-projection`；不会 → `dsh-plugin-fetch-route`
3. **界面** → `dsh-client-slot-placement`（放哪）→ 按需 `dsh-conversation-view-tab` /
   `dsh-settings-page`
4. **配置** → `dsh-settings-page`（含 volatile 双轨）→ 多实例用 `dsh-multi-source-config`
5. **收口** → `dsh-harness-compat-gate`（探测 + 门控 + 支持矩阵）
   + `dsh-plugin-robust-mount`（可选依赖、单活、副作用）

第 1、2 步是地基 —— 缺任何一个，后面几步都用不上。

## 真相来源（按权威性排序）

写代码前先确认「事实在哪」，这一步比读文档重要。

| 要判断的事 | 去哪读 |
|---|---|
| **运行时行为**（服务在不在、面长什么样） | **本机已装副本** `<dsh-home>\profiles\desktop\node_modules\<包名>\` |
| 已装宿主版本 | asar 内 `dsh/desktop-runtime.json` 的 `release.version`（**不是** profile 下的 `runtime.json`，那个不存在） |
| **构建语义 / 平台模块表** | `<harness-checkout>\packages\client\`（0.1.7-rc.2 检出） |
| 本机自研插件（7 个） | `<my-plugins-dir>\` |
| 第三方成熟范例（2k★，日更） | `<dsh-context-checkout>`（v0.72.0 快照，约 20MB，不需要可删） |
| 官方宿主源码（asar 内提取） | `<asar-extract-dir>\` |

**三条铁律**：

1. **本地检出 ≠ 已装版本**。本机实测：源码树 `0.1.7-rc.2`，已装 `0.2.0-rc.2` —— 两代不同线。
   读**构建语义**看检出可以，判断**运行时契约**必须看已装副本
2. **别在本地检出里找插件源码**。`<plugins-dir>\dsh-context\` 是 0.54.2 的旧快照且
   不是 git 克隆；它和已装的 0.72.0 差了 18 个版本
3. **源码优先于文档**（包括这套 skill）。skill 里的结论都标了核实版本，冲突时以源码为准

## 跨篇反模式速查

最容易犯、后果最重的一批，按痛感排序：

| # | 反模式 | 后果 | 哪篇详述 |
|---|---|---|---|
| 1 | 顶层 `inject` 写了可能缺席的服务 | 插件**静默**不加载，无任何报错 | `dsh-plugin-robust-mount` |
| 2 | 用 `ctx.get()` 去等一个还没到的服务 | 永远拿不到，且不重试 | `dsh-plugin-robust-mount` |
| 3 | 浏览器半 `import` 宿主半的值 | 构建失败（纯净门）或两份值漂移 | `dsh-plugin-dual-half-skeleton` |
| 4 | `register` 不带稳定 `id` | 无法守卫，双挂载处画两份 | `dsh-plugin-robust-mount` |
| 5 | 投影 `apply` 忽略事件时返回 `{...state}` | 每条事件都发布一次（coredump 级重渲染） | `dsh-session-projection` |
| 6 | 配置字段标错 volatile 双轨 | 改不动，或改了不生效 | `dsh-settings-page` |
| 7 | 自己起 HTTP server 当插件路由 | 落在认证围栏外、不随 profile 卸载 | `dsh-plugin-fetch-route` |
| 8 | 忘了 `.bind(拥有者对象)` | 延后调用时 `this` 丢失 | `dsh-plugin-fetch-route` / `-robust-mount` |
| 9 | 大循环不让出事件循环 | 查看一个大日志 = 宿主卡近一秒 | `dsh-plugin-fetch-route` |
| 10 | 到处写版本号分支而不探测能力 | 每个新宿主版本都要改一遍代码 | `dsh-harness-compat-gate` |
| 11 | 探测不到版本就兜一个默认值 | 门控用假数据判断，可能误关功能 | `dsh-harness-compat-gate` |
| 12 | `c.effect` 里注册与注销分开写 | 泄漏注册，且不报错 | `dsh-plugin-robust-mount` |
| 13 | CSS import 顺序随意 | 样式互相覆盖 | `dsh-plugin-dual-half-skeleton` |
| 14 | 忘了 `.loose()` | 升级后陈旧配置值让 entry 装载失败 | `dsh-settings-page` |

## 这套库的维护规则

新增或修改 skill 时照这套走（否则库会退化成互相矛盾的碎片）：

| 规则 | 说明 |
|---|---|
| **一 skill 一目录** | `SKILL.md` + `references/`；深度细节进 references，SKILL.md 控制在 250 行上下 |
| **frontmatter 用英文** | `name` / `description`（写成「什么时候该用它」）/ `license: MIT` / `compatibility`（注明核实版本） |
| **正文用中文** | 表格优先，偏差表 + 检查清单是必备两节 |
| **收尾必须有互引行** | 「配套 skill：…」+「总览与索引见 `dsh-plugin-dev-guide`」 |
| **双向回填** | 新增一篇，必须回填既有篇目里的互引 —— 单向链接会让导航失真 |
| **标注取材与许可** | 摘第三方的结构/语义要写明来源（当前取材自 `bowenliang123/dsh-context`，Apache-2.0），代码重写为骨架 |
| **标核实版本** | 每条契约都要能回答「这是哪个版本上核实的」 |
| **行尾与本库一致** | 改写时按文件实际换行符读写，否则整文件假 diff |
| **不要创建重复篇** | 主题重叠时先并入既有篇（volatile 双轨就是这么并进 `dsh-settings-page` 的） |

## 本库之外

| 位置 | 内容 |
|---|---|
| `_notes\` | 历史规划与勘察稿（不参与 skill 加载）：`_分析-dsh-context-可蒸馏技术.md`（15 技术点 → 5 候选的完整推导，含「不建议蒸馏」清单） |
| `<memory-dir>\` | 项目长期约定（`MEMORY.md`）与每日工作日志 |

配套 skill：以上索引全部指向本库正文；入口之外**没有第二份事实来源** ——
需要新知识时，先按「真相来源」一节去读代码，再把结论写回对应篇目。
