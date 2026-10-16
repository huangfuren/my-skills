# settings 命名空间：宿主半注册与客户端半读写

自定义设置页能跑起来 = **宿主半建命名空间** + **客户端半读写它**。本文是这两半的完整契约，
证据取自 `dsh-grafana` 0.18.1、`dsh-mindmap` 0.17.0 与宿主源码
`deepseek-harness-master\packages\settings\settings\src\index.ts`。

## 0. 数据模型

一个插件的配置有三层，`describe()` 的 `value` 是它们**解析后**的结果：

```
schema 默认值  →  composition base（profile 的 patch 基线）  →  user 层（用户写入的覆盖）
                        ↑ base                                    ↑ user（字段出现在这里 = 被用户改过）
```

- `revision`：该条目原始配置的**单调版本号**。写入时带上它 = 乐观并发检查。
- `secrets`：schema 声明为密钥的槽位，只回传「是否已设置」，**值永不过线**。
- `autoGenerate`：**「没有自定义页面时，UI 是否可自动生成一页」**（见 §3）。

## 1. 宿主半：注册命名空间

### 1.1 先导出 `Config`

```js
export const Config = Schema.object({
  defaultPanelWidth: Schema.number().default(42).volatile(),
  lineStyle: Schema.union(["curve", "elbow"]).default("elbow").volatile(),
});
```

0.1.7+ 的 loader 从**平铺导出的 `Config`** 发现 schema，settings 服务不再提供 `register`/`scope`。

### 1.2 双代注册（0.1.5 与 0.1.7+）

```js
ctx.inject(["settings"], (sctx) => {
  const settings = sctx.settings;
  const scope = typeof settings.register === "function"
    ? settings.register(NS, Config, { base: entryConfig, validate: validateConfig })
    : null;

  const descriptorOf = () => settings.describe?.()?.find?.((e) => e?.ns === NS);
  const currentConfig = (d = scope ? undefined : descriptorOf()) =>
    scope?.get() ?? d?.value ?? entryConfig;

  const updateConfig = (patch, d) => {
    validateConfig({ ...currentConfig(d), ...patch });          // 写入前先自校验
    const revision = Number.isInteger(d?.revision) ? d.revision : undefined;
    if (typeof settings.update === "function") return settings.update(NS, patch, revision);
    if (typeof scope?.update === "function") return scope.update(patch);
    throw new Error("Settings service does not support update or legacy scope.update.");
  };

  activeConfig = () => currentConfig();
  sctx.effect(() => () => { activeConfig = () => entryConfig; });   // 卸载必须复位
});
```

| 世代 | 服务面 | 读 | 写 |
|---|---|---|---|
| ≤ 0.1.5 | `register(ns, Schema, {base})` 返回 scope | `scope.get()` | `scope.update(patch)` |
| ≥ 0.1.7 | 只有 `describe()` / `update(ns, patch, revision?)` | `describe().find(r => r.ns === NS).value` | `settings.update(NS, patch, revision)` |

**读时一律「活值优先」**：`scope.get()` → `descriptor.value` → `entryConfig`。入口值只作
「尚未出现在 describe 里」的兜底，不能当成当前值——用户改了设置而工具仍读入口值，是典型 bug。

### 1.3 `.volatile()` 门禁（0.1.7+ 最常踩的坑）

0.1.7 的存储体系引入 volatile 门禁：**schema 里没标 `.volatile()` 的字段，运行时
`describe` 读回空、`update`/`mutate` 写入被拒、legacy 导入也失败。**

- 要在设置页里**读写**的字段：必须 `.volatile()`
- 只在**启动时**生效、不需要运行时改的字段：可以不标

这条规则只影响「设置页能不能改它」，不影响工具执行时读到的值。

### 1.4 `configure`：自动页开关

```js
ctx.settings.configure({ auto: false }, ctx);   // 我不需要自动页
```

`autoGenerate` 缺省为 **`true`**（`this.presentations.get(entry.fiber)?.auto ?? true`），
语义是「**没有**自定义页面时，UI **可以**生成一页」。所以：

- 只导出 `Config`、不写客户端页 → 自动页兜底（`dsh-localsend` 走这条路）
- 有自定义页 → 两者不会重复；若不希望宿主再生成，显式 `{ auto: false }`

### 1.5 旧配置迁移

宿主升级时会把旧的顶层 `settings.yaml` 改名为 `settings.yaml.imported`，并由服务自身
`importLegacyDocument()` 按段导入。插件侧若还有自己的历史格式，实务做法是：

- 只在**新存储没有用户覆盖**时迁移（`descriptor.user` 为空）
- 不删除旧文件；迁移失败静默跳过，不影响工具与设置页继续工作
- 迁移前 `await sctx.root?.loader?.await?.()`，等所有 entry 加载完（`describe` 只含已加载的插件）

## 2. 客户端半：取服务并读写

### 2.1 取服务：三路降级

```js
function serviceOf(name) {
  if (typeof ctx.get !== "function") return null;
  try { return ctx.get(name) ?? null; } catch { return null; }   // 守卫异常 → 视为不可用
}
function isSettingsApi(v) {
  return Boolean(v) && typeof v.describe === "function" && typeof v.update === "function";
}
function settingsApiOf() {
  const remote = serviceOf("remote.settings");
  if (isSettingsApi(remote)) return { kind: "remote", settings: remote };
  try {
    const settings = serviceOf("connection")?.api?.settings;
    if (isSettingsApi(settings)) return { kind: "connection", settings };
  } catch { /* 守卫拒绝或连接形态异常，同样降级 */ }
  return null;
}
```

两个必须记住的点：

1. **必须整名 `ctx.get("remote.settings")`**。带点号的服务是独立服务名，写成
   `ctx.remote.settings` 会被守卫拒绝：`cannot get property "remote.settings" without inject`。
2. **不能在 `apply` 时把服务缓存下来**。客户端插件启动后服务才可能就绪；每次读写前重新查取，
   服务晚到也能恢复。

### 2.2 `describe` / `update` 的两代形状

| 世代 | 读 | 写 |
|---|---|---|
| `kind: "remote"` | `settings.describe()`（无参） | `settings.update(ns, patch, revision)`（位置参数） |
| `kind: "connection"` | `settings.describe({})` | `settings.update({ ns, patch })`（对象参数） |

`dsh-mindmap` 的判别方式是**函数元数**：

```js
if (api.kind === "remote" || api.settings.update.length !== 1) {
  await api.settings.update("mindmap", payload, undefined);
} else {
  await api.settings.update({ ns: "mindmap", patch: payload });
}
```

### 2.3 写之前先想清楚「谁覆盖谁」

一个真实的坑：引擎侧存在等价开关（如 `requireApproval: false`）时，设置页选的显式模式
必须**连带解除它**，否则保存后会被静默拉回：

```js
const payload = patch.approvalMode && patch.approvalMode !== "off"
  ? { ...patch, requireApproval: true }      // 显式选择优先于 legacy 开关
  : patch;
```

### 2.4 读到的形状

`describe()` 成功应答的 value 在远端是聚合格：

```js
{ writable, hasDocument, namespaces: [ { ns, schema, value, base, user, applies, secrets, revision } ] }
```

客户端常见的封装：

```js
function namespacesOf(value) {
  const list = value?.namespaces;
  return Array.isArray(list) ? list : [];      // 畸形值回退空数组
}
```

### 2.5 应答信封

远端应答必须**形状完整**才可判定：

```js
function unwrap(res, what) {
  if (res && typeof res === "object" && res.ok === true) return res.value;
  const message = res?.error?.message || `${what} failed`;
  if (res && typeof res === "object" && res.ok === false) throw remoteRejectedError(message);
  throw new Error(message);   // 信封缺失/畸形：结果未知，不能宣称「未提交」
}
```

判定口径：**只有明确写着 `ok:false` 才算宿主拒绝**；信封缺失或畸形一律按「结果未知」处理。

### 2.6 乐观并发

读到的 `descriptor.revision` 要缓存成基线，写时带上——否则「本页读到的基线」形同虚设，
陈旧页面仍能把别的页面刚写进去的内容整批覆盖：

```js
let describedRevision = null;
// 读：describedRevision = descriptor.revision
// 写：settings.update(NS, patch, Number.isInteger(expected) ? expected : describedRevision)
```

## 3. 字段速查

| 字段 | 含义 | 谁用 |
|---|---|---|
| `ns` | 命名空间键；`settings.plugin.item` 的 `key` 就是它 | 两侧 |
| `schema` | `schema.toJSON()` 序列化信封，`new Schema(json)` 可重建 | 客户端表单 |
| `value` | 默认值 → base → user 解析后的**实时值**（密钥已脱敏） | 客户端读 |
| `base` | composition 基线层（默认值已解析） | 诊断 |
| `user` | 用户写入的原始段；**字段出现在这里 = 被用户覆盖过** | 迁移判断 |
| `revision` | 单调版本号，写入时回传做并发检查 | 两侧 |
| `secrets` | 每个密钥槽的 `{ path, set }`，值永不过线 | 客户端表单 |
| `autoGenerate` | 没有自定义页时 UI 是否可自动生成一页 | 宿主 UI |
