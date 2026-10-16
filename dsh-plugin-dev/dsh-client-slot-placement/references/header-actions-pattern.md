# 范例：mindmap 按钮落到会话表头

`dsh-mindmap` v0.5.1（第三方，作者 guhanfei-ai）的「思维脑图」按钮，
与内置的「标准模式」标签并排出现在会话表头。以下是它完整的落地过程与代码。

## 目标位置的推导

1. 观察：按钮在会话区最顶部一行，标题右侧，与「标准模式」水平对齐
2. 反查「标准模式」是谁 —— `@deepseek-ai/dsh-client-ui-agent-preset`，
   注册进 `conversation.session.header.actions`
3. 读该插槽声明（`dsh-client-ui-conversation/src/client/contract/slots.ts:156`）：

```ts
/** Title-adjacent Session actions in ascending order. */
'conversation.session.header.actions': {
  kind: 'list'
  scope: 'session'
  owner: ConversationHeaderActionOwnerProps
}
```

→ `list` 槽可共存、`session` scope 给全量会话 props、**升序**排列。
结论：**跟它挂同一个槽就行**，横向位置由 `order` 决定。

## 排序推算

同一个 `list` 槽内的两个注册项：

| 注册者 | id | order | 组件 |
|---|---|---|---|
| `ui-agent-preset`（内置） | `agent-preset` | **-10** | `AgentPresetLabel`（「标准模式」） |
| `dsh-mindmap`（第三方） | `dsh-mindmap` | **100** | `MindmapSlot`（「思维脑图」） |

升序 → `-10` 在前、`100` 在后。这就是"并排且标准模式在左"的全部原因。

`ui-agent-preset` 的注释点明了负序的含义：

```ts
// Static session context occupies the header's leading negative-order band.
order: -10,
```

## 注册代码

`dsh-mindmap/client.js:3111-3130`：

```js
// 015 设置面板：settings.section（list 槽、root scope）——设置页左栏
// 新增「思维脑图」导航项
ctx.slots.inject("settings.section", () => ctx.slots.register({
  name: "settings.section",
  id: "dsh-mindmap",
  order: 100,
  label: "思维脑图",
  inject: () => ({ mindmapFace: face }),
}, SettingsPanel));

// 014 overlay 形态：面板宿主层（position:fixed）
// 与 M 按钮一起渲染在 conversation.session.header.actions 槽位里——
// better-sidebar 同款「fixed 宿主层自举」思路（它的宿主层挂在
// conversation.chat.turnTail）；session scope 全套 props 直给，无需跨槽。
// details 槽已归还官方（原生「工具详情」栏恢复）；shell.overlay 方案
// 实测未渲染，已弃用（见 docs/014 排障）。
ctx.slots.inject("conversation.session.header.actions", () => ctx.slots.register({
  name: "conversation.session.header.actions",
  id: "dsh-mindmap",
  order: 100,
  inject: () => ({ mindmapFace: face }),
}, MindmapSlot));
```

注意 `id` 在两条注册里都是 `dsh-mindmap` —— id 只需在**各自插槽内**唯一。

## 组件：一次注册渲染按钮 + 面板

`client.js:1488-1537`：

```js
function MindmapSlot(props) {
  const { useSession, sessionId, inputActions, mindmapFace } = props;
  const nodes = useSession ? useSession((s) => (s && s.nodes) || EMPTY_NODES) : EMPTY_NODES;
  // 016 可靠性加固：结构指纹作第二 selector。
  // store 原地改数组（引用不变）时 nodes prop 不换、memo 命中缓存、
  // auto-open effect 永不重跑 —— 「AI 打开了脑图但面板不展开」的根因。
  const nodesVersion = useSession
    ? useSession((s) => nodesFingerprint((s && s.nodes) || EMPTY_NODES))
    : "";
  const [open, setOpen] = React.useState(false);

  return <>
    <button type="button" title="脑图面板：展开 / 收起"
            style={S.mButton} onClick={() => setOpen((v) => !v)}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none"
           stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"
           strokeLinejoin="round" aria-hidden="true"
           style={{ opacity: 0.7, flex: "none" }}>
        <circle cx="2.5" cy="7" r="1.7" />
        <circle cx="11.5" cy="3.5" r="1.7" />
        <circle cx="11.5" cy="10.5" r="1.7" />
        <path d="M4.1 6.2 L9.9 4.2" />
        <path d="M4.1 7.8 L9.9 9.8" />
      </svg>
      思维脑图
    </button>
    <MindmapDetailsPanel
      open={open} sessionId={sessionId} inputActions={inputActions}
      nodes={nodes} nodesVersion={nodesVersion} mindmapFace={mindmapFace}
      onOpen={() => setOpen(true)} onClose={() => setOpen(false)} />
  </>;
}
```

两个要点：

- **`session` scope 把 `useSession` / `sessionId` / `inputActions` 直接给了插槽组件**，
  不需要 any 桥接层（插件注释原话：*"全套 props 直给，无需跨槽"*）
- **结构指纹 `nodesVersion` 作第二 selector** —— store 原地改数组时引用不变，
  只靠 `nodes` 会让 `useMemo` 命中缓存、副作用永不重跑

## 样式：fixed 宿主层 + 复用邻居 token

`client.js:1195` 起：

```js
// 按钮：刻意复用邻居（标准模式）的 token，看起来是一排
mButton: {
  display: "inline-flex", alignItems: "center", gap: "4px", padding: "0 8px",
  height: "22px", background: "var(--dsw-alias-fill-tsp-secondary)",
  color: "var(--dsw-alias-label-secondary)", border: "none", borderRadius: "6px",
  cursor: "pointer", font: "inherit", fontSize: "12px", whiteSpace: "nowrap"
},

// 014 overlay 外壳：右缘贴边全高悬浮面板，点击穿透层里自 opt-in pointer-events。
panelHost: {
  position: "fixed", top: 0, right: 0, bottom: 0, left: 0,
  pointerEvents: "none", zIndex: 40
},
overlayRoot: {
  position: "absolute", top: 0, right: 0, bottom: 0, display: "flex",
  flexDirection: "column", background: "var(--dsw-alias-bg-base)",
  color: "var(--dsw-alias-label-primary)", fontSize: "13px", minWidth: 0,
  borderLeft: "1px solid var(--dsw-alias-border-l2)",
  boxShadow: "-8px 0 24px rgba(16,24,40,0.10)", pointerEvents: "auto"
},
overlayHandle: {
  position: "absolute", left: -4, top: 0, bottom: 0, width: 8,
  cursor: "col-resize", zIndex: 1
},
```

同文件里的其他浮层 z-index（分层留余量）：

| 层 | z-index |
|---|---|
| `panelHost`（穿透宿主） | 40 |
| `treeMenu`（浮动菜单） | 60 |
| `codePanel` / `textPanel`（代码浮窗） | 70 |

## 宽度拖拽的持久化与钳制

```js
const WIDTH_KEY = "dsh-mindmap.overlay-width";
const [panelWidth, setPanelWidth] = React.useState(() => {
  try {
    const saved = Number(localStorage.getItem(WIDTH_KEY));
    if (Number.isFinite(saved) && saved >= 280) {
      return Math.min(saved, Math.round(window.innerWidth * 0.8));
    }
  } catch { /* localStorage 不可用：走默认 */ }
  return Math.round(window.innerWidth * 0.42);
});

// 窗口尺寸变化时持续钳制 —— 只在挂载时压一次的话，
// 窗口先放大 → 拖宽 → 再缩小会让面板保持旧像素宽，聊天区被挤没。
React.useEffect(() => {
  const clamp = () => setPanelWidth((prev) => {
    const max = Math.round(window.innerWidth * 0.8);
    return prev > max ? max : prev;
  });
  clamp();
  window.addEventListener("resize", clamp);
  return () => window.removeEventListener("resize", clamp);
}, []);
```

## 包声明

`dsh-mindmap/package.json`：

```json
"dsh": {
  "bundle": { "patch": "./cordis.patch.yml" },
  "client": {
    "inject": [
      "@deepseek-ai/dsh-client-runtime",
      "@deepseek-ai/dsh-client-ui-layout"
    ],
    "platform": "web",
    "immediately": true
  }
}
```

## 插件自己记下的失败路径

原注释（`client.js:3119-3124`）与 `docs/014`：

| 尝试 | 结果 |
|---|---|
| 挂 `details` 槽 | 该槽**被官方收回**，原生「工具详情」栏恢复，不能再用 |
| 挂 `shell.overlay` 做浮层 | 声明存在，但**实测不渲染**，弃用 |
| 借用 `better-sidebar` 的宿主层位置 | 它挂在 `conversation.chat.turnTail`；思路可借鉴，槽位不必照抄 |

这三条是本次落位设计里最贵的信息 —— 它们的来源是**先例的注释和 docs 目录**，
而不是文档。找先例时要优先挑带注释、带 `docs/` 的实现。
