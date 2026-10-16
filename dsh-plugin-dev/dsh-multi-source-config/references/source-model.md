# 源站模型：schema、标识、校验与迁移

本文给出可直接照抄的完整实现，取自 `dsh-jumpserver` 0.12.0 的 `index.js`（另注 `dsh-grafana` 0.18.1 的差异）。

## 1. 常量与正则

```js
// 旧版单源凭据引用（迁移时沿用，不搬密钥）
const AK_REF = "JUMPSERVER_ACCESS_KEY_ID";
const SK_REF = "JUMPSERVER_ACCESS_KEY_SECRET";
// 每源站派生引用的前缀
const AK_REF_PREFIX = "JUMPSERVER_AK_";
const SK_REF_PREFIX = "JUMPSERVER_SK_";
const DEFAULT_SOURCE_NAME = "default";
const MAX_SOURCES = 50;
const MAX_SOURCE_NAME_CHARS = 100;
const SOURCE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9-]{0,127}$/;
const CREDENTIAL_REF_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
```

`CREDENTIAL_REF_PATTERN` 是宿主凭证库的硬约束：ref 必须是合法标识符、**以字母或下划线开头**。
所以从 id 派生时必须剥掉横线等非法字符。

## 2. 三段降级的 id 生成

```js
export function generateSourceId() {
  const c = globalThis.crypto;
  if (c?.randomUUID) return String(c.randomUUID());
  if (c?.getRandomValues) {
    const bytes = c.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;      // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80;      // variant
    const hex = Array.from(bytes, (x) => x.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
```

客户端半要有**同一份**实现（浏览器没有 Node 的 crypto 形态差异），且 `Date.now` 兜底分支在
`randomUUID` 缺失的裸环境里仍然可用。

## 3. 由 id 派生凭据引用

```js
function refForId(prefix, id, label) {
  const clean = String(id ?? "").replace(/[^A-Za-z0-9_]/g, "").slice(0, 64);
  return validateCredentialRef(`${prefix}${clean}`, label);   // 派生结果也要过正则
}
export function akRefForId(id) { return refForId(AK_REF_PREFIX, id, "AccessKeyID"); }
export function skRefForId(id) { return refForId(SK_REF_PREFIX, id, "AccessKeySecret"); }
```

**要点**：派生函数是纯函数，host 与 client 两侧同式实现，因此
「读到的源站没有 ref」时可以各自补出来，不需要额外约定。改 `name` 不影响 ref —— 密钥不需要搬家。

## 4. 单个源站的持久化形态（草稿字段不落库）

```js
// 一行源站的持久化形态（不含草稿字段）
function storedRow(s) {
  return {
    id: s.id,
    name: String(s.name ?? ""),          // 由调用方 trim
    baseUrl: String(s.baseUrl ?? ""),
    akRef: s.akRef || akRefForId(s.id),
    skRef: s.skRef || skRefForId(s.id),
  };
}
```

UI 上的 `akDraft` / `skDraft` / `akFocus` / `skFocus` / `persisted` 都是**客户端状态**，
绝不能写进配置——它们每次保存都由 `storedRow` 过滤掉。

## 5. 写前统一校验（host 与 client 各一份，规则一致）

```js
function validateConfigValue(raw) {
  const value = unwrapVolatile(raw) ?? {};
  validateCredentialRef(value.akRef ?? AK_REF, "AccessKeyID");
  validateCredentialRef(value.skRef ?? SK_REF, "AccessKeySecret");

  const sources = Array.isArray(value.sources) ? value.sources : [];
  if (sources.length > MAX_SOURCES) throw new Error(`At most ${MAX_SOURCES} sources can be configured.`);

  const names = new Set(), ids = new Set();
  for (const source of sources) {
    const id = typeof source?.id === "string" ? source.id.trim() : "";
    if (!SOURCE_ID_PATTERN.test(id)) throw new Error(`Invalid source id: ${JSON.stringify(source?.id)}`);
    if (ids.has(id)) throw new Error(`Duplicate source id: ${id}`);
    ids.add(id);

    const name = normalizeSourceName(source?.name);        // trim + 非空 + 限长
    if (names.has(name)) throw new Error(`Duplicate source name: ${JSON.stringify(name)}`);
    names.add(name);

    if (source.akRef) validateCredentialRef(source.akRef, "AccessKeyID");
    if (source.skRef) validateCredentialRef(source.skRef, "AccessKeySecret");
    if (source.baseUrl) normalizeBaseUrl(source.baseUrl, true);
  }

  const def = typeof value.defaultSource === "string" ? value.defaultSource : "";
  if (def && !ids.has(def)) throw new Error(`defaultSource ${JSON.stringify(def)} does not match any configured source.`);
}
```

校验函数在**两处**被调用：`settings.register(ns, Config, { validate })`（旧宿主）与
`updateConfig()` 写前自校验（新宿主）。**write 入口和启动迁移共用同一个函数**，避免两套规则漂移。

## 6. URL 规范化（顺带挡住内嵌凭据）

```js
function normalizeBaseUrl(input, allowInsecureHttp = true) {
  const value = String(input ?? "").trim();
  if (!value) throw new Error("Base URL is not configured. Set it in Settings → Plugins.");
  let url;
  try { url = new URL(value); } catch { throw new Error("Base URL must be an absolute HTTP(S) URL."); }
  if (url.protocol !== "https:" && url.protocol !== "http:")
    throw new Error("Base URL must use https:// or http://.");
  if (url.username || url.password) throw new Error("Base URL must not contain embedded credentials.");
  if (url.search || url.hash) throw new Error("Base URL must not contain a query string or fragment.");

  const loopback = url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]";
  if (url.protocol === "http:" && !loopback && !allowInsecureHttp)
    throw new Error("Plain HTTP is disabled for non-loopback hosts. Use HTTPS or set allowInsecureHttp: true.");
  return url.toString().replace(/\/+$/, "");      // 去掉尾部斜杠，避免拼接出双斜杠
}
```

`allowInsecureHttp` 是**全局**开关（对所有源站生效），不是一个源站一个——内网 HTTP 部署开箱可用，
安全要求高的部署显式关掉。

## 7. 旧单源迁移全文

```js
let disposed = false;
sctx.effect(() => () => { disposed = true; });

const waitForDescriptor = async () => {           // 见 SKILL.md §3
  if (scope) return undefined;
  for (let attempt = 0; attempt < MIGRATION_MAX_ATTEMPTS; attempt += 1) {
    if (disposed) return null;
    const descriptor = descriptorOf();
    if (descriptor) return descriptor;
    await new Promise((resolve) => { const t = setTimeout(resolve, MIGRATION_RETRY_MS); t.unref?.(); });
  }
  return null;
};

(async () => {
  try {
    const descriptor = await waitForDescriptor();
    if (descriptor === null) return;                            // 拿不到描述符：放弃，下次启动再试

    const current = currentConfig(descriptor);
    if (current.legacyMigrated === true) return;                 // 护盾已置：永不再迁
    if (Array.isArray(current.sources) && current.sources.length > 0) return;   // 用户已有源站

    const akRef = String(current.akRef || "").trim() || AK_REF;
    const skRef = String(current.skRef || "").trim() || SK_REF;
    const legacyUrl = String(current.baseUrl ?? "").trim();
    const [ak, sk] = await Promise.all([
      sctx.credentials.resolve(akRef),
      sctx.credentials.resolve(skRef),
    ]);
    if (!legacyUrl && !ak?.value && !sk?.value) return;           // 旧配置彻底为空：无需迁移

    const id = generateSourceId();
    await updateConfig({
      sources: [{ id, name: DEFAULT_SOURCE_NAME, baseUrl: legacyUrl, akRef, skRef }],
      defaultSource: id,
      baseUrl: "",
      legacyMigrated: true,
    }, descriptor);
    migrationStatus("sources", "materialized sources=1");
  } catch (error) {
    migrationFailure("sources", error);
  }
})();
```

### 迁移失败必须可诊断，但不能阻断启动

```js
function migrationFailure(step, error) {
  const message = String(error?.message ?? error);
  const reason = /conflict|revision/i.test(message) ? "revision-conflict"
    : /invalid|duplicate|at most|does not match/i.test(message) ? "invalid-config"
    : "settings-error";
  console.error(`[jumpserver-migrate] ${step} failed reason=${reason}`);
}
```

静默 `catch` 会让真机验收无法区分「没执行」「读错目录」「版本冲突」三类情况。**至少要打一条带
`reason=` 的结构化日志。** 其中 `revision-conflict` 是**正常路径**：用户在迁移跑之前就在设置页
保存了自己的源站，此时迁移应当放弃，用户配置优先。

## 8. 生效源站列表与默认源

```js
function effectiveSources() {
  const cfg = activeConfig();
  const raw = Array.isArray(cfg.sources) ? cfg.sources : [];
  const list = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const id = typeof entry.id === "string" ? entry.id.trim() : "";
    const name = typeof entry.name === "string" ? entry.name.trim() : "";
    if (!id || !name) continue;                       // 形状不全的行直接跳过
    list.push({
      id, name,
      baseUrl: typeof entry.baseUrl === "string" ? entry.baseUrl : "",
      akRef: entry.akRef || akRefForId(id),
      skRef: entry.skRef || skRefForId(id),
      legacy: false,
    });
  }
  if (list.length > 0) return list;
  // 护盾已置 = 用户主动删光了源站，不能再回退成隐式的旧版源站
  if (cfg.legacyMigrated === true) return [];
  return [{
    id: null, name: DEFAULT_SOURCE_NAME,
    baseUrl: typeof cfg.baseUrl === "string" ? cfg.baseUrl : "",
    akRef: cfg.akRef || AK_REF, skRef: cfg.skRef || SK_REF,
    legacy: true,
  }];
}

function defaultSourceId(sources) {
  const cfg = activeConfig();
  if (typeof cfg.defaultSource === "string" && cfg.defaultSource &&
      sources.some((s) => s.id === cfg.defaultSource)) return cfg.defaultSource;
  return sources.length === 1 ? sources[0].id : null;    // 唯一源站即默认
}
```

注意 `legacy` 隐式源站的 `id: null` —— 它不是一个可持久化的条目，`sourceIdentity()` 里用
`src?.id ?? "legacy"` 把它映射成固定串，正因如此审批绑定对隐式源站同样有效。
