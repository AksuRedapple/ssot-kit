# ARCHITECTURE · 系统全貌与双机模型

## 一图

```
┌─ macmini（上游 · 迭代者）─────────────────────────┐
│  ~/ssot（本机知识中枢：线/知识/收件箱/台账）      │
│  系统件迭代（工具/协议/技能/模板）                │
│  bash scripts/publish.sh ──► 白名单发布           │
└────────────────────────┬─────────────────────────┘
                         │ push（仅上游）
                         ▼
            GitHub 私有仓 ssot-kit（系统件 · 零内容）
                         │
                         │ pull（仅下游）
                         ▼
┌─ 工作机（下游 · 使用者）──────────────────────────┐
│  git pull && bash scripts/update.sh              │
│  ~/ssot（本机知识中枢：同名同构，内容各自生长）   │
│  skills → ~/.qoder/skills（框架覆盖）             │
└────────────────────────┬─────────────────────────┘
                         │ 痛点/提案（经用户转交，不带业务内容）
                         └──► 回上游迭代 → CHANGELOG → 下轮 pull
```

## 三层文件分类（升级时行为不同）

| 层 | 位置 | 升级行为 | 举例 |
|---|---|---|---|
| **框架层** | 仓库 `tools/` `skills/` | **覆盖**（上游管理，别改本机副本） | sp_compile.py、ssmap 技能 |
| **模板层** | 仓库 `instance/` → `~/ssot/` | **只补缺**（本机没有才拷） | START.md、registry.md、线页模板 |
| **内容层** | `~/ssot/` 的 lines/knowledge/inbox/sessions | **永不触碰** | 你的台账、知识、收件箱 |

推论：想保留某个框架文件的自定义 = 改上游（提提案），不要改本机副本——下次升级会被覆盖。

## 系统部件（v0.8 配套）

| 部件 | 载体 | 作用 |
|---|---|---|
| 会话台账 | registry + lines/ + ssmap 技能 | 开工三问 / 收尾一行（接哪个、新开还是接续） |
| 知识库 | knowledge/ + inbox/ | 结论沉淀与提纯（fact 带 source / decision 带 owner） |
| 薄壳编译 | tools/sp_compile.py | 正本 → agent 记忆薄壳（常驻上下文极小化） |
| 语义检索 | tools/sp_index.py + sp_semantic.py + serve_embed.sh | 按意思搜（本地模型，可选层） |
| 会话普查 | tools/scan_sessions.py | 存量盘点（Qoder 会话 → TSV） |
| 自查 | tools/ssot_check.py | 台账/收件箱/缓存健康检查 |
| 升级通道 | `tools/install/update.sh`（`scripts/update.sh` 为兼容包装）+ UPGRADE.md | 下游升级一条命令 |

## 路线（待上游迭代，按下游需求拉动 + 开源就绪）

- [x] 开源就绪面：LICENSE（MIT）+ 英文 README + 定位与状态区
- [x] 会话原文入索引（四源会话 → S1 转录 → 语义索引），「按意思搜到会话」已可用
- [x] 定时值守（launchd 保鲜/巡检）下游版：`tools/steward.sh`
- [x] 开机块自动化安装（hook）：`scripts/install-hooks.sh`
- [x] 下游本地提案文件（`~/ssot/drafts/` + inbox 先落草稿）
- [x] 10 分钟快速开始（`docs/QUICKSTART.md`）
- [ ] 首发演示（demo 素材 / 方法文）
- [ ] 会话级技能族下放：memo / session-handoff 等（去个人化后）
- [ ] 英文文档与中文对齐（当前 README.en 仅覆盖到早期版本）

## 部署形态

**单机（默认）**：`clone` → `tools/install/setup.sh` → 你即是 owner，可自由改造；不存在"上游/下游"的权限约束。

**多机分发（可选）**：上游机维护 fork，下游机 `git pull` 只读同步；此模式下"只 pull"是**分发约定**，不是本项目的使用前提。

> 迭代原则：**照下游真实痛点拉动**，不预先堆功能（上游已经踩过的坑=白名单发布/内容零外泄/路径同构）。
