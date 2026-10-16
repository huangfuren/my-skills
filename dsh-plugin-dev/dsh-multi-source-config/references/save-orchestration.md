# 保存编排：门面、凭据写入策略、孤儿清理与回读合并

本文给出客户端半的完整实现，取自 `dsh-jumpserver` 0.12.0 与 `dsh-grafana` 0.18.1。
两家的分岔点集中在**是否回收凭据**（§4），其余骨架一致。

## 1. 门面：客户端与宿主之间唯一的边界

设置面板组件不直接碰 `remote.*`。中间隔一层门面（face），理由有两个：宿主版本差异被吸收在一处；
测试可以对门面打桩而不必起宿主。

```js
// remote.<ns> 之名由 ctx.get 读取，不要写 ctx.remote.<ns>：未 inject 的点号访问直接抛错，
// 而 ctx.get 在服务缺席时只返回 undefined。
function remoteNamespace(ctx, ns) {
  return typeof ctx.get === "function" ? ctx.get("remote." + ns) : undefined;
}

function requireNamespace(ctx, ns) {
  const api = remoteNamespace(ctx, ns);
  if (!api) throw new Error(HOST_UNSUPPORTED);   // 调用方要把它渲染成人话
  return api;
}

// remote.* 一律返回 { ok:true, value } 或 { ok:false, error:{ message } }。
// 失败必须抛出可读信息——静默降级成空数据会把「故障」伪装成「没配置」，用户会照着
// 空列表保存，一次抹掉全部源站。
function unwrap(res, what) {
  if (res && typeof res === "object" && res.ok === true) return res.value;
  const message = (res && typeof res === "object" && res.error && res.error.message) || (what + " failed");
  const error = new Error(message);
  // remoteRejected 是把两种失败分开的**唯一**信号，见 §4 三态表。
  if (res && typeof res === "object" && res.ok === false) error.remoteRejected = true;
  throw error;
}
```

### 门面暴露的四个方法

| 方法 | 参数 | 说明 |
|---|---|---|
| `describe()` | — | 读源站列表 + 默认源 + 凭据「是否已配置」+ `revision` + `unconfirmed` 标记 |
| `setSecret(ref, value)` | **位置参数** | 写凭据（仅写不读，`describe` 只回 `{configured, writable}`） |
| `unsetSecret(ref)` | 位置参数 | 删凭据（仅选择了「主动清理」立场的插件需要） |
| `writeSources(rows, defaultSource, expectedRevision)` | 位置参数 | 一次 `mutate` 写 `sources` + `defaultSource` + `legacyMigrated` |

`describe()` 必须自己完成「读回信封 → 判定权威性 → 合并凭据状态」三件事：

```js
const described = unwrap(await settings.describe(), "settings.describe");
const ns = settingsNamespacesOf(described).find((n) => n && n.ns === SETTINGS_NS);
const rawValue = ns && ns.value;
const value = rawValue && typeof rawValue === "object" && !Array.isArray(rawValue) ? rawValue : {};
const rawSources = Array.isArray(value.sources) ? value.sources : null;
const sources = rawSources === null ? [] : rawSources.map(normalizeSource).filter(Boolean);

// 信封 ok 但载荷缺失/畸形（没有 namespaces、没有本插件命名空间、sources 不是数组、
// 有行被丢弃）：这不是宿主契约内的合法配置。经降级得到的空列表**不是**「权威的空配置」，
// 不能当作写入基线——否则各调用点都会拿它整表回写。
const unconfirmed = !Array.isArray(described && described.namespaces)
  || !ns || rawSources === null || sources.length !== rawSources.length;
```

```js
// writeSources 的第三参决定并发保护强度
const revision = ns && Number.isInteger(ns.revision) ? ns.revision : null;
describedRevision = revision;   // 门面内部留存，供「本次会话没读到过版本」时兜底
```

`writeSources` 的实现要点（`set` 对路径整体赋值，两个 op 同事务）：

```js
writeSources: async (rows, defaultSource, expectedRevision) => {
  const settings = requireNamespace(ctx, "settings");
  const normalized = rows.map(storedRow);
  unwrap(await settings.mutate(SETTINGS_NS, [
    { op: "set", path: ["sources"], value: normalized },
    { op: "set", path: ["defaultSource"], value: defaultSource },
    { op: "set", path: ["legacyMigrated"], value: true },
  ], Number.isInteger(expectedRevision) ? expectedRevision
    : (Number.isInteger(describedRevision) ? describedRevision : void 0)), "settings.mutate");
},
```

**为什么必须一次 mutate 三个 op**：早期版本「先 `mutate` 清空、再 `update` 写新值」是两步写，
第二步失败时 `sources` 已被清空而新值未落地——存量用户的全部源站配置当场丢失。
`set` 是**整体替换**、不按下标合并，正是我们要的语义。

## 2. 保存的固定顺序

```js
validateSources(nextSources, T);                       // ① 全部校验先跑完
for (const { ref, value } of secretWrites) {           // ② 凭据
  attemptedRefs.push(ref);                             //    先记账，再写
  await face.setSecret(ref, value);
}
await face.writeSources(nextSources, nextDefault, revision);   // ③ 配置
```

顺序不可颠倒：先写凭据再校验，非法输入会留下**密钥已落库但配置没写**的半保存状态。
`attemptedRefs` 在写入**之前**入账——RPC 抛错也可能已经落到宿主侧，记账不能等 `await` 返回。

## 3. 凭据写入的两种策略

```js
// 单行（或整表）的凭据写入计划，纯函数。
function secretWritePlan(draft, stored) {
  const value = String(draft.secretDraft ?? "").trim();
  if (!value) return null;                                  // 无草稿 = 本次不动这枚凭据
  const canonical = draft.secretRef || secretRefForId(draft.id);
  if (!stored) return { ref: canonical, value, staged: false, replaces: null };
  // 已落库的源站一律走暂存：只改令牌同样可能被配置的版本检查拒绝，而凭据写入发生在
  // 检查之前——原地覆盖的话，被拒绝的那次保存也已经换掉了正在用的令牌。
  return { ref: stagedSecretRef(canonical), value, staged: true, replaces: canonical };
}

function stagedSecretRef(ref) {
  return `${ref}_PENDING_${generateSourceId().replace(/[^A-Za-z0-9_]/g, "")}`;
}
```

| 策略 | 何时用 | 回收 |
|---|---|---|
| **A 直写派生 ref** | 全新源站（`!stored`）——该 ref 本次才第一次写入 | 保存被**明确拒绝**时可回收 |
| **B 暂存 ref 切换** | 覆盖一个**已落库源站**的凭据 | 切换成功后旧 ref 按立场处理（§4） |

暂存后缀**每次保存都要重新随机**。固定写 `_PENDING` 的后果：

- 另一页（或本页的下一次保存）复用了同一个键 → **覆盖别人已生效的凭据**；
- 一条陈旧的「重试清理」提示认领了这个键 → **删掉正在生效的凭据**。

来源站与已落库源站的差别，就是「本次新写入」与「覆盖写」的差别：前者失败可回收，
后者**在写入那一刻原值就没了**，无从回滚。

## 4. 孤儿凭据清理：三种结果，只有一种能删

| 写配置的结果 | 能否删暂存凭据 | 理由 |
|---|---|---|
| 宿主**明确拒绝**（`ok:false`） | ✅ 能，逐个回收 | 确定没提交，暂存的是孤儿 |
| 结果**未知**（RPC 断开、传输异常） | ❌ **绝不能删** | 宿主可能已提交，删了就毁掉生效凭据 |
| 成功 | 按插件立场（下表） | — |

```js
try {
  await face.writeSources(nextSources, nextDefault, revision);
} catch (writeError) {
  rejected = !!(writeError && writeError.remoteRejected);   // 只有这一种算「确定没写入」
  if (rejected) {
    for (const ref of stagedRefs) {
      try { await face.unsetSecret(ref); }
      catch (cleanupError) { note(T.stagedCleanupFailed.replace("{ref}", ref) + messageOf(cleanupError)); }
    }
  }
  throw writeError;
}
```

### 成功之后：两家刻意相反的立场

| | 立场 | 实现 | 论证 |
|---|---|---|---|
| `dsh-jumpserver` | **主动清理** | 配置落地后算 `inUse` 集合，跳过仍被引用的 ref，其余 `unsetSecret` | 双凭据按 id 派生，天然一源一份；清理失败只提示，**不回滚**已生效的移除 |
| `dsh-grafana` | **一律保留** | `unsetToken: async () => { throw new Error("SHARED_CREDENTIAL_CLEANUP_DISABLED"); }` | 凭证库可能**跨 profile 共用**，当前 `describe` 无法证明别的 profile 不再引用它；凭据只写不读，删了拿不回来 |

选择判据一句话：**证明不了没人用，就不要删。** 若选保留，必须把保留项显式呈现：

```js
// 保留凭证的说明按 ref 累积；同一 ref 更新说明，不拆成多条。
function mergeRetainedCredential(list, entry) {
  const rows = Array.isArray(list) ? list : [];
  const index = rows.findIndex((row) => row.ref === entry.ref);
  if (index === -1) return [...rows, entry];
  const next = rows.slice();
  next[index] = { ...rows[index], ...entry };
  return next;
}
// kind: removed=移除后保留；replaced=轮换后保留；staged=保存未确认时保留。
```

`staged` 这一态容易被漏：保存流程抛错后（含**结果未知**）把 `attemptedRefs` 逐条列为「保留」，
让用户知道多出来一个 ref——因为**已禁止回收**，只能靠提示让用户知情。

## 5. 三条流程的差异

### 5.1 保存一行：只有本行用草稿

```js
const nextSources = storedById.has(id)
  ? stored.map((s) => (s.id === id ? row : storedRow(s)))     // 替换本行
  : [...stored.map(storedRow), row];                          // 新行追加到末尾
const nextDefault = pickDefault(nextSources, defaultSource);
```

其余行以**存储值原样带上**，不动它们的草稿——「保存当前源站」不该顺手提交别人的编辑。
`nextDefault` 里 `pickDefault` 兜住了「本行是新行的第一行」：候选里没有有效默认时取第一个。

### 5.2 移除：配置落地在前，清理在后

```js
// 未落库的新行从未持久化，直接丢草稿，不做远端写入。
if (!storedById.has(id)) { setSources((prev) => prev.filter((s) => s.id !== id)); return; }

const nextSources = stored.filter((s) => s.id !== id).map(storedRow);
const nextDefault = pickDefault(nextSources, defaultSource === id ? "" : defaultSource);
await face.writeSources(nextSources, nextDefault, revision);
const inUse = new Set(nextSources.flatMap((s) => [s.akRef, s.skRef]));
for (const ref of [target.akRef || akRefForId(id), target.skRef || skRefForId(id)]) {
  if (inUse.has(ref)) continue;
  try { await face.unsetSecret(ref); } catch (e) { note(...); }
}
```

### 5.3 设为默认：只改指针，`sources` 原样回写

```js
if (!storedById.has(id)) return;                               // 未落库的行不开放此操作
await face.writeSources(stored.map(storedRow), id, revision);   // 草稿一概不动
```

### 5.4 删除成功后的本地权威推进

远端已生效，界面**不得继续依赖回读**：回读失败时若仍按旧状态渲染，用户会看到实际上
已被删除的卡片并基于它继续操作。`nextSources` / `nextDefault` 就是刚写进存储的值：

```js
function localStateAfterRemoval({ sources, removedId, nextSources, nextDefault }) {
  return {
    sources: (Array.isArray(sources) ? sources : []).filter((s) => s.id !== removedId),
    stored: nextSources,
    defaultSource: nextDefault,
  };
}
```

## 6. 回读合并：清掉已提交的草稿

```js
// committed: Map<id, 本次提交的凭据值>。据此清空草稿；其它行保留用户正在编辑的内容。
function mergeDrafts(described, drafts, committed, previousStored = []) {
  const describedIds = new Set(described.map((s) => s.id));
  const draftById = new Map(drafts.map((s) => [s.id, s]));
  const merged = described.map((s) => {
    const d = draftById.get(s.id);
    const base = { ...s, secretDraft: "", secretFocus: false };
    if (!d) return base;
    const submitted = committed && typeof committed.get === "function" ? committed.get(s.id) : undefined;
    // 提交的是 trim 后的值，比较也必须 trim：否则 "  tok  " 这类带空白的输入保存后
    // 仍算脏，下一次保存会把它再写一遍，撤销别处的令牌轮换。
    const secretDraft = submitted !== undefined && String(d.secretDraft ?? "").trim() === submitted
      ? "" : (d.secretDraft ?? "");
    return { ...base, name: d.name, baseUrl: d.baseUrl, secretDraft, secretFocus: d.secretFocus ?? false };
  });
  // 「是否曾持久化」由上次存储基线判断，不能由凭据状态推断——已保存源站也可能没有凭据，
  // 或凭据状态读取失败。只保留真正未保存的新草稿。
  const storedIds = new Set(previousStored.map((s) => s.id));
  for (const d of drafts) if (!describedIds.has(d.id) && !storedIds.has(d.id)) merged.push({ ...d });
  return merged;
}
```

`dsh-jumpserver` 的老版用 `committedIds: Set` + `d.persisted` 标记，语义等价但**多一个状态位要维护**；
新写法从存储基线推导，少一处能写错的地方。两者共同的硬约束是：**比较必须 trim**。

回读本身要防 `unconfirmed`：

```js
async function reread(committed, baseline) {
  const r = await face.describe();
  if (r && r.unconfirmed) throw new Error(T.unconfirmedRead);   // 畸形读不能刷新基线
  const described = (r && r.sources) || [];
  setSources((prev) => mergeDrafts(described.map((s) => ({ ...s, persisted: true })), prev, committed, baseline));
  setStored(described);                                    // describe 读回的权威基线
  setDefaultSource((r && r.defaultSource) || "");
  setRevision(Number.isInteger(r && r.revision) ? r.revision : null);
}
```

保存成功后**先立刻** `setStored(nextSources)` / `setDefaultSource(nextDefault)`，再回读——即使两次回读
都失败，也不能再把刚保存的新卡片当成「从未保存的草稿」。

## 7. UI 契约

### 7.1 脏判定

```js
function rowDirty(draft, storedById) {
  const st = storedById.get(draft.id);
  if (!st) return true;                                          // 从未保存的新行
  if (String(draft.secretDraft ?? "").trim() !== "") return true; // 有待写入的凭据
  const a = storedRow({ ...draft, name: String(draft.name ?? "").trim(), baseUrl: String(draft.baseUrl ?? "").trim() });
  return a.name !== storedRow(st).name || a.baseUrl !== storedRow(st).baseUrl;   // trim 后比
}
```

### 7.2 凭据输入框的掩码三态

```js
const value = configured && !focus && draft === "" ? MASK : draft;   // MASK = "*".repeat(28)
// onChange：输入若以掩码开头，先剥掉掩码前缀
let v = e.target.value; if (v.startsWith(MASK)) v = v.slice(MASK.length);
```

| 状态 | 显示 | 触发 |
|---|---|---|
| 已配置 · 未聚焦 · 无草稿 | 28 个 `*` | 默认态 |
| 聚焦 | 空串 | `onFocus` 置 `focus: true`，用户直接输入新值 |
| 输入中 | 用户输入 | `onChange` 写草稿 |

`onBlur` 只在**草稿为空**时复位 focus，否则用户填了一半切走会看到自己的输入被掩码盖住。
掩码常量随服务尺寸调，但**绝不能回显真实凭据**——`describe` 也只回 `configured` 布尔。

### 7.3 卡片

- 头部：源站名 + `默认` 徽标（仅已落库且是默认源）+ `未保存` 徽标（未落库）+ 操作按钮
- 「设为默认」对**未落库行不渲染**（`isStored && !isDefault` 才出现），与 `canSetDefault` 同判据
- UID 只读回显，文案固定为「自动生成、全球唯一、不可修改」
- 折叠外壳对齐官方 `PluginCard`：收起 `--dsw-alias-bg-layer-3`，展开 `--dsw-alias-bg-layer-2`

未落库的 id 一旦成为 `defaultSource`，宿主判定「多源无有效默认」，此后每次工具调用都必须
显式传 `source`，而 UI 草稿仍在列表里——**界面与运行时从此不一致**。所以：先保存，再设默认。
