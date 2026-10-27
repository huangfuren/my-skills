# my-skills

自己日常用的一些 skills，放在这里。

## 目录

| 名称 | 说明 |
| --- | --- |
| [dsh-plugin-dev](dsh-plugin-dev/) | DSH 插件开发 skill 库（10 篇 + 库级索引）—— 双半边骨架与构建链、会话投影、按需路由、多源配置、控件落位、会话标签页、设置页、跨版本兼容、挂载互操作。入口见该目录的 `README.md`，或 `dsh-plugin-dev-guide` 的「任务 → 读哪篇」索引 |
| [skill-creator](skill-creator/) | Skill 的编写方法论 —— 从具体场景界定边界、规划要沉淀的内容、目录与命名约定、SKILL.md 写作风格（祈使句）、人工检查清单与迭代闭环 |
| [svg-diagram](svg-diagram/) | 手写 SVG 架构图 / 网络拓扑图 / 流程图的作图规范 —— 配色语义、字号层级、坐标网格、箭头 marker、图例、文字溢出预估、结构校验与目视验证 |

## 说明

- 大多是给 AI 助手用的 skill（`SKILL.md` + `references/` 结构），按需维护。
- 每个 skill 一个子目录，目录内 `SKILL.md` 是入口。
- `dsh-plugin-dev/` 是一套**成套**的 skill 库（内含 10 篇 + 一份库级 `README.md` 与任务索引），
  与 `svg-diagram` 这类单篇 skill 不同，它自身再分一层子目录。
