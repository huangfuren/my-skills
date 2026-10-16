# 可复制骨架：给插件加一个左栏设置页

按此骨架新建或改造插件，得到：设置弹窗左栏一个条目 + 一页能真正读写自己配置的界面 +
跨三代宿主的入口降级。示例插件名统一用 `my-plugin`。

## 1. 目录与 `package.json`

```
my-plugin/
├── index.js          # 宿主半：工具 + settings 命名空间
├── client.js         # 客户端半：设置页插槽注册
├── cordis.patch.yml  # 需要在启动时装配时必须（见下）
└── package.json
```

```json
{
  "name": "my-plugin",
  "version": "0.1.0",
  "type": "module",
  "main": "index.js",
  "files": ["index.js", "client.js", "cordis.patch.yml"],
  "dsh": {
    "bundle": { "patch": "./cordis.patch.yml" },
    "client": {
      "inject": ["@deepseek-ai/dsh-client-runtime"],
      "platform": "web",
      "immediately": true
    }
  },
  "dependencies": { "@deepseek-ai/schemastery": "^3.18.1" },
  "engines": { "node": ">=22.19" }
}
```

可选：声明本插件对宿主发布版的兼容性（本机仅 `dsh-context` 声明了该字段）：

```json
"dsh": {
  "compatibility": { "dshReleases": { "0.1.7-rc.2": "compatible", "0.2.0-rc.2": "compatible" } }
}
```

- `dsh.client` 段是**客户端半被加载的前提**；没有它，注册再多插槽也不会出现。
- `dsh.client.inject` 是「需要随插件预加载的包」，**不是**服务名清单。
- `immediately: true` 让客户端半在启动时就装入，而不是等到某个页面才加载。
- 没有宿主路由/工具时可以省掉 `bundle.patch`；有则必须在 `package.json` 声明，
  否则要手工在 profile 的 `cordis.patch.yml` 里 insert。

## 2. 宿主半 `index.js`

```js
import Schema from '@deepseek-ai/schemastery';
import { defineTool } from '@deepseek-ai/dsh-tools';

export const name = 'my-plugin';
// 顶层 inject 只列**确定存在**的服务；settings 用嵌套 inject 可选接入
export const inject = ['tools', 'systemPrompt'];

export const SETTINGS_NAMESPACE = 'my-plugin';

// 每个要在设置页里读写的字段都必须 .volatile()（0.1.7+ 门禁）
export const Config = Schema.object({
  lineStyle: Schema.union(['curve', 'elbow']).default('elbow').volatile()
    .description('Connector line style.'),
  panelWidth: Schema.number().default(42).volatile()
    .description('Panel width as a percentage of the viewport (20-80).'),
});

const entryConfig = () => ({ lineStyle: 'elbow', panelWidth: 42 });

export function apply(ctx) {
  let activeConfig = () => entryConfig();

  ctx.inject(['settings'], (sctx) => {
    const settings = sctx.settings;
    const scope = typeof settings.register === 'function'
      ? settings.register(SETTINGS_NAMESPACE, Config, { base: entryConfig() })   // ≤ 0.1.5
      : null;                                                                    // ≥ 0.1.7

    const descriptorOf = () => settings.describe?.()?.find((e) => e?.ns === SETTINGS_NAMESPACE);
    const current = (d = scope ? undefined : descriptorOf()) =>
      scope?.get() ?? d?.value ?? entryConfig();

    activeConfig = () => current();
    sctx.effect(() => () => { activeConfig = () => entryConfig(); });
  });

  // 工具执行时读「活值」，不要读入口值
  ctx.tools.register(defineTool({
    name: 'my_plugin_do',
    description: 'Do something using the plugin settings.',
    parameters: {},
    output: {
      schema: { type: 'string' },
      // render 必须返回 ContentBlock[]，返回裸字符串会写坏 tool/result 事件
      render: (_args, value) => [{ type: 'text', text: String(value) }],
    },
    async execute() {
      return JSON.stringify({ ok: true, config: activeConfig() });
    },
  }));
}
```

## 3. 客户端半 `client.js`

### 3.1 外壳与导出形状

本机既有插件用的形状（`vm` 载入浏览器包）：

```js
(function () {
  var module = { exports: {} };
  var exports = module.exports;
  Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

  // 只 inject 确定存在的服务。名单上任一缺席都会让 fiber 永远停在 INACTIVE。
  const inject = ['slots'];

  function apply(ctx) { /* … */ }

  exports.apply = apply;
  exports.inject = inject;
  return module.exports;
})();
```

官方包用 ESM 写法（`export function apply` / `export const inject`），两者等价，
按你的构建方式选一种。

### 3.2 拿 settings 服务

```js
function serviceOf(name) {
  if (typeof ctx.get !== 'function') return null;
  try { return ctx.get(name) ?? null; } catch { return null; }
}
function isSettingsApi(v) {
  return Boolean(v) && typeof v.describe === 'function' && typeof v.update === 'function';
}
function settingsApiOf() {
  const remote = serviceOf('remote.settings');           // 必须整名，不能 ctx.remote.settings
  if (isSettingsApi(remote)) return { kind: 'remote', settings: remote };
  try {
    const s = serviceOf('connection')?.api?.settings;
    if (isSettingsApi(s)) return { kind: 'connection', settings: s };
  } catch { /* 守卫拒绝 → 等同服务缺失 */ }
  return null;                                           // 服务可能晚到，每次读写前重查
}
```

### 3.3 设置页组件 + 插槽注册

```js
const h = react.createElement;
const NS = 'my-plugin';
const S = {
  wrap:  { display: 'flex', flexDirection: 'column', gap: '12px', padding: '16px', maxWidth: '480px' },
  group: { display: 'flex', flexDirection: 'column', gap: '14px', padding: '14px', borderRadius: '12px',
           border: '1px solid var(--dsw-alias-border-l2)', background: 'var(--dsw-alias-bg-layer-3)' },
  title: { fontSize: '13px', fontWeight: 600, color: 'var(--dsw-alias-label-primary)', margin: '4px 0 0' },
  row:   { display: 'flex', alignItems: 'center', gap: '12px', fontSize: '13px' },
  label: { flex: '1 1 auto', color: 'var(--dsw-alias-label-secondary)' },
  input: { width: '72px', padding: '4px 8px', borderRadius: '6px', font: 'inherit', fontSize: '13px',
           border: '1px solid var(--dsw-alias-border-l2)',
           background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)' },
  hint:  { color: 'var(--dsw-alias-label-tertiary)', fontSize: '12px', margin: 0 },
  error: { color: 'var(--dsw-alias-label-error)', fontSize: '12px', margin: 0 },
};

function SettingsPanel(props) {
  const { close, myFace } = props;              // close 是外壳给的能力；myFace 是自己的 inject 面
  const [state, setState] = react.useState(null);

  // 服务晚到：每次进入重查，用 effect 卸载时置位避免 setState-after-unmount
  react.useEffect(() => {
    let alive = true;
    (async () => {
      const value = await myFace.readSettings().catch(() => null);
      if (alive) setState(value ?? {});
    })();
    return () => { alive = false; };
  }, [myFace]);

  if (state === null) return h('div', { style: S.wrap }, h('p', { style: S.hint }, '正在读取设置…'));

  const setField = async (key, value) => {
    setState((s) => ({ ...s, [key]: value }));
    try { await myFace.updateSettings({ [key]: value }); } catch (e) { /* 展示错误，别吞 */ }
  };

  return h('div', { style: S.wrap }, [
    h('p', { key: 't', style: S.title }, '外观'),
    h('div', { key: 'g', style: S.group }, [
      h('div', { key: 'w', style: S.row }, [
        h('span', { style: S.label }, '面板宽度（%）'),
        h('input', { type: 'number', style: S.input,
                     value: String(state.panelWidth ?? 42),
                     onChange: (e) => setField('panelWidth', Number(e.target.value)) }),
      ]),
    ]),
    h('p', { key: 'h', style: S.hint }, '改动即时生效。'),
  ]);
}

// ── 候选插槽降级（详见 references/slot-fallback-adapter.md）──────────────
function registerSettingsEntry(ctx, face) {
  const candidates = [
    { name: 'settings.section', kind: 'list', scope: 'root',
      options: { name: 'settings.section', id: NS, order: 16, label: 'My Plugin' },
      component: () => h(SettingsPanel, { myFace: face }) },
    { name: 'settings.plugins.tab', kind: 'list', scope: 'root',
      options: { name: 'settings.plugins.tab', id: NS, order: 100, label: 'My Plugin' },
      component: () => h(SettingsPanel, { myFace: face }) },
    { name: 'settings.plugin.item', kind: 'keyed',
      options: { name: 'settings.plugin.item', key: NS, inject: () => ({ myFace: face }) },
      component: SettingsPanel },
  ];

  if (typeof ctx.slots.spec !== 'function') {                 // 无探测能力的老宿主
    for (const c of candidates.slice(1)) {
      ctx.slots.inject(c.name, () => ctx.slots.register(c.options, c.component));
    }
    return;
  }

  ctx.effect(() => {
    const available = new Map();
    const waits = [];
    let active, unregister, queued = false, stopped = false;

    const reconcile = () => {
      if (stopped || queued) return;
      queued = true;
      queueMicrotask(() => {
        queued = false;
        if (stopped) return;
        const next = candidates.map((c) => available.get(c.name)).find(Boolean);
        if (next === active) return;
        unregister?.(); unregister = undefined; active = undefined;
        if (next) {
          try { unregister = ctx.slots.register(next.options, next.component); active = next; }
          catch (e) { if (e?.code !== 'INACTIVE_EFFECT') throw e; stop(); }
        }
      });
    };
    const stop = () => {
      if (stopped) return;
      stopped = true;
      const d = unregister; unregister = undefined; active = undefined; d?.();
      for (const x of waits.reverse()) x?.();
      available.clear();
    };

    try {
      for (const c of candidates) {
        waits.push(ctx.slots.inject(c.name, () => {
          const spec = ctx.slots.spec(c.name);
          if (spec?.kind !== c.kind || (c.scope && spec.scope !== c.scope)) return;
          const lifetime = { ...c };
          available.set(c.name, lifetime);
          reconcile();
          return () => {
            if (available.get(c.name) === lifetime) available.delete(c.name);
            reconcile();
          };
        }));
      }
    } catch (e) { stop(); throw e; }
    return stop;
  }, 'my-plugin: settings navigation');
}
```

## 4. 落地顺序

1. 宿主半先导出 `Config`、字段全标 `.volatile()`，注册命名空间，跑通「工具能读到活值」
2. `package.json` 补 `dsh.client` 段，客户端半先做一个只读面板，确认左栏出现条目
3. 再接读写（`describe` / `update` + `revision`），确认改完重启/切页仍在
4. 最后换到候选降级适配器，回老宿主验证卡片仍出现
5. 用 `dsh-client-slot-placement` 的清单核对视觉与落位

## 5. 常见偏差

| 偏差 | 后果 |
|---|---|
| `Config` 没导出、或写成 `export default` | 宿主发现不到 schema，设置页无数据 |
| 字段漏 `.volatile()` | `describe` 读回空、写入被拒（0.1.7+） |
| 只写客户端半 | 页面出现但读写全失败 |
| 只写宿主半 | 有自动页，但没有你想要的整页布局 |
| 客户端半 `inject` 里写了不确定存在的服务 | fiber 停在 `INACTIVE`，插件完全不加载 |
| `describe` 有参无参写死一种 | 在另一代宿主上直接抛错 |
| 写入不带 `revision` | 并发写会互相覆盖 |
