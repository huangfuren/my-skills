# DSH 插件开发 skill 库

这是**自用**的一套 DSH（DeepSeek Harness）插件开发知识库，共 **11 篇 skill**。

每一篇回答一类具体问题：从零建插件、数据怎么送到界面、控件放哪、换宿主版本怎么办。
结论都来自**读源码 + 本机实测**，每篇标注了核实版本 —— 不是泛泛的经验总结。

> **不知道从哪篇读起 → 直接看 `dsh-plugin-dev-guide`**（库入口，含「任务 → 该读哪篇」索引）。

---

## 目录

| # | skill | 一句话功能 |
|---|---|---|
| 1 | [`dsh-plugin-dev-guide`](#1-dsh-plugin-dev-guide) | 库入口：任务路由、阅读顺序、真相来源 |
| 2 | [`dsh-plugin-dual-half-skeleton`](#2-dsh-plugin-dual-half-skeleton) | 双半边骨架 + 客户端 bundle 构建链 |
| 3 | [`dsh-session-projection`](#3-dsh-session-projection) | 会话日志 → 投影值流（推给浏览器） |
| 4 | [`dsh-plugin-fetch-route`](#4-dsh-plugin-fetch-route) | 宿主侧按需取数：认证路由 + 冷读治理 |
| 5 | [`dsh-multi-source-config`](#5-dsh-multi-source-config) | 同一服务多实例 + 每源独立凭据 |
| 6 | [`dsh-client-slot-placement`](#6-dsh-client-slot-placement) | 控件/面板放哪、怎么不被裁切 |
| 7 | [`dsh-conversation-view-tab`](#7-dsh-conversation-view-tab) | 会话视图里加一个标签页 |
| 8 | [`dsh-settings-page`](#8-dsh-settings-page) | 设置弹窗里加一页 / 配置卡片 |
| 9 | [`dsh-harness-compat-gate`](#9-dsh-harness-compat-gate) | 跨宿主版本探测、门控与降级 |
| 10 | [`dsh-plugin-robust-mount`](#10-dsh-plugin-robust-mount) | 可选依赖、单活挂载、副作用治理 |
| 11 | [`dsh-agent-loop-discipline`](#11-dsh-agent-loop-discipline) | 自己跑 agent 循环：终止、预算、收尾纪律 |

---

## 库地图

十篇正文 + 一篇导航，按「你正在问什么」分五组：

| 组 | 回答的问题 | 篇目 |
|---|---|---|
| **骨架** | 怎么从零建起来、怎么打包 | 2 |
| **数据通道** | 数据从哪来、怎么送到界面 | 3 · 4 · 5 |
| **界面落位** | 控件放哪、怎么进设置页 | 6 · 7 · 8 |
| **执行循环** | 自己跑多步循环、怎么收得住 | 11 |
| **生存与互操作** | 换宿主版本怎么办、和别人怎么不打架 | 9 · 10 |

其中 **2 和 3 是地基** —— 缺任何一个，后面几步都用不上。

---

## 逐篇详解

### 1. `dsh-plugin-dev-guide`

**功能**：整库的入口与索引。它本身不含事实，只做路由。

**解决什么问题**：手上有一堆 skill，但不知道某个具体任务该翻哪篇。

**内容**：
- 「你遇到什么 → 读哪篇」19 条索引（按症状查，比如「插件完全没动静，也没有报错」）
- 从零到上线的 5 步阅读顺序
- **真相来源** 6 处：判断运行时行为该读哪个副本、构建语义该读哪里
- 14 条跨篇反模式速查（按痛感排序）
- 本库的 9 条维护规则

**何时用**：开始任何 DSH 插件工作之前。

---

### 2. `dsh-plugin-dual-half-skeleton`

**功能**：一个 DSH 插件为什么是「两个半边」，以及怎么把它们和构建链摆正。

**背景**：DSH 插件 = **host 半边**（Node 侧，写 `apply`）+ **client 半边**（浏览器侧，React 组件）。
两边导出形态不对称、装载方式不同、打包规则严格 —— 这是新手最容易翻车的地方。

**内容**：
- `dsh.bundle.patch` 与 `dsh.client.platform = "web"` 的声明式装载
- **导出形态不对称**：host 用 ESM `export function apply`，client 用 CJS `module.exports`
- tsdown 链：React + Tailwind 怎么编译成单个 `client.js`
- **平台模块白名单纯净门**：`react` 必须留给注入的 `require`，其余 import 一律构建失败
- CSS import 顺序即级联顺序（Tailwind 必须排第一）
- i18n 词典注册 + label thunk

**references**：
- `skeleton.md` —— 目录结构、`package.json`、两个半边、tsdown 双配置、落地顺序
- `bundle-purity.md` —— `__ModuleLoader__` 三件套、官方 9 项平台模块表、纯净门正则、产物自检

**何时用**：新建带 UI 的插件；或浏览器半白屏、客户端构建失败时。

---

### 3. `dsh-session-projection`

**功能**：把**已提交的会话事件日志**折叠成每个会话的状态，流给浏览器。

**典型场景**：会话统计、todo / goal 快照、任何「从日志推导出来的只读模型」。

**三条铁律**（靠猜写不对的）：
1. `apply` 对**忽略的事件必须返回同一引用**（返回 `{...state}` 会让每条事件都发布一次）
2. **不写 `wire` 就是 host-only** —— 值永不下发浏览器
3. 一切同步，不做异步

**内容**：`key / stateSchema / init / apply / wire / stateVersion` 六字段契约、
注册生命周期与共享 key 引用计数、四个读取面（`snapshot` / `onChanged` / `stateOf` / `checkpoint`）、
瘦 wire 纪律、客户端 `useProjection` 座位。

**references**：
- `contract.md` —— 逐字段语义、`Object.is` 双闸、注册实现、已知限制
- `skeleton.md` —— wire 单元 + host-only 单元 + 注册 + 订阅 + 客户端座位
- `state-version-and-legacy.md` —— bump 时机、升降级处置、两代差异、零值降级

**何时用**：宿主半要从会话日志推导状态并给浏览器。

---

### 4. `dsh-plugin-fetch-route`

**功能**：宿主半的数据**按需**给浏览器 —— 投影值流送不动的部分。

**典型场景**：大集合（几千条明细）、机器本地路径、含凭据的远程读取。

**内容**：
- 走 `ctx.connection.fetch.register` 落在**已认证的 `/api` 围栏内** —— **不要自己起 HTTP server**
- 三条铁律：bind-at-extraction / `c.effect` 管 disposer / refuse-quietly
- 活会话走 `stateOf` 不二次折叠；冷会话走 `observeSession` + 必须 `Symbol.dispose`
- 缓存键必须是 **`(persistence, id, revision)` 三元组**（防换后端后命中陈旧数据）
- **全宿主共享的冷读闸**：FIFO + 2/3 水位 + 探测 fail open
- 大折叠每 1000 事件让出事件循环
- 客户端三层校验 + 代数 / revision 双游标

**references**：`connection-seam.md`（路由 seam）/ `data-paths.md`（活冷双路径）/ `client-call-site.md`（客户端调用侧）

**何时用**：数据大、要打开面板才取、或含凭据不能随每次 `session.list` 下发。

---

### 5. `dsh-multi-source-config`

**功能**：一个插件要对接**同一个服务的多套实例**（prod / staging 的 Grafana、JumpServer）。

**内容**：带一个默认项的命名源列表、每源独立凭据、从旧版单源配置的一次性迁移。

**缺陷场景**（本篇正是为这些写的）：删掉的源重启后又回来、token 轮换在别处被静默回退、一次保存把所有源抹掉。

**关键机制**：
- `SourceConfig` schema + id 派生的凭据引用
- **revision 校验的整数组改写**
- 凭据轮换的分阶段引用
- **孤儿凭据清理规则**：区分「明确拒绝」与「结果未知」两种写结局
- 工具侧按名解析源 + 审批绑定

**references**：`source-model.md` / `save-orchestration.md` / `skeleton.md`

**何时用**：多实例、多凭据的配置功能。

---

### 6. `dsh-client-slot-placement`

**功能**：决定插件的控件**放哪** —— 会话头部的按钮、标签页、侧边栏面板、全高浮层。

**症状触发**：现有挂载位置不对、被裁切、或者**根本不出现**。

**内容**：四步落位法（先找官方先例 → 在 `slots.ts` 确认插槽契约 → 用 `order` 横向排序 →
用固定浮层宿主逃出布局盒）、会话 UI 的插槽选择表、真实插件试错并否决过的方案。

**references**：`header-actions-pattern.md`

**何时用**：任何「这个控件该挂哪里」的决策。

---

### 7. `dsh-conversation-view-tab`

**功能**：在 DSH 会话视图的标签栏（对话 / 轨迹 / 上下文 / 编队）里**加自己的标签页** —— 即一个渲染整块面板的客户端插件。

**内容**：`conversation.view` 插槽契约、`ctx.slots.inject` + `ctx.slots.register` 配方、
按会话注入的 props、store 门控显隐、**「少于 2 个视图会隐藏整个标签栏」**这条规则、
label thunk 本地化、以及一个真实视图需要的 ViewMap 数据管线。

**references**：`viewmap-contract.md`

**何时用**：要在会话视图里增加一个整块面板。

---

### 8. `dsh-settings-page`

**功能**：让插件在**设置弹窗**里有一页自己的位置 —— 左侧导航项（如 Grafana / 思维脑图）、
内置插件区的 tab、或一张读写自身 settings 命名空间的配置卡片。

**内容**：
- **三代插槽降级**：`settings.section` → `settings.plugins.tab` → `settings.plugin.item`
- 宿主半命名空间注册（0.1.5 用 `scope`，0.1.7+ 用 `describe` / `update`）
- 客户端服务降级：`remote.settings` / `connection.api.settings`
- 导航顺序与图标规则
- **volatile 双轨字段**：绑定字段（编辑时重挂载 entry）/ 偏好字段（就地提交）
- `autoGenerate` 自动页策略
- 「页面静默不渲染」的坑

**references**：`skeleton.md` / `settings-namespace.md` / `slot-fallback-adapter.md` / `volatile-two-track.md`

**何时用**：插件需要设置入口；或入口不出现 / 出现在错误的宿主世代、配置改不动时。

---

### 9. `dsh-harness-compat-gate`

**功能**：让插件在**多个宿主版本**上都能活。

**症状触发**：某功能在旧宿主上静默变空白、某配置字段只在某些宿主存在、
旧版本存下的值让 entry 装载失败、或需要声明支持矩阵。

**第一原则 —— fail open**：探测误报绝不能让可用部署变空白。方向是不对称的：
「误判为太老」的代价远大于「误判为够新」。

**内容**：
- **双锚点版本探测**（运行模块树优先于 home 镜像）+ `isInside` 守卫
- 感知发布通道的版本比较（正式 > rc > beta > alpha）
- 基线门控：低于基线时注册**零值降级单元**而不是不注册
- pre-0.1.1 的 `schema` / `view` 别名
- 特性探测的字段修饰器 —— 一套 schema 服务所有宿主

**references**：`version-probe.md` / `baseline-gate.md` / `support-matrix.md`

**何时用**：插件要跨宿主版本；或要声明「我支持哪些宿主」。

---

### 10. `dsh-plugin-robust-mount`

**功能**：让插件与**它不控制的服务和插件**和平共处。

**症状触发**：
- 插件**静默**不加载（顶层硬 `inject` 写了一个缺席的服务）
- 服务比插件晚到，注册被漏掉
- 同一 bundle 被挂两次，每个座位画两份
- 插件要注册系统提示词段

**内容**：
- **三态语义**：硬 `inject`（缺席即静默 INACTIVE）/ `ctx.inject`（延迟注入，服务后到也生效）/
  `ctx.get`（即时读取，不会等服务到达）
- re-prove-and-bind 边界规则
- **slot ledger 单活挂载守卫**（根因：运行器给每次注册新的 shadowing priority）
- 服务拆除时的清理
- 系统提示段注入契约与 order 锚点（**副作用明示**）

**references**：`inject-semantics.md` / `single-mount-guard.md` / `system-prompt-section.md`

**何时用**：插件行为不确定、可选依赖缺席、或要注入系统提示。

---

### 11. `dsh-agent-loop-discipline`

**功能**：插件自己拥有 agent 循环时，把「什么时候停、算不算成功、试几次、结果不明怎么报」定成可检查的规矩。

**症状触发**：
- AI 说「已完成」，但机器上什么都没变
- 步数用完了，循环却报成功
- 执行结果拿不到（超时 / 断连），不知道该报什么
- AI 越跑越偏，忘了最初的目标
- AI 把自己命令的回显当成机器返回的信息

**内容**：
- **四个具名终态** + 空态；`COMPLETED` 与 `ROUND_LIMIT` 必须分开
- **三条优先级规则**：未知优先于耗尽 / 完成不可伪造 / 收尾单一路径
- **窄失败判定**：以「命令不存在」为例，四条约束同时成立才接受
- **三层预算分开计**：步数（决策次数）/ 读次数 / 输出长度
- **契约与实现分离**：可选能力用 `?` 标记，不用空函数
- **会话隔离用可升级 uid 盒**，不用布尔标记
- 规格编号注释（让行为可回溯到需求）

**references**：`termination-semantics.md` / `budget-and-context.md` / `runtime-contract.md`

**何时用**：插件里有一个多步执行循环，且工具会改真实机器。

---

## 怎么用

- **被 DSH 加载**：每篇是一目录，`SKILL.md` + `references/`。
  加载时读 `SKILL.md` 的 frontmatter `description`（写成「什么时候该用它」）判断是否命中。
- **人工查阅**：直接打开对应目录的 `SKILL.md`；深度细节在 `references/` 里。
- **写代码前**：先按 `dsh-plugin-dev-guide` 的「真相来源」一节确认事实在哪，
  这比读文档更重要。

---

## 库的约定

| 规则 | 说明 |
|---|---|
| 一 skill 一目录 | `SKILL.md`（约 250 行）+ `references/`；深度细节进 references |
| frontmatter 用英文 | `name` / `description` / `license: MIT` / `compatibility`（注明核实版本） |
| 正文用中文 | 表格优先；偏差表 + 检查清单是必备两节 |
| 收尾必有互引行 | 「配套 skill：…」+「总览与索引见 `dsh-plugin-dev-guide`」 |
| 互引双向回填 | 新增一篇，必须回填既有篇里的引用 —— 单向链接会让导航失真 |
| 标注取材与许可 | 摘第三方结构 / 语义要写明来源（当前两处：`bowenliang123/dsh-context` Apache-2.0、`guhanfei-ai/zterm` MIT），代码重写为骨架 |
| 标核实版本 | 每条契约都要能回答「这是在哪个版本上核实的」 |
| 不建重复篇 | 主题重叠时先并入既有篇 |

**统一校验**：`<skill-lint.mjs>`（frontmatter / 死链 / 互引行 / 导航行 / 行尾 / 孤立篇目）。

---

## 目录内其他内容

| 位置 | 内容 |
|---|---|
| `_notes\` | 历史规划与勘察稿（**仅本地保留，不随仓库发布**），不参与 skill 加载。<br>`_分析-dsh-context-可蒸馏技术.md` —— 15 技术点 → 5 候选的完整推导（含「不建议蒸馏」清单） |
| `README.md` | 本文件 |

## 库外相关位置

| 位置 | 内容 |
|---|---|
| `<dsh-home>\profiles\desktop\node_modules\<包名>\` | **运行时行为的权威副本**（已装插件） |
| `<harness-checkout>\` | 官方源码树（0.1.7-rc.2 检出，看构建语义） |
| `<dsh-context-checkout>\` | 第三方成熟范例快照（v0.72.0，约 20MB，不需要可删） |
| `<my-plugins-dir>\` | 本机 7 个自研插件 |
| `<memory-dir>\` | 项目长期约定与每日日志 |

---

**三条铁律**（写代码前务必记住）：

1. **本地检出 ≠ 已装版本** —— 本机源码树 `0.1.7-rc.2`、已装 `0.2.0-rc.2`，两代不同线。
   看构建语义可以读检出，判断运行时契约必须读**已装副本**。
2. **别在本地检出里找插件源码** —— `dsh-plugin\dsh-context\` 是旧快照且不是 git 克隆。
3. **源码优先于文档**（包括这套 skill）—— 冲突时以源码为准。

---

## 关于路径（发布版说明）

本目录发布时做过**脱敏**：原文中的本机绝对路径已统一替换为占位符，含义如下。

| 占位符 | 原指 |
|---|---|
| `<dsh-home>` | DSH 主目录（`DSH_HOME`，通常 `~/.dsh`） |
| `<user-home>` | 用户主目录 |
| `<install-dir>` | DSH 桌面端安装目录（`app.asar` 所在） |
| `<harness-checkout>` | DSH 官方源码检出 |
| `<dsh-context-checkout>` | 第三方范例 `dsh-context` 的源码检出 |
| `<ctx-src>` | 第三方源码检材目录 |
| `<asar-extract-dir>` | 从 `app.asar` 提取出的宿主源码目录 |
| `<plugins-dir>` / `<my-plugins-dir>` | 插件目录 / 自研插件目录 |
| `<memory-dir>` | 项目记忆目录 |
| `<skill-lint.mjs>` | 本库一致性校验脚本 |
| `<workspace>` | 其它本地工作区路径 |

另：`_notes/`（历史规划与蒸馏推导稿）**不在发布范围内**。
