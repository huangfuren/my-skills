---
name: dsh-client-slot-placement
description: >-
  Use when deciding WHERE to mount a DSH client plugin's control or surface — a
  button in the conversation header, a tab, a sidebar panel, a full-height overlay —
  or when an existing mount renders in the wrong place, gets clipped, or never
  appears. Gives the four-step placement process (find an official precedent first,
  confirm the slot contract in slots.ts, position horizontally with `order`, escape a
  layout box with a fixed overlay host), a slot selection table for the DSH session
  UI, and the approaches real plugins tried and rejected.
license: MIT
compatibility: >-
  DSH client plugins (dsh.client.platform = "web"), Web and desktop profiles.
  Slot names and kinds verified against dsh 0.2.0-rc.2
  (@deepseek-ai/dsh-client-ui-conversation, dsh-client-ui-layout).
---

# DSH 插件控件落位设计

目标：把「我想让这个按钮/面板出现在那儿」在**几步内**变成一个正确的插槽注册，
不靠猜、不靠试错。

## 四步流程

```
① 找先例   →  grep 官方包，找已经待在那个位置的控件（不要先读文档）
② 验契约   →  读该插槽在 slots.ts 的声明：kind / scope / owner
③ 定横向   →  用 order 排位（升序；负序是"前导带"）
④ 放不下   →  插槽是布局盒子 → fixed 宿主层自举
```

---

## ① 找先例（最省时间的一步）

**不要**先翻文档找"有没有顶部插槽"。反过来：**看官方在同一个位置放了什么控件，
再抄它的注册**。先例同时给你 `kind`、`scope`、`order` 量级和 owner props 形状。

```bash
# 在候选包里列出所有插槽注册
grep -rn "slots.register\|slots.inject" <pkg>/src/client
# 已知位置的一条线索：它 inject 了哪个包
grep -n '"inject"' <plugin>/package.json     # dsh.client.inject
```

判断该读哪个包：

| 你想要的位置 | 先去读 |
|---|---|
| 会话表头 / 对话区 / 标签 | `@deepseek-ai/dsh-client-ui-conversation` |
| 整体骨架 / 侧栏 / 主区 / 浮层 | `@deepseek-ai/dsh-client-ui-layout` |
| 设置页 | `@deepseek-ai/dsh-client-ui-settings` |

包的 `src/client/contract/slots.ts` 是**唯一事实来源**：每个插槽都有注释说明用途，
`kind` 决定能不能共存。

**`kind` 语义**：

| kind | 含义 | 后果 |
|---|---|---|
| `single` | 只有一个占用者 | 后注册的会与先注册的冲突，别抢官方的位置 |
| `list` | 多个并列，按 `order` 升序 | 追加式，最适合第三方 |
| `keyed` | 按 key 索引（如 `main`） | 自己占一个 key |
| `chain` | selector 竞争，首个返回非 null 的获选 | 用于"接管"类覆盖（如 composer） |

---

## ② 插槽选型表（会话界面）

| 想放哪 | 插槽 | 形态 |
|---|---|---|
| 表头，标题右侧动作 | `conversation.session.header.actions` | `list` / session / 升序 |
| 表头右对齐工具区 | `conversation.session.header.utilities` | `list` / session / 升序 |
| 表头最右角（**只放一个**控件） | `conversation.session.header.corner` | `single` / session |
| 替换面包屑标题 | `conversation.session.header.lineage` | `single` / session |
| 对话标签页 | `conversation.view` | `list` / session |
| 覆盖输入框 | `conversation.composer` | `chain` / session |
| 右侧栏面板 | `sidebar.panellist` | `list` |
| 设置页左栏导航 | `settings.section` | `list` / root |
| 骨架层主导航 | `main` / `sidebar` / `rightbar` | `keyed`/`single` / root |

> 标签页有独立的契约与可见性规则（少于 2 个视图整条标签栏隐藏），
> 见配套 skill `dsh-conversation-view-tab`。

**`scope` 决定你能拿到什么 props**：`session` 拿得到当前会话（`useSession`/`sessionId`/
`inputActions`）；`root` 拿不到；`session-maybe` 可能没有会话（空态）。

---

## ③ 用 `order` 定横向位置

同 `list` 插槽内**按 `order` 升序**排列。这是全部规则——没有左右插槽之分。

官方注释原话：*"Static session context occupies the header's leading negative-order band."*
即**负序是前导带**。实测值：

| 控件 | order |
|---|---|
| 内置 agent 预设标签（「标准模式」） | `-10` |
| `dsh-mindmap` 的「思维脑图」 | `100` |

所以想让自己的按钮排在「标准模式」**左边**用 `< -10`，**右边**用 `> -10`。

> 想要「右对齐」别靠大 order 硬挤——那是 `conversation.session.header.utilities` 的职责。

---

## ④ 放不下时：fixed 宿主层自举

**触发条件**：插槽落在布局盒子里（表头、工具行），但你要渲染**全高/全宽**面板。
直接渲染会被盒子的尺寸与 `overflow` 裁掉。

**解法**：在同一次注册里渲染两个兄弟节点——一个占位按钮 + 一个 `position: fixed` 的宿主层。

```jsx
function MySlot(props) {
  const [open, setOpen] = useState(false)
  return <>
    <button style={S.chip} onClick={() => setOpen(v => !v)}>我的面板</button>
    <div style={S.panelHost}>{open && <Panel …/>}</div>
  </>
}
```

三层结构，缺一层就会挡住聊天区：

```js
panelHost:    { position:"fixed", inset:0, pointerEvents:"none", zIndex:40 },
              // 全屏透明层：不挡交互，只当定位上下文
overlayRoot:  { position:"absolute", top:0, right:0, bottom:0, display:"flex",
                pointerEvents:"auto" },   // 实际面板：自己 opt-in 交互
overlayHandle:{ position:"absolute", left:-4, width:8, cursor:"col-resize" }
```

**要点**：

- 宿主层必须 `pointerEvents: none`，面板自己开 `auto`——否则整页点不动
- z-index 分层留余量（实测：宿主 40 / 浮动菜单 60 / 代码浮窗 70）
- 可拖宽就配 `localStorage` 持久化，并在 `resize` 时**持续钳制**（只在挂载压一次，
  窗口先放大→拖宽→再缩小会把聊天区挤没）
- 同款思路的另一个先例：`better-sidebar` 把宿主层挂在 `conversation.chat.turnTail`

按钮要看起来"和邻居一排"，就**复用邻居的设计 token**（`--dsw-alias-*`），
而不是自己定尺寸：

```js
chip: { display:"inline-flex", alignItems:"center", gap:"4px", height:"22px",
        padding:"0 8px", borderRadius:"6px", fontSize:"12px", font:"inherit",
        background:"var(--dsw-alias-fill-tsp-secondary)",
        color:"var(--dsw-alias-label-secondary)", border:"none", cursor:"pointer" }
```

---

## 被否决的方案（别重踩）

| 方案 | 结果 |
|---|---|
| 挂 `details` 槽 | **官方已收回**，不要依赖 |
| 挂 `shell.overlay` 做浮层 | 声明存在（`list`/root）但**实测不渲染**，已弃用 |
| 跨槽传 props | 不需要。`session` scope 下全套 props 直给（`useSession`/`sessionId`/`inputActions`） |
| 在 `single` 槽抢官方位置 | 会冲突。第三方一律优先选 `list` 槽 |

> 这些取舍的价值在于：**先例的注释里已经写下了失败路径**。所以第 ① 步要找的是
> "有注释、有 docs 目录"的实现，而不只是能跑的代码。

---

## 落地检查清单

- [ ] 已找到同位置的官方先例，并抄了它的 `kind` / `order` 量级
- [ ] 插槽是 `list`（第三方不抢 `single`）
- [ ] `order` 相对邻居合理（前导带用负值）
- [ ] `dsh.client.inject` 声明了所需客户端包，`platform: "web"`
- [ ] 渲染全高/全宽面板时用了 fixed 宿主层，且宿主 `pointerEvents: none`
- [ ] 面板打开时聊天区仍可点击（手动验证）
- [ ] 拖拽宽度在 `resize` 时有持续钳制
- [ ] 按钮样式复用 `--dsw-alias-*` token，与邻居视觉一致

## 参考实现

| 位置 | 文件 |
|---|---|
| 表头按钮 + fixed 全高面板（完整范例） | `<plugins-dir>\dsh-mindmap\client.js`：注册 3125、组件 1488、样式 1195 |
| 表头「标准模式」标签（负序前导带） | `…\dsh-client-ui-agent-preset\src\client\index.ts`（`id: 'agent-preset'`, `order: -10`） |
| 插槽声明唯一事实来源 | `…\dsh-client-ui-conversation\src\client\contract\slots.ts` |
| 骨架层插槽 | `…\dsh-client-ui-layout\src\client\contract\slots.ts` |

详细的 mindmap 落地代码（注册片段 + 组件 + 样式 + 排序推算）见
[references/header-actions-pattern.md](references/header-actions-pattern.md)。

配套 skill：会话标签页见 `dsh-conversation-view-tab`；设置页入口见 `dsh-settings-page`；
从零建双半边插件（声明式装载、客户端 bundle 构建链、React/Tailwind 打包）见
`dsh-plugin-dual-half-skeleton`；把会话数据流给你渲染的视图见 `dsh-session-projection`；
控件要展示的数据由宿主半随取随送见 `dsh-plugin-fetch-route`；同一 bundle 被挂两次导致
每个座位画两份见 `dsh-plugin-robust-mount`。

总览与索引见 `dsh-plugin-dev-guide`。
