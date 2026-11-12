---
name: ssmap
description: 本机会话台账（SSMAP）协议。当用户要开展新需求、问「从哪个会话继续/接续哪个/新开还是接续」、提到「业务线 / 台账 / 登记册 / 收尾记一行 / 盘点会话」时使用——先查 ~/ssot/sessions/registry.md 与 ~/ssot/lines/，再决定新开或接续。
---

# SSMAP · 会话台账（本机 ~/ssot）

本机有会话台账系统。核心两条回路：

**开工三问**（开展新需求前）：
1. 在 `~/ssot/sessions/registry.md` 搜相关词
2. 有线 → 读 `~/ssot/lines/<线名>.md` 的「当前在途」与【续点】→ 默认去【续点】会话接续
3. 无线 → 新开，补登记册一行 + 建线页

**语义检索（开工三问第 1.5 站）**：台账/线页没有直接命中时，先做一次「按意思搜」——
`python3 ~/ssot/tools/sp_semantic.py "<问题或关键词>" --mode route3 --top 5`
服务常驻本机 8399（安装见系统件仓库 `docs/SEMANTIC.md` §六）；每次检索自动记入 `kb-index/search-log.tsv`。
**派子 agent 时**：把检索规则与本任务相关的 1–3 个 `path:line` 抄进它的 brief——子 agent 不继承开机块与 SessionStart。

**收尾一行**（会话干完活时）：更新登记册里自己那行（状态 + 干到哪了）。

口径：同线同目标 → 接续；目标变了/上下文太脏/跨系统 → 新开，并把旧会话关键结论摘要作为新会话开场引用。
细则：系统件仓库 `docs/SSMAP.md`。布局与全貌：系统件仓库 `docs/ARCHITECTURE.md`（仓库位置见 `~/ssot/profile/.kit-path`）。
纪律：内容永不外发；只 pull 永不 push。
