# 版本探测：完整骨架与逐段语义

## 0. 骨架全貌

```ts
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, isAbsolute, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'

/** 与宿主发布同步发版的库包（版本号一致）。 */
const LIBRARY_PROBE_PACKAGES = ['@deepseek-ai/dsh-session-projection', '@deepseek-ai/dsh-session'] as const

/** 运行锚点专用序：宿主半在运行时**必然 import 过的**那个包排第一（它一定解析得到）。 */
const RUNNING_PROBE_PACKAGES = ['@deepseek-ai/dsh-session', '@deepseek-ai/dsh-session-projection'] as const

/** home 镜像序：CLI 包只在这里探测（插件从不 import 它）。 */
const HOME_PROBE_PACKAGES = ['@deepseek-ai/dsh', ...LIBRARY_PROBE_PACKAGES] as const

type Resolve = (specifier: string) => string
type ResolveUrl = (specifier: string) => string
```

**三个包清单分开写是有意的**：

- `RUNNING_PROBE_PACKAGES` 的第一个必须是宿主半**运行时真的 import 过的**包 ——
  否则「必然能解析」这个前提不成立，探测在正常部署上就失败
- `HOME_PROBE_PACKAGES` 里放 CLI 包 —— 它只存在于 home 镜像，不能出现在运行锚点
- 探测顺序即优先级：**先探最可能答得出的那个**

## 1. 自我根目录（守卫的基准）

```ts
function ownPackageRoot(): string {
  try {
    return dirname(fileURLToPath(import.meta.resolve('<包名>/package.json')))
  } catch {
    return dirname(fileURLToPath(import.meta.url))
  }
}
const PLUGIN_ROOT = ownPackageRoot()
```

- **经包自身的 `./package.json` 自引用定位**：源码树里、打包安装后都得到正确的包根
- 退化分支（解析不了自引用）用**本文件的目录**：守卫覆盖变小，但仍不会把插件自己的
  `node_modules` 误认成宿主 —— 所谓「少覆盖但不误判」
- 注意 `PLUGIN_ROOT` 必须是**包根**，不是插件源码目录

## 2. 两个读清单的手法

```ts
function versionOfManifest(manifestPath: string, expectedName?: string): string | undefined {
  try {
    const parsed: unknown = JSON.parse(readFileSync(manifestPath, 'utf8'))
    if (parsed === null || typeof parsed !== 'object') return undefined
    const record = parsed as { name?: unknown; version?: unknown }
    if (expectedName !== undefined && record.name !== expectedName) return undefined
    return typeof record.version === 'string' && record.version !== '' ? record.version : undefined
  } catch {
    return undefined
  }
}

/** 手法 A：直接解析 `pkg/package.json` 子路径。 */
function versionViaManifest(resolve: Resolve, packageName: string): string | undefined {
  try {
    return versionOfManifest(resolve(packageName + '/package.json'))
  } catch {
    return undefined   // 导出表没暴露这个子路径，或包不存在
  }
}

/** 手法 B：解析入口 → 逐级向上找同名的 package.json。 */
function versionViaEntry(resolve: Resolve, packageName: string): string | undefined {
  let dir: string
  try { dir = dirname(resolve(packageName)) } catch { return undefined }
  for (;;) {
    const version = versionOfManifest(join(dir, 'package.json'), packageName)
    if (version !== undefined) return version
    const parent = dirname(dir)
    if (parent === dir) return undefined      // 到根了
    dir = parent
  }
}
```

| 手法 | 适用 | 失败模式 |
|---|---|---|
| A：直接读子路径 | 导出表放行 `./package.json`（多数包） | Node 的 exports 门会拒绝；返回 `undefined` |
| B：入口向上找 | **打包成可执行文件的代理**：只导出入口桩，但入口所在目录的清单带真版本 | 需要 `name` 匹配才能避免误读祖先清单 |

两者串起来用：

```ts
function probeAnchor(resolve: Resolve, packageNames: readonly string[]): string | undefined {
  for (const packageName of packageNames) {
    const version = versionViaManifest(resolve, packageName) ?? versionViaEntry(resolve, packageName)
    if (version !== undefined) return version
  }
  return undefined
}
```

## 3. isInside：守卫的判定

```ts
function isInside(root: string, candidate: string): boolean {
  const rel = relative(root, candidate)
  return !rel.startsWith('..') && !isAbsolute(rel)
}
```

两个条件缺一不可：

| 条件 | 挡的情况 |
|---|---|
| `!rel.startsWith('..')` | 普通的上级逃逸（`../..`） |
| `!isAbsolute(rel)` | **跨盘符**：Windows 上 `relative('C:\\a', 'D:\\b')` 返回 `'D:\\b'`（绝对路径） |

也就是说，只写第一个条件的话，在跨盘符的部署上守卫会失效 —— 这种 bug 只在特定机器上出现。

## 4. 运行锚点

```ts
function probeRunningTree(resolve: Resolve, pluginRoot: string): string | undefined {
  for (const packageName of RUNNING_PROBE_PACKAGES) {
    let witness: string
    try { witness = resolve(packageName) } catch { continue }   // 这个锚点答不了，换下一个包
    if (isInside(pluginRoot, witness)) continue                  // 自家闭包，丢弃
    const version = versionViaManifest(resolve, packageName) ?? versionViaEntry(resolve, packageName)
    if (version !== undefined) return version
  }
  return undefined
}
```

注意 `continue` 的两种含义不同，都不许改成 `return`：

- **解析不到**：这个包在这个锚点不可见 → 试下一个包
- **见证落在自家目录内**：这个包被解析到了**插件自己的依赖**里 → 丢弃这个见证，
  但**仍要试下一个包**（另一个包可能落在宿主里）

## 5. home 锚点

```ts
try {
  const homePath = ctx.get('dshHomePath') as unknown
  if (typeof homePath === 'function') {
    const req = createRequire((homePath as (...segments: string[]) => string)('profiles', '<插件名>-version-probe.cjs'))
    const home = probeAnchor(specifier => req.resolve(specifier), HOME_PROBE_PACKAGES)
    if (home !== undefined) return home
  }
} catch { /* 无人应答；门控 fail open */ }
return undefined
```

- `dshHomePath('profiles', '<文件名>.cjs')` 只是**拿一个锚点路径**来建 `createRequire`
  （文件不需要存在）；从它出发的解析会落到 `profiles/node_modules`
- `ctx.get('dshHomePath')` 可能不存在、可能不是函数 → 形状校验后再用
- 整段包在 try/catch 里：宿主面是敌意可能的

## 6. 入口与「非 file URL」

```ts
export function detectHarnessVersion(
  ctx: Context,
  resolveUrl: ResolveUrl = resolveRunningModule,   // 可注入，供测试
  pluginRoot: string = PLUGIN_ROOT,                // 可注入，供测试
): string | undefined {
  const running = probeRunningTree((specifier) => {
    const url = resolveUrl(specifier)
    if (!url.startsWith('file:')) throw new Error(`<插件名>: non-file module URL for ${specifier}`)
    return fileURLToPath(url)
  }, pluginRoot)
  if (running !== undefined) return running
  /* …home 锚点… */
  return undefined
}
```

**非 `file:` URL（奇异 loader）**：它不对应磁盘上的任何清单 → 抛错 → 这个锚点整体让位给
home 锚点。注意抛的是**锚点内部**，由 `probeRunningTree` 的 `catch` 消化成「换下一个包」。

**两个可注入参数**（`resolveUrl` / `pluginRoot`）是刻意的：探测逻辑是最难在真实环境里
构造多版本场景的一段代码，把这两处变成参数之后，测试可以直接喂假解析器。

## 7. 本机复核

```bash
# 你机器上装的是哪个版本（权威出处）
cd "<workspace>" && node -e "
const j=require('<install-dir>/resources/app.asar/../app.asar/package.json')" 2>/dev/null

# 更可靠：asar 内的运行时描述
node _asar.mjs cat "<install-dir>/resources/app.asar" "dsh/desktop-runtime.json"
```

> 本地源码树（`deepseek-harness-master`）与已装运行时**可能是不同一代**，
> 版本号必须以**已装副本**为准。本机实测：源码树 `0.1.7-rc.2`，已装 `0.2.0-rc.2`。
