---
name: message-sync
description: >-
  Use when turning scattered notes, chat logs or document content into a
  structured team announcement in the house style — @-blocked by audience,
  numbered outlines, quantified wording, 【】-marked key entities, every action
  owned by a person with a deadline — and saved to a timestamped desktop file.
  Ships 7 message formats with a format-switching rule, a style profile distilled
  from real team messages, and a privacy self-check for anything leaving the
  internal channel. Triggers: 整理一下 / 整理成消息 / 整理这段话 / 帮我整理 /
  写个通知 / 写个公告 / 进度同步 / 发群里 / 群消息 / msg / message-sync / 整理这个文档。
license: MIT
compatibility: >-
  Pure standard-library Python 3 (argparse / os / re / hashlib / json); no
  third-party packages, no network access. Runs on Windows, macOS and Linux —
  the desktop path is auto-detected (registry first on Windows) and can be
  overridden with -d. An optional corpus at references/raw_ty.txt (or the
  MSG_RAW_CORPUS env var) refreshes the style profile; without it the committed
  profile serves as a static baseline and message drafting still works.
---

# 团队消息整理助手

把 **碎片化信息**（口述、聊天记录、随手记）或 **文档内容**（文档链接 / 本地文件）
整理成符合团队风格的结构化消息，并写入桌面 `message-<标题>-<时间戳>.txt`（永不覆盖）。

---

## 环境适配（动笔前先读）

本 skill 只依赖 Python 标准库，无第三方包。三个环境量需要现场确认，**不要凭记忆写死路径**：

```bash
# $SKILL = 本 SKILL.md 所在目录，按实际路径填写（后文命令都用它）
SKILL="/path/to/message-sync"

# 1) Python 解释器：先探测，后文命令里的 python3 指探测到的那个
command -v python3 || command -v python
python -c "import sys; print(sys.executable)"

# 2) 技能目录：脚本用自身位置定位，无需传入
#    sync_style.py / save_msg.py 内部都以 __file__ 推算 SKILL_DIR

# 3) 桌面目录：save_msg.py 已内置探测（注册表 → 候选 → 主目录）
#    Windows 上桌面常被重定向到非系统盘，直接拼 ~/Desktop 可能写失败
```

| 项目 | 说明 |
|------|------|
| 技能目录 | 脚本按 `__file__` 自行定位，放在任意路径都能跑 |
| Python | 优先 `python3`；Windows 上无该命令时用 `python`，下文命令照此替换 |
| 桌面 | 由 `save_msg.py` 自动探测，`-d` 可显式指定 |
| 临时草稿 | 可用 `/tmp/_msg_draft.txt`，也可完全不用临时文件、直接 `-c` 传 |

**语料状态**：`references/raw_ty.txt` 是可选的语料文件，**缺失不影响整理功能**——
`style_guide.md` 里已固化的动态档案就是静态基线。需要更新风格时再提供语料，
路径按下面「语料更新」一节给。

---

## 风格档案（先读，再动笔）

`references/style_guide.md` 末尾有一块 **动态风格档案**（`<!-- AUTO-SYNC -->` 标记之间），
由 `scripts/sync_style.py` 从语料统计生成，包含：高频 @ 对象、编号体系分布、
【】标注高频内容、常见开场白、时间表达、量化表达样例、**本次新增样本**。

**每次整理消息前，先读一遍动态档案**，尤其看「本次新增样本」——那是团队最新的说话方式，
优先级高于通用规则。档案与语料不一致时（用户刚更新过语料），先同步再动笔。

---

## 核心流程

### 第零步：判断是否需要同步风格档案

出现下列任一情况，**先跑同步再整理**：

- 用户说 `同步风格` / `更新风格` / `语料更新了` / `重新学一下`
- 语料的修改时间晚于 `references/.style_state.json` 记录的 `synced_at`
- 用户明确说"最近说话风格变了"

```bash
python3 "$SKILL/scripts/sync_style.py" --dry-run    # 先看会生成什么
python3 "$SKILL/scripts/sync_style.py"              # 确认后写入
```

没有上述信号就跳过，直接进入第一步。**没有语料时不要反复尝试同步**，跑一次确认不存在就继续整理。

### 第一步：拿内容

两种入口，先判断是哪种：

| 入口 | 特征 | 处理 |
|------|------|------|
| **A. 碎片化信息** | 用户直接在对话里贴了一段话/几条要点/一段聊天记录 | 直接用，跳到第二步 |
| **B. 文档链接 / 文件** | 给了 URL 或文件路径 | 先取内容，再进第二步 |

**B 类取内容的方式**（按来源选工具）：

| 来源形态 | 取内容的手段 |
|---------|-------------|
| 本地文件路径 / 工作区文件 | `Read` 工具直接读 |
| 腾讯文档（`docs.qq.com`） | 加载 `tencent-docs` skill |
| 企业微信文档 / 微盘 | 用企业微信连接器；未开启时请用户直接粘贴正文 |
| 内部知识库 / 语雀等需登录的系统 | 对应连接器或 skill 未装时，请用户粘贴正文 |
| 其它公网链接 | `WebFetch` |

取不到内容（无权限 / 需登录 / 抓取为空）→ **不要瞎编**，直接告诉用户取不到，请他自己贴正文。

### 第二步：补信息（先判够不够）

对照下面 5 项检查原材料，**缺什么问什么，一次最多问 2 个**，不要一口气甩一堆问题：

1. **给谁** — 全员知会，还是某个具体人执行？（决定要不要 `@`）
2. **什么事** — 一句话能说清的主题
3. **什么状态** — 做完了 / 进行中百分之多少 / 还没开始
4. **要对方做什么** — 知会、确认、协助、拍板？（决定格式）
5. **什么时候** — 截止时间或时间节点

**红线**：不许编造。原文没有的数字、时间、结论一律不补；实在缺就写 `待确认`，并在回复里提示用户。

### 第三步：选格式并整理

按 `references/formats.md` 的选型决策挑一种格式，再按 `references/style_guide.md` 的细则打磨。

打磨自检清单（每条都要过）：
- [ ] 接收对象写清楚了，该 `@` 的都 `@` 了
- [ ] 结论在最前面，不是埋在最后
- [ ] 骨架里填的是**信息**不是**套话**，没有空壳段落
- [ ] 模糊词全部换成数字或明确时间点（`差不多`→`85%`，`尽快`→`今天下班前`）
- [ ] 关键实体（IP / 主机名 / 方案名 / 数量 / 状态）用【】标注
- [ ] 编号体系同一层只用一套
- [ ] 没有编造任何原文没有的信息
- [ ] 若整理结果要对外（发公开群、写进文档、进仓库），先过一遍 `scripts/privacy_scan.py`

### 第四步：落盘

**必须用脚本**，不要用 `Write` 工具直接写桌面（脚本保证文件名唯一、不覆盖、自动探测桌面路径）：

```bash
python3 "$SKILL/scripts/save_msg.py" -c "$(cat <<'EOF'
<整理好的消息正文>
EOF
)"
```

或先把正文写入临时文件再落盘：

```bash
cat > /tmp/_msg_draft.txt <<'EOF'
@所有人
……
EOF
python3 "$SKILL/scripts/save_msg.py" -f /tmp/_msg_draft.txt
```

脚本输出 `SAVED: <路径>` 即成功。
文件名规则：`message-<首行标题>-YYYYmmdd-HHMMSS.txt`，同名（同秒）自动追加 `-2`、`-3`，**永不覆盖旧文件**。

落盘后：
1. 把完整路径告诉用户
2. 把正文在对话里也回显一遍，方便直接复制粘贴到群里
3. 删掉临时草稿文件 `/tmp/_msg_draft.txt`

### 第五步：不满意就换格式

用户说"太长""不像""不是这个意思""太啰嗦" → **不要在同一格式里小修小补**，直接换一种格式重出：

- 说太长 → 降级到 ⑤ 极简要点式
- 说太简单 → 升级到 ① 群播报式 或 ④ 进度同步式
- 说人都没点到 → 改 ② 指派式，一块一个人
- 说要老板拍板 → 改 ⑦ 决策建议式
- 说信息杂 → 按主题拆成多条，各选各的格式

换格式时**只换组织方式，不删信息**。如果新旧两版用户都可能要，**两版都落盘**（时间戳不同，不会互相覆盖）。

---

## 重要原则

1. **只整理、不编造** — 所有数字、时间、结论必须来自原材料
2. **先结论后细节** — 对方只看前两行就知道要不要继续看
3. **责任到人 + 时间到点** — 没有 `@人` 和 `时间` 的待办等于没写
4. **量化，消灭模糊词** — `差不多/一些/尽快/还行` 一律换算成数字或具体时间点
5. **格式不对就换** — 换格式的成本远低于在同一格式里反复微调
6. **永不覆盖** — 落盘一律走 `scripts/save_msg.py`
7. **分发前看边界** — 整理结果含真实姓名、内网地址、客户名时，只发内部渠道；
   要进公开仓库或对外文档，先脱敏再发（见下节）

---

## 脱敏约定

`references/style_guide.md` 中的示例与动态档案**已脱敏**，占位符含义固定：

| 占位符 | 指代 |
|--------|------|
| `@成员A` … `@成员K` | 团队内承担不同职责的人，字母只标志「是否同一人」，不代表真实姓名 |
| `<内网 IP>` `<主控 IP>` `<旧数据源 IP>` | 内网地址，实际使用时替换为真实值 |
| `<客户 A>` `<客户 B>` `<业务线>` | 客户或业务线名称 |
| `<集群名>` `<项目名>` | 内部集群 / 项目代号 |

整理真实消息时，占位符**必须替换为真实值**（否则发出去没人知道 @ 谁）；
只有把这份 skill 本身对外分发时才保留占位符。

发布前自检：

```bash
python3 "$SKILL/scripts/privacy_scan.py" .          # 扫当前目录
python3 "$SKILL/scripts/privacy_scan.py" . --strict # 有命中即非零退出，可接 CI
```

扫描规则：内网 IP、**带用户名的绝对路径**（macOS / Linux 的 `/Users/`、`/home/` 前缀，
以及 Windows 盘符下的用户目录）、邮箱、手机号、
`@` 中文姓名、以及 `references/privacy-rules.txt` 里的自定义敏感词（一行一个，`#` 开头为注释）。

---

## 目录说明

- [style_guide.md](references/style_guide.md) — 语言风格细则（六大特征 + 排版细则 + 写作四步法）+ 末尾 **动态风格档案（自动同步区）**
- [formats.md](references/formats.md) — 7 种输出格式模板 + 选型决策 + 换格式规则
- `scripts/save_msg.py` — 落盘脚本，自动探测桌面，生成 `message-<标题>-<时间戳>.txt`，同名自动加序号，绝不覆盖。`-d` 可显式指定目录
- `scripts/sync_style.py` — 语料同步脚本，重算统计并刷新 style_guide.md 的自动同步区；`--dry-run` 只预览；`--source` 可换语料路径
- `scripts/privacy_scan.py` — 脱敏自检，扫内网 IP / 绝对路径 / 邮箱 / 手机号 / @姓名 / 自定义词
- `references/.style_state.json` — 同步状态（上次同步时间 + 各段落指纹），用于识别新增内容；首次同步时自动生成，勿手改
- `references/privacy-rules.txt` — 可选的自定义敏感词表，脱敏自检时一并匹配

---

## 语料更新（三步）

1. 把语料放到 `references/raw_ty.txt`（或设环境变量 `MSG_RAW_CORPUS`，或用 `--source` 指定）
2. 跑 `sync_style.py` 刷新动态档案
3. 看输出里的「本次新增样本 N 段」，读一遍新增内容

**如果新增内容体现了新风格**（新的编号习惯、新的开场白、新的收口方式、新的标注用法），
把这条新规律**手工补写进 style_guide.md 上面的静态规则区**——脚本只管统计，规则提炼归人。
如果新增样本里出现了新的常用 @ 角色 / 项目类型，同步更新 `formats.md` 里的示例骨架。

> 同步后档案里会出现真实姓名与内网地址，属正常；**别把同步后的 style_guide.md 原样提交到公开仓库**，
> 先跑 `privacy_scan.py` 再决定。

---

配套 skill：本篇不依赖 DSH 生态，自足可用。整理好的消息若要落成网页或文档页，
排版与字号层级见 `ui-visual-language`；要把架构图、流程图贴进消息，作图规范见 `svg-diagram`。
总览与索引见 `dsh-plugin-dev-guide`。
