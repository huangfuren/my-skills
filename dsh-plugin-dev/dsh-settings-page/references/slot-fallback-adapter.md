# 候选插槽降级适配器（跨宿主世代）

同一个落点在不同宿主世代用了不同槽名。写死一个就会在换版本后「入口凭空消失」。
本文给出可复用的适配器——原型是 `dsh-grafana` 0.18.1 `client.js` 的 `registerSettingsEntry`
（857–935 行），下面逐段解读。

## 1. 槽名谱系

| 槽名 | `kind` | 世代 | 落点 |
|---|---|---|---|
| `settings.section` | `list` / root | 0.1.7+ | 设置弹窗左栏**独立导航项** |
| `settings.plugins.tab` | `list` / root | 0.1.7+ | 「内置插件」段内部的 **tab**（子槽，需该段先在位） |
| `settings.plugin.item` | `keyed` | 0.1.x 旧线 | 按 `key`（= settings 命名空间）派发的**配置卡片** |

> 0.2.0-rc.2 宿主的设置域契约里只有前两个。`settings.plugin.item` 仍然出现在候选表里，
> 是为了让插件在旧宿主上继续有卡片——**不能因为新宿主永不渲染它就把旧卡片撤掉**。

## 2. 前置知识：三个 API 的确切语义

### `ctx.slots.spec(key)`

```ts
spec<K extends keyof SlotMap & string>(key: K): SlotSpec<SlotMap[K]> | undefined
```

**未声明时返回 `undefined`**，声明后返回 `{ kind, scope }`。
这是「这个槽在**当前宿主**里到底存不存在、形状对不对」的唯一权威判据。

### `ctx.slots.register(options, component)`

```ts
register(options, component): () => void      // 返回可撤销的 disposer
```

会抛错的三种情形（`ui-slots/src/index.ts:1203-1236`）：

| 情形 | 报错 |
|---|---|
| 槽未声明 | `slot "X" is not declared (a parent entry's children table must declare it)` |
| `list` 缺 `id` | `list slot "X" requires options.id` |
| 同 `id` + 同 `priority` 重复注册 | `list slot "X" already has an entry with id "..."` |
| `children` 里声明一个已被别人声明的子槽 | `slot "Y" is already declared (by ...)` |

第三条是适配器必须做**变化合并**的直接原因：同一轮内多次 `register` 会撞 `id` 而抛错。

### `ctx.slots.inject(key, cb)`

```ts
inject(key, cb: () => SlotInjectionEffect): () => void
```

来自 `ui-renderer/src/client/registry.ts:209`，注释原文要点：

- **「Install an effect for each declaration lifetime of a slot.」**
  `cb` 在**声明已存在时同步执行**；否则在声明提交后、于 `register()` 调用内执行。
- **「Collapse disposes the effect and a later declaration runs it again.」**
  声明撤销 → 执行 `cb` 返回的 disposer；之后再声明 → **`cb` 再跑一次**。
- 声明生命周期是一个**嵌套 cordis effect**：`cb` 若是 generator，同样具备事务性安装与逆序销毁。
- 控制器属于**调用方 fiber**：插件卸载会取消等待并移除已生效的贡献。
- 返回值是幂等 disposer。

一句话：`inject` 是「**等这个槽被声明**」的订阅，而不是「一次性注册」。

## 3. 适配器全文

```js
function registerSettingsEntry(ctx, face) {
  const NS = "my-plugin";
  const candidates = [
    {
      name: "settings.section", kind: "list", scope: "root",
      options: { name: "settings.section", id: NS, order: 16, label: "MyPlugin" },
      component: () => react.createElement(MyCard, { face, defaultOpen: true }),
    },
    {
      name: "settings.plugins.tab", kind: "list", scope: "root",
      options: { name: "settings.plugins.tab", id: NS, order: 100, label: "MyPlugin" },
      component: () => react.createElement(MyCard, { face }),
    },
    {
      name: "settings.plugin.item", kind: "keyed",
      options: { name: "settings.plugin.item", key: NS, inject: () => ({ card: face }) },
      component: MyCard,
    },
  ];

  // ── 无声明探测能力的老宿主：保持原来的双代注册 ─────────────────────
  // 不能把未知槽当成可用入口，更不能因一个永不渲染的新槽而撤掉原有卡片。
  if (typeof ctx.slots.spec !== "function") {
    for (const c of candidates.slice(1)) {         // 跳过首选（老宿主没有 settings.section）
      ctx.slots.inject(c.name, () => ctx.slots.register(c.options, c.component));
    }
    return;
  }

  ctx.effect(() => {
    const available = new Map();   // name -> 该声明生命周期的标识对象
    const waits = [];
    let active;                    // 当前已注册的候选
    let unregister;
    let queued = false;
    let stopped = false;

    const reconcile = () => {
      if (stopped || queued) return;
      queued = true;
      // 在声明/撤销回调之外注册：避免把新入口挂到正在销毁的 effect 上；
      // 同时把同一轮槽位变化合并成一次切换，不制造重复入口（重复 id 会抛错）。
      queueMicrotask(() => {
        queued = false;
        if (stopped) return;
        const next = candidates.map((c) => available.get(c.name)).find(Boolean);
        if (next === active) return;
        unregister?.();
        unregister = undefined;
        active = undefined;
        if (next) {
          try {
            unregister = ctx.slots.register(next.options, next.component);
            active = next;
          } catch (error) {
            // Fiber 卸载可能先于本控制器的清理；待执行的微任务不得复活入口。
            if (error?.code !== "INACTIVE_EFFECT") throw error;
            stop();
          }
        }
      });
    };

    const stop = () => {
      if (stopped) return;
      stopped = true;
      const disposeActive = unregister;
      unregister = undefined;
      active = undefined;
      disposeActive?.();
      for (const dispose of waits.reverse()) dispose?.();   // 逆序撤销等待
      available.clear();
    };

    try {
      for (const c of candidates) {
        waits.push(ctx.slots.inject(c.name, () => {
          const spec = ctx.slots.spec(c.name);
          // kind 与 scope 都必须相符，才算「这个槽真的能用」
          if (spec?.kind !== c.kind || (c.scope && spec.scope !== c.scope)) return;
          // 每个声明生命周期用**新对象**标识；同 tick 撤销并重声明同名槽时也须重挂。
          const lifetime = { ...c };
          available.set(c.name, lifetime);
          reconcile();
          return () => {
            if (available.get(c.name) === lifetime) available.delete(c.name);
            reconcile();
          };
        }));
      }
    } catch (error) {
      stop();
      throw error;
    }
    return stop;
  }, "my-plugin: settings navigation");
}
```

## 4. 设计要点拆解

| 设计 | 为什么必须这样 |
|---|---|
| 候选表按**优先级**排列，`find(Boolean)` 取第一个可用 | 新宿主优先用 `settings.section`（整页），旧宿主自然回落到卡片 |
| 用 `spec()` 探测而不是「注册了就认为生效」 | 未声明的槽 `register` 会**抛错**；且「注册成功但永不渲染」无法区分 |
| `spec.kind !== c.kind` 直接判不可用 | 同名槽在不同世代可能换 `kind`（如 `list` ↔ `keyed`），形状不符就不能按原样注册 |
| `available` 存**生命周期对象**而不是布尔 | 同 tick 撤销 + 重声明时，旧的撤销回调不能误删新的可用标记 |
| `queueMicrotask` 合并 | 一轮内多次声明变化会连续触发 `reconcile`；不合并就会重复 `register`，撞 `id` 抛错 |
| 在回调**之外**注册 | 回调本身挂着「声明生命周期」的 effect，在里面注册会被随声明撤销一起带走 |
| 捕获 `error.code === "INACTIVE_EFFECT"` | 卸载竞态下 `register` 可能落在已失效的 effect 上；这类错误应静默停表，其余照常抛 |
| `ctx.effect(..., label)` 包裹 + 返回 `stop` | 插件卸载时一次性撤销全部等待与已生效入口 |
| 老宿主分支**注册全部备选**（`slice(1)`） | 没有探测能力时只能「都摆上去」，由各自宿主消费；撤掉任何一个都会真的丢入口 |
| 一个组件、多种包装 | 同一份 UI 在三代里都渲染；差异只在 `options.inject` 的形状（keyed 走 `inject`，list 走组件 props） |

## 5. 自检

- [ ] 每个候选都写了 `kind` **和** `scope`，且与官方契约一致
- [ ] `settings.section` / `settings.plugins.tab` 的 `options.id` 是稳定标识（通常用命名空间名）
- [ ] `settings.plugin.item` 的 `options.key` = 宿主端 settings 命名空间名
- [ ] 老宿主分支保留 `slice(1)`（不要把首选也算上）
- [ ] `reconcile` 走微任务合并，且 `next === active` 时早退
- [ ] 捕获 `INACTIVE_EFFECT`，其余错误照抛（静默吞错会掩盖真实故障）
- [ ] `inject` 的每个 disposer 都进了 `waits`，`stop` 里逆序撤销
- [ ] 整个适配器包在 `ctx.effect` 内
