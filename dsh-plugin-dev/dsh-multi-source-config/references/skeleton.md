# 骨架：可复制的多源站实现

本文是**可照抄的骨架**，把服务相关的部分缩成几个占位符。约定：
`<NS>` = 设置命名空间（如 `jumpserver`）、`<SVC>` = 服务名、`<PREFIX>` = 凭据引用前缀（如 `JUMPSERVER_AK_`）。
设置页入口本身（插槽选型、`order`、宿主半命名空间双代注册）见配套 skill `dsh-settings-page`，本文不重复。

## 1. 双半文件布局

```
<plugin>/
├─ index.js         宿主半：schema + 派生 + 校验 + 迁移 + 按名选源的工具 + 设置注册
├─ client.js        客户端半：门面 + 源站卡片 + 设置入口注册
└─ package.json
```

宿主半与客户端半各自持有一份**同式的纯函数**（`generateSourceId` / `refForId` / `storedRow` 的等价物）。
这是刻意的重复：客户端没有 Node 的 crypto 形态差异，且两侧都需要在「读到的行缺 ref」时自行补齐。

## 2. 宿主半骨架

### 2.1 schema

```js
const SourceConfig = Schema.object({
  id:      Schema.string().default("").description("System-generated, read-only, globally unique source UID."),
  name:    Schema.string().default("").description("Required, unique source name; used to select this source in tool calls."),
  baseUrl: Schema.string().default("").description("<SVC> base URL for this source."),
  akRef:   Schema.string().default("").description("Credential reference for this source's <SECRET_A>; derived from id when empty."),
  skRef:   Schema.string().default("").description("Credential reference for this source's <SECRET_B>; derived from id when empty."),
});

export const Config = Schema.object({
  sources:        Schema.array(SourceConfig).default([]).volatile()
                    .description("Configured <SVC> sources. Each has a unique name, a read-only UID, and its own base URL and credentials."),
  defaultSource:  Schema.string().default("").volatile()
                    .description("Id of the source used when a tool call omits the source argument."),
  legacyMigrated: Schema.boolean().default(false).volatile()
                    .description("Set once the legacy single-source configuration has been materialized into sources[]; prevents a removed source from being resurrected on the next start."),
  // 旧版单源字段：仅供迁移与「尚无 sources」时的隐式默认源
  baseUrl: Schema.string().default("").volatile(),
  akRef:   Schema.string().default("<LEGACY_AK_REF>"),
  skRef:   Schema.string().default("<LEGACY_SK_REF>"),
});
```

单凭据服务删掉 `skRef` 相关的一整列，其余不变。

### 2.2 volatile 读回

0.1.7+ 宿主把标了 `.volatile()` 的字段包成引用，**消费配置前必须解包**；旧宿主忽略该 meta，原样返回：

```js
const VOLATILE_WRITE = Symbol.for("cosmokit.volatile.write");
export function unwrapVolatile(value) {
  if (value !== null && typeof value === "object" && VOLATILE_WRITE in value && typeof value.get === "function")
    return unwrapVolatile(value.get());
  if (Array.isArray(value)) return value.map(unwrapVolatile);
  if (value !== null && typeof value === "object") {
    const out = {};
    for (const key of Object.keys(value)) out[key] = unwrapVolatile(value[key]);
    return out;
  }
  return value;
}
```

### 2.3 注册与配置访问（双代存活分支）

```js
export function apply(ctx, config = {}) {
  const entryConfig = unwrapVolatile({
    sources: [], defaultSource: "", baseUrl: "",
    akRef: LEGACY_AK_REF, skRef: LEGACY_SK_REF,
    ...config,
  });

  let activeConfig = () => entryConfig;                 // settings 可用前/卸载后的回退
  ctx.inject(["settings"], (sctx) => {
    const settings = sctx.settings;
    // 旧宿主（≤0.1.5）：register 返回 scope，schema 由 register 提交
    const scope = typeof settings.register === "function"
      ? settings.register(SETTINGS_NAMESPACE, Config, { base: entryConfig, validate: validateConfigValue })
      : null;
    // 新宿主（0.1.7+）：只有 describe/update，schema 由 loader 从导出的 Config 发现
    const descriptorOf = () => {
      try { return settings.describe?.()?.find?.((e) => e?.ns === SETTINGS_NAMESPACE); }
      catch { return undefined; }
    };
    const currentConfig = (descriptor = scope ? undefined : descriptorOf()) =>
      unwrapVolatile(scope?.get() ?? (descriptor?.value ? { ...entryConfig, ...descriptor.value } : entryConfig));
    const updateConfig = (patch, descriptor) => {
      validateConfigValue({ ...currentConfig(descriptor), ...patch });    // 写前自校验，与迁移共用
      const revision = Number.isInteger(descriptor?.revision) ? descriptor.revision : undefined;
      if (typeof settings.update === "function") return settings.update(SETTINGS_NAMESPACE, patch, revision);
      if (typeof scope?.update === "function") return scope.update(patch);
      throw new Error("Settings service does not support update.");
    };
    activeConfig = () => currentConfig();
    sctx.effect(() => () => { activeConfig = () => entryConfig; });       // 服务消失时回退

    startLegacyMigration({ sctx, scope, descriptorOf, currentConfig, updateConfig });   // §2.4
    registerTools({ ctx, activeConfig });                                 // §2.6
  });

  registerTools({ ctx, activeConfig });      // 即使 settings 不可用也要暴露工具（用入口配置）
}
```

> `registerTools` 只调一次：settings 到位时用增强后的 `activeConfig`，未到位时用入口配置。
> 若写成两边都调，工具会被注册两遍（宿主对重名工具的处理是报错或静默覆盖，别赌）。

### 2.4 启动迁移挂点

```js
function startLegacyMigration({ sctx, scope, descriptorOf, currentConfig, updateConfig }) {
  let disposed = false;
  sctx.effect(() => () => { disposed = true; });

  const waitForDescriptor = async () => {              // 见 SKILL.md §3
    if (scope) return undefined;                       // 旧宿主有 scope，不需要等
    for (let i = 0; i < MIGRATION_MAX_ATTEMPTS; i += 1) {
      if (disposed) return null;
      const d = descriptorOf();
      if (d) return d;
      await new Promise((r) => { const t = setTimeout(r, MIGRATION_RETRY_MS); t.unref?.(); });
    }
    return null;
  };

  (async () => {
    try {
      const descriptor = await waitForDescriptor();
      if (descriptor === null) return;                 // 拿不到：放弃，下次启动再试
      const current = currentConfig(descriptor);
      if (current.legacyMigrated === true) return;                                 // 护盾
      if (Array.isArray(current.sources) && current.sources.length > 0) return;    // 用户已有源站
      // 旧配置彻底为空则无需迁移（读凭据也可以省掉）
      const ak = await sctx.credentials.resolve(String(current.akRef || "").trim() || LEGACY_AK_REF);
      const legacyUrl = String(current.baseUrl ?? "").trim();
      if (!legacyUrl && !ak?.value) return;

      const id = generateSourceId();
      await updateConfig({
        sources: [{ id, name: DEFAULT_SOURCE_NAME, baseUrl: legacyUrl, akRef: current.akRef || LEGACY_AK_REF, skRef: current.skRef || LEGACY_SK_REF }],
        defaultSource: id, baseUrl: "", legacyMigrated: true,       // ← 旧 URL 进数组后清空
      }, descriptor);
      console.error(`[<NS>-migrate] sources materialized sources=1`);
    } catch (error) {
      migrationFailure("sources", error);              // 见 source-model.md §7
    }
  })();
}
```

### 2.5 生效源站列表与默认源

```js
function effectiveSources() { /* 见 source-model.md §8 */ }
function defaultSourceId(sources) { /* 见 source-model.md §8 */ }
```

### 2.6 工具侧按源选路

```js
const sourceStore = new AsyncLocalStorage();          // 常驻调用绑定源站，避免并发串号
const approvalBindings = new WeakMap();               // exec → { identity, name }

function resolveSource(arg) { /* 见 SKILL.md §6 */ }
function sourceIdentity(src) { /* 见 SKILL.md §6 */ }
function resolveApprovedSource(arg, exec) { /* 见 SKILL.md §6 */ }
```

工具描述里必须写清选源工作流，否则模型会猜源站名：

```
0. Every tool accepts an optional "source" argument. When more than one <SVC> is configured,
   call <NS>_sources first to list source names, then pass the one the user means. Omit "source"
   to use the default. Never guess a source name, and never run a write against a source the
   user did not clearly identify when several are configured.
```

## 3. 客户端半骨架

```js
exports.apply = apply;
exports.inject = inject;      // 顶层只列确定存在的服务；settings 走嵌套 ctx.inject

function apply(ctx) {
  ctx.inject(["settings"], () => {                    // 只要服务在，就注册设置入口
    const face = createFace(ctx);                     // §3.1
    registerSettingsEntry(ctx, face);                 // 见 dsh-settings-page：插槽选型 + 组件
  });
}

function createFace(ctx) { /* §1 of save-orchestration.md：describe / setSecret / unsetSecret / writeSources */ }
```

组件内部的状态与流程，见 `save-orchestration.md` §2–§7。要点是三个 state 各司其职：

| state | 含义 | 谁写 |
|---|---|---|
| `sources` | 界面行（含草稿字段） | 用户编辑 + 回读合并 |
| `stored` | 最近一次 `describe` 的权威基线（**无草稿字段**） | `describe` 成功时 |
| `revision` | 最近一次读到的版本号 | `describe` 成功时 |

## 4. 占位符替换表

| 占位符 | 含义 | jumpserver 实例 | grafana 实例 |
|---|---|---|---|
| `<NS>` | 设置命名空间 | `jumpserver` | `grafana` |
| `<SVC>` | 服务名（文案里） | JumpServer | Grafana |
| `<PREFIX>` / `<LEGACY_AK_REF>` | 凭据引用前缀 / 旧单源 ref | `JUMPSERVER_AK_` / `JUMPSERVER_ACCESS_KEY_ID` | `GRAFANA_` / `GRAFANA_API_TOKEN` |
| 凭据字段数 | 每源几枚凭据 | 2（AK + SK） | 1（token） |
| `MASK` | 掩码常量 | `"*".repeat(28)` | 同 |
| `MAX_SOURCES` | 源站上限 | 50 | 50 |
| `allowInsecureHttp` | 内网 HTTP 开关 | 有（内网部署） | 无（强制 HTTPS） |
| 删除凭据立场 | §4 表 | 主动清理 | 一律保留 |

### 单凭据 ↔ 双凭据 的替换清单

从双凭据改成单凭据，按顺序删：`SourceConfig.skRef` → `Config.skRef` → `skRefForId` → 校验里的 sk 分支
→ `storedRow` 的 `skRef` → 门面 `describe` 的 `refs` 里 `s.skRef` → 卡片里第二个 `secretField` 调用
→ 删除流程里 `inUse` 的 `s.skRef`。反向补齐同理。**别只改一半**：`storedRow` 与 `validateConfigValue`
是两侧共用的形状定义，漏改会在保存时才炸。

## 5. 落地顺序

1. **宿主半 schema + 派生 + 校验**（`source-model.md` §1–§6），先让 `Config` 能通过宿主校验。
2. **注册 + `activeConfig` 双代分支**（§2.3），确认旧宿主与新宿主都能读到配置。
3. **启动迁移**（§2.4），用「先造旧单源配置 → 重启 → 看设置页」验证一次；再手动删掉源站重启，
   确认**没有被复活**（护盾生效）。
4. **客户端门面 + 卡片**（`save-orchestration.md`），先只做读取与显示，再做保存。
5. **工具侧选路 + 审批绑定**（§2.6），最后接上业务工具。

## 6. 常见偏差

| 偏差 | 后果 | 正解 |
|---|---|---|
| `sources` 没标 `.volatile()` | 0.1.7+ 读回空、写入报 `Config field "..." is not volatile` | 三个字段都标 |
| 只有新宿主分支（无 `scope`） | 旧宿主上设置页完全不可用 | 保留 `settings.register` 存活分支 |
| `registerTools` 调两次 | 工具重名 | 只调一次，用函数式 `activeConfig` |
| 客户端复制了宿主半的 schema | 两份会漂移 | 只复制**纯函数**（id 生成 / ref 派生 / 形状），schema 不复制 |
| 迁移读配置时没 `unwrapVolatile` | 读到的是引用对象，`legacyMigrated === true` 永远不成立 | 消费前统一解包 |
| `updateConfig` 没接 `revision` | 并发下覆盖用户刚写的配置 | 从 `descriptor.revision` 传下去 |
| 客户端把 `akDraft` 写进配置 | 草稿字段落库 | 写前一律过 `storedRow` 收窄 |

配套 skill：`dsh-settings-page`（设置页入口与宿主半命名空间）、`dsh-client-slot-placement`（控件落位）。
