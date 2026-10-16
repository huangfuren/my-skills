---
name: dsh-multi-source-config
description: >-
  Use when a DSH plugin must talk to several instances of the same service
  (production / staging Grafana or JumpServer), i.e. a named source list with one
  default, a per-source credential, and a one-time migration from the old
  single-source config — or when such a feature is misbehaving (a removed source
  comes back after restart, a token rotation silently reverts elsewhere, a save
  wipes every stored source). Covers the SourceConfig/Config schema, id-derived
  credential references, the revision-checked whole-array mutate, staged
  credential references for safe rotation, orphan-credential cleanup rules under
  rejected vs unknown write outcomes, tool-side source resolution by name with
  approval binding, and the UI contract for source cards.
license: MIT
compatibility: >-
  DSH plugins with a host half (index.js) and a client half (client.js), using
  the settings + credentials remote facades. Verified against dsh 0.2.0-rc.2
  desktop and dsh-api-gateway; cross-checked against dsh-jumpserver 0.12.0 and
  dsh-grafana 0.18.1 (both verified working on the desktop profile).
---

# DSH 插件多源站配置

一句话结论：**多源站 = 一个数组配置项 + 一个默认源指针 + 每源独立凭据引用**，
再配一条「按名称选源」的工具侧解析规则。难点不在 CRUD，而在**凭据与配置是两处存储、
写不原子**——所有真正的坑都在这个缝里。

两个已验证实现的对照：`dsh-jumpserver` 0.12.0（双凭据 AccessKey 对）与
`dsh-grafana` 0.18.1（单令牌）。它们在**删除源站时是否回收凭据**上刻意取了相反的立场，
两者都能自证其立场，见 §5。

> **references/**：[source-model.md](references/source-model.md)（schema / id 与 ref 派生 / 写前校验 / 迁移全文）、
> [save-orchestration.md](references/save-orchestration.md)（门面与 `unwrap` / 凭据写入策略 / 孤儿清理三态 / 回读合并 / UI 契约）、
> [skeleton.md](references/skeleton.md)（可复制骨架 + 占位符替换表 + 落地顺序 5 步 + 偏差表）。

## 一、数据模型

```js
// 单个源站
const SourceConfig = Schema.object({
  id:      Schema.string().default(""),   // 系统生成、只读、全局唯一、稳定
  name:    Schema.string().default(""),   // 必填、唯一；工具按它选源
  baseUrl: Schema.string().default(""),   // 该源站地址
  akRef:   Schema.string().default(""),   // 该源站凭据引用；空则由 id 派生
  skRef:   Schema.string().default(""),   // 同上（单凭据服务只需一个）
});

export const Config = Schema.object({
  sources:        Schema.array(SourceConfig).default([]).volatile(),
  defaultSource:  Schema.string().default("").volatile(),   // 存的是源站 **id**
  legacyMigrated: Schema.boolean().default(false).volatile(),  // 迁移护盾，别省
  // 旧版单源字段：只供迁移与「尚无 sources」时的隐式默认源
  baseUrl: Schema.string().default("").volatile(),
  akRef:   Schema.string().default(LEGACY_AK_REF),
  skRef:   Schema.string().default(LEGACY_SK_REF),
});
```

> `volatile()` 是 0.1.7+ 的读写门禁，细节见配套 skill `dsh-settings-page`。
> `defaultSource` 存 **id 而不是 name**：改名不该改变默认指向。

## 二、三条不变量

| # | 不变量 | 理由 |
|---|---|---|
| 1 | **id 是身份，name 是别名**：id 系统生成、只读、全局唯一；name 用户可改；两者都要能选源（优先 name、其次 id） | 工具调用里人类写的是 name；持久化引用必须锚在不变量上 |
| 2 | **凭据引用由 id 派生**：`REF_PREFIX + clean(id)`，`clean = s.replace(/[^A-Za-z0-9_]/g,"").slice(0,64)` | 改名不动密钥；引用还必须是合法标识符 `^[A-Za-z_][A-Za-z0-9_]*$` |
| 3 | **任何写入都是整表替换**：一次 `mutate` 里 `{op:"set", path:["sources"], value: normalized}` | `set` 对路径整体赋值、**不按下标合并**；多个 op 在同一事务里一起落地 |

id 生成用三段降级，别忘了老运行时：

```js
crypto.randomUUID()
  ?? 由 crypto.getRandomValues(16 字节) 手工拼 v4
  ?? `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,10)}`
```

## 三、旧单源迁移（四条缺一不可）

```js
// 迁移前提：护盾未置 且 sources 为空 且（旧 URL 或旧凭据任一存在）
if (current.legacyMigrated === true) return;
if (Array.isArray(current.sources) && current.sources.length > 0) return;
const [ak, sk] = await Promise.all([credentials.resolve(akRef), credentials.resolve(skRef)]);
if (!legacyUrl && !ak?.value && !sk?.value) return;

const id = generateSourceId();
await updateConfig({
  sources: [{ id, name: DEFAULT_SOURCE_NAME, baseUrl: legacyUrl, akRef, skRef }],
  defaultSource: id,
  baseUrl: "",              // 旧 URL 已进入 sources[]，清空
  legacyMigrated: true,     // ← 护盾
}, descriptor);
```

1. **沿用旧 ref**：迁移来的源站显式带上旧 `akRef`/`skRef`，**密钥零搬运**（否则用户要重新输入凭据）。
2. **置 `legacyMigrated: true`**：否则用户删掉这个源站后，下次启动会因为「sources 为空 + 旧配置还在」被**复活**。
3. **等描述符出现再迁**：`settings.describe()` 只返回**已进入运行态**的条目，而迁移回调在 apply 同步阶段就可能跑；此时写入会报 `no longer configurable`。做法是有限次重试、不阻塞启动、插件卸载立即停：

```js
const waitForDescriptor = async () => {
  if (scope) return undefined;                     // 旧宿主有 register/scope，不需要
  for (let i = 0; i < MAX_ATTEMPTS; i += 1) {
    if (disposed) return null;
    const d = descriptorOf();
    if (d) return d;
    await new Promise((r) => { const t = setTimeout(r, RETRY_MS); t.unref?.(); });
  }
  return null;
};
```

4. **迁移写入带 revision**：若用户已在设置页保存过自己的源站，宿主会以版本冲突拒绝迁移；**用户配置优先**，这是期望行为而不是失败。迁移全文（含失败日志的 `reason=` 结构化分级）见 [references/source-model.md](references/source-model.md)。

## 四、写入侧的三条守卫（缺一条就会整表覆盖）

| 守卫 | 触发 | 不做的后果 |
|---|---|---|
| **未加载不得写** | `!loaded` 时点新增/保存 → 直接报错返回 | 把「只有这张新卡」的列表写回去，**抹掉全部已存源站** |
| **`unconfirmed` 读不是权威** | 信封 `ok:true` 但载荷畸形（没有 `namespaces`、没有本插件命名空间、`sources` 不是数组、有行被丢弃） | 拿它清空基线 → 下一次保存**不带修订号**整表覆盖 |
| **`revision` 是唯一真正的并发保护** | 每次写入回传最近一次 `describe` 读到的 `revision` | 单事务的原子性救不了「基于旧列表的整表替换」，陈旧页面照样覆盖新配置 |

```js
// mutate 第三参在 arity 上不可省：网关按声明参数表严格校验
// dsh-api-gateway: values.length !== descriptor.parameters.length
//   → `client api: <endpoint> expected N argument(s), got M`
unwrap(await settings.mutate(NS, ops, Number.isInteger(revision) ? revision : void 0));
```

## 五、保存编排：先校验 → 再写凭据 → 最后写配置

顺序不能反。若先写凭据再校验，非法输入会留下**密钥已落库但配置没写**的半保存状态。
（门面契约、`unwrap` 的 `remoteRejected` 标记、三条流程的完整实现见
[references/save-orchestration.md](references/save-orchestration.md)。）

```js
validateSources(nextSources, T);                    // ① 全部校验先跑完
for (const s of tokenWrites) await face.setToken(s.ref, s.value);   // ② 凭据
await face.writeSources(nextSources, nextDefault, revision);        // ③ 配置（整表 + 默认源）
```

### 5.1 凭据写入的两种安全策略

| 策略 | 做法 | 适用场景 |
|---|---|---|
| **A 派生引用直写** | 新源站的凭据直接写它自己的派生 ref；保存失败且宿主**明确拒绝**时回收该 ref | 该 ref 本次才第一次写入，无人在用 |
| **B 暂存引用切换** | 新值先写 `ref_PENDING_<本次随机>`，再用一次带 revision 的配置写入把指针切过去 | **覆盖一个正在生效的凭据** |

**为什么 B 是必需的**：两步写入无法保证一致——先覆盖原 ref，配置写失败就留下「新令牌 + 旧地址」；
把顺序换成先写配置，又变成**把旧令牌发往新地址**。暂存引用让"切换"成为一次原子配置写入。

```js
// 每次保存生成全新随机后缀。固定 `_PENDING` 键会被另一页或本页下一次保存复用——
// 要么覆盖别人已生效的凭证，要么被一条旧的「重试清理」提示删掉正在生效的令牌。
function stagedTokenRef(ref) {
  return `${ref}_PENDING_${generateSourceId().replace(/[^A-Za-z0-9_]/g, "")}`;
}
```

### 5.2 孤儿凭据清理：三种结果，只有一种能删

`unwrap()` 必须在宿主**明确拒绝**时给错误打标记，调用方据此决策：

```js
function unwrap(res, what) {
  if (res && res.ok === true) return res.value;
  const error = new Error(res?.error?.message || `${what} failed`);
  if (res && res.ok === false) error.remoteRejected = true;   // ← 只有这一种算「确定没写入」
  throw error;
}
```

| 写配置的结果 | 能否删暂存凭据 | 理由 |
|---|---|---|
| 宿主**明确拒绝**（`ok:false`） | ✅ 能，逐个回收 | 确定没提交，暂存的是孤儿 |
| 结果**未知**（RPC 断开、传输异常） | ❌ **绝不能删** | 宿主可能已经提交，删了就毁掉生效凭据 |
| 成功 | 按 §5.3 的策略 | — |

### 5.3 删除源站：配置先落地，再清凭据

```js
const nextSources = stored.filter((s) => s.id !== id).map(storedRow);
const nextDefault = pickDefault(nextSources, defaultSource === id ? "" : defaultSource);
await face.writeSources(nextSources, nextDefault, revision);       // 配置先生效
const inUse = new Set(nextSources.flatMap((s) => [s.akRef, s.skRef]));
for (const ref of [target.akRef || akRefForId(id), target.skRef || skRefForId(id)]) {
  if (inUse.has(ref)) continue;                                   // ← 还被别的源站引用就别删
  try { await face.unsetSecret(ref); } catch (e) { note(...); }   // 失败只提示，不回滚已生效的移除
}
```

**两家在这里刻意相反，选择依据是「能否证明该凭据没有别的引用」**：

| | 立场 | 论证 |
|---|---|---|
| `dsh-jumpserver` | **主动清理**（跳过 `inUse` 的 ref） | 双凭据按 id 派生，天然一源一份 |
| `dsh-grafana` | **一律保留**，只把旧 ref 作为「保留提示」列给用户（`unsetToken` 直接抛 `SHARED_CREDENTIAL_CLEANUP_DISABLED`） | 凭证库可能**跨 profile 共用**，当前 `describe` 无法证明别的 profile 不再引用它；凭据只写不读，删了拿不回来 |

判据一句话：**证明不了没人用，就不要删。** 若选择保留，必须把保留项显式呈现给用户，否则会留下无声的凭据残留。

### 5.4 回读合并：已提交的令牌草稿必须清掉

```js
function mergeDrafts(described, drafts, committed, previousStored = []) {
  // 已提交且此后未被再次编辑的行 → 草稿清空；其它行保留用户正在编辑的内容
  const tokenDraft = submitted !== undefined && String(d.tokenDraft ?? "").trim() === submitted
    ? ""                      // ← 比较必须 trim
    : (d.tokenDraft ?? "");
  // 存储里缺席的草稿：只有「从未持久化过」的新行才保留
  for (const d of drafts) if (!describedIds.has(d.id) && !storedIds.has(d.id)) merged.push({ ...d });
}
```

- **不清会怎样**：该行一直算脏，下一次保存会把**同一枚令牌再写一遍**，把别处的令牌轮换撤销掉。
- **不 trim 会怎样**：`"  tok  "` 这类带空白的输入保存后仍算脏，同样触发上面的重写。
- **「是否曾持久化」只能由上次存储基线判断**，不能由凭据状态推断——已保存的源站也可能根本没有凭据，或凭据状态读取失败。

### 5.5 写前统一校验（两家规则一致，照抄即可）

| 规则 | 值 |
|---|---|
| 源站数量 | `<= 50` |
| name | trim 后非空、`<= 100` 字符、**唯一**（trim 后精确匹配，大小写敏感） |
| baseUrl | 若填：`new URL` 可解析、协议 `http:`/`https:`、**无** user / password / query / hash |
| defaultSource | 空，或命中某个已存在的 id |
| id | 唯一，匹配 `^[A-Za-z0-9][A-Za-z0-9-]{0,127}$` |
| 凭据 ref | 匹配 `^[A-Za-z_][A-Za-z0-9_]*$` |

## 六、工具侧按源选路

```js
function resolveSource(arg) {
  const sources = effectiveSources();
  if (sources.length === 0) throw new Error("No <service> source is configured. Add one in Settings → <Plugin>.");
  const key = String(arg ?? "").trim();
  if (key) {
    const hit = sources.find((s) => s.name === key) ?? sources.find((s) => s.id === key);  // name 优先，其次 id
    if (hit) return hit;
    throw new Error(`Unknown source ${JSON.stringify(key)}. Configured: ${names}. Call <plugin>_sources to list them.`);
  }
  const def = sources.find((s) => s.id === defaultSourceId(sources));
  if (def) return def;
  throw new Error(`Multiple sources are configured (${names}) but none is the default and no source was specified. ...`);
}
```

- **默认源解析**：显式 `defaultSource` 命中则用它；否则**唯一源站即默认**；多源且无默认 → 报错要求显式指定（不要随便挑第一个）。
- **隐式旧源的回退要受护盾约束**：`sources` 为空且 `legacyMigrated !== true` 时才合成旧版单源；护盾已置则返回**空列表**——用户把源站全删了就是"没有源站"。
- 提供一个只读的 `<plugin>_sources` 工具，返回 `{ id, name, baseUrl, <secret>Configured: boolean }`——**只回布尔，绝不回显明文**。
- 用 `AsyncLocalStorage` 把解析结果传给下层 `api()`：几十个工具不必逐个改签名，并发调用之间也不会串号。

### 审批绑定（写操作必做）

审批与执行之间，另一个设置页可能改掉默认源。此时必须**拒绝写入**：

```js
const sourceStore = new AsyncLocalStorage();
const approvalBindings = new WeakMap();          // exec → { identity, name }

function sourceIdentity(src) {                   // 只含非敏感字段：id / URL / ref 名
  return `${src?.id ?? "legacy"}\u0000${src.baseUrl}\u0000${src.akRef}\u0000${src.skRef}`;
}
function resolveApprovedSource(arg, exec) {
  const resolved = resolveSource(arg);
  const bound = approvalBindings.get(exec);
  if (bound && bound.identity !== sourceIdentity(resolved))
    throw new Error(`The source this write was approved for has changed: approval named ${bound.name}, ` +
                    `the call now resolves to ${resolved.name}. Nothing was written — run the tool again.`);
  return resolved;
}
```

用户批准的是**审批文案里那一台**，不是执行时随手解析到的那一台。同样地，常驻工具调用的源站要经
`sourceStore.run({ source: src }, () => execute(...))` 绑定，避免并发串号。

## 七、UI 契约（源列表卡片）

- **卡片头部**：标题/描述 + 折叠箭头；徽标 `默认` / `未保存`；操作 `设为默认`（仅已落库行）/ `移除`
- **每行**：名称输入 + UID 只读回显（`UID（自动生成、全球唯一、不可修改）`）+ URL 输入 + 每个凭据一个 password 输入（带 `已配置/未配置` 徽标）
- **凭据输入框掩码三态**：已配置 且 未聚焦 且 无草稿 → 显示掩码（例：28 个 `*`）；聚焦 → 空串（可输入新值）；输入时若以掩码开头则剥掉掩码前缀
- **「保存当前源站」只提交本行**：其它行以**存储值原样带上**（不动它们的草稿），本行用草稿值；新行追加到末尾
- **「设为默认」只对已落库行开放**：未落库的 id 会让宿主判定「多源无有效默认」，此后每次调用都必须显式传 `source`，而 UI 草稿仍在列表里，界面与运行时从此不一致。先保存，再设默认。
- **未落库的新行移除时只丢草稿**，不做远端写入
- 折叠外壳对齐官方 `PluginCard`：收起 `--dsw-alias-bg-layer-3`，展开 `--dsw-alias-bg-layer-2`

## 八、坑（Gotchas）

| 现象 | 根因 |
|---|---|
| 删掉的源站重启后又出现 | 迁移没置 `legacyMigrated: true`，隐式旧源被复活 |
| 保存后被别处的令牌轮换被撤销 | 已提交的令牌草稿没清（或比较未 trim）→ 下次保存重写旧令牌 |
| 另一页刚写的源站被整批覆盖 | 没回传 `revision`；或 `sources` 用了按下标合并而非整表替换 |
| 一次保存后全部源站丢失 | 读取失败/`unconfirmed`/未 `loaded` 时仍允许保存，用空基线整表写回 |
| 密钥已落库但配置没写 | 校验放在了凭据写入之后 |
| 删源站把别的源站在用的凭据删了 | 没做 `inUse` 集合过滤 |
| 结果未知时删了凭据，生效凭据被毁 | 把「RPC 异常」当成「宿主拒绝」的回滚信号 |
| 报 `client api: ... expected N argument(s), got M` | `mutate` 第三参被省略；arity 上不可省，无版本时也要显式传 `void 0` |
| 两个源站名一样 / 默认源指向不存在的 id | 写前没跑统一校验 |
| 写入打到了另一台 JumpServer | 没做审批绑定；审批后默认源被改，执行时静默换了目标 |
| 卡片一直显示"未保存" | 草稿比较用了原始字符串而非 trim 后的值 |

## 九、自检清单

- [ ] `sources` / `defaultSource` / `legacyMigrated` 三个字段都标了 `.volatile()`
- [ ] id 系统生成、只读、三段降级；凭据 ref 由 id 派生且通过标识符正则
- [ ] 迁移沿用旧 ref、置护盾、清旧 URL、带 `revision`、等描述符出现
- [ ] 写入顺序为 校验 → 凭据 → 配置；`mutate` 带 `revision`（无版本显式 `void 0`）
- [ ] 覆盖生效凭据时用了带随机后缀的暂存 ref，而不是固定 `_PENDING`
- [ ] `unwrap` 区分了「明确拒绝」与「结果未知」；只有前者触发回收
- [ ] 删除源站跳过仍被引用的 ref；选择保留时把保留项展示给用户
- [ ] 回读合并清掉了已提交的令牌草稿，且比较 trim
- [ ] `!loaded` / `unconfirmed` 两条守卫拦住了写入
- [ ] 工具按 name（其次 id）选源；无默认且多源时报错；`<plugin>_sources` 只回布尔
- [ ] 写操作做了审批绑定；常驻调用经 `AsyncLocalStorage` 绑定源站
- [ ] 未落库的行不能设为默认，移除时不触发远端写入

## 十、参考实现

路径前缀：已安装副本 `<dsh-home>\profiles\desktop\node_modules\`（**运行时事实**）；
本地检出 `<plugins-dir>\` 是旧版（jumpserver 0.11.0 / grafana 0.15.0），读代码先看已安装副本。

| 用途 | 位置 |
|---|---|
| 双凭据 schema / ID 与 ref 派生 / 写前校验 / 常量 | `dsh-jumpserver\index.js`（105–200、204–290） |
| 旧单源迁移（护盾 + 等描述符 + revision） | `dsh-jumpserver\index.js`（1100–1165） |
| 生效源站列表 / 默认源 / 按名解析 | `dsh-jumpserver\index.js`（1204–1250） |
| AsyncLocalStorage 绑定 + 审批绑定 | `dsh-jumpserver\index.js`（1167–1175、1290–1360） |
| 客户端纯函数（校验 / 脏行 / 草稿合并 / 掩码） | `dsh-jumpserver\client.js`（147–210） |
| 保存一行 / 移除 / 设为默认（含孤儿凭据回收） | `dsh-jumpserver\client.js`（332–450） |
| 凭据输入框掩码三态 / 源站卡片 | `dsh-jumpserver\client.js`（454–500） |
| 门面：`describe` 的 `unconfirmed` 判定 + `writeSources` 多 op | `dsh-jumpserver\client.js`（700–760） |
| **暂存引用轮换** `stagedTokenRef` / `tokenWritePlan` / `buildSavePlan` | `dsh-grafana\client.js`（276–312） |
| 回读合并清草稿 / 未落库不可设默认 / 删除后本地推进 | `dsh-grafana\client.js`（318–370） |
| 保存编排与「尝试过就不删」的注释 | `dsh-grafana\client.js`（514–545） |
| `mutate` 双 op 原子性与 arity 校验说明 | `dsh-grafana\client.js`（1016–1050） |

可复制的骨架（含占位符替换表、单↔双凭据删改清单、落地顺序、偏差表）见
[references/skeleton.md](references/skeleton.md)。

配套 skill：设置页入口本身（插槽选型、`order`、宿主半命名空间、volatile 双轨）见
`dsh-settings-page`；控件落位见 `dsh-client-slot-placement`；双半边骨架与客户端 bundle
构建链见 `dsh-plugin-dual-half-skeleton`；**凭据绝不下发浏览器**、由宿主半代读的写法见
`dsh-plugin-fetch-route`；宿主版本差异下的字段降级见 `dsh-harness-compat-gate`。

总览与索引见 `dsh-plugin-dev-guide`。
