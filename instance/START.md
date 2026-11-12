# START · 读档入口（本机知识中枢）

> 本机 agent 的知识中枢（SSOT）。系统件仓库位置见 `profile/.kit-path`（README / UPGRADE 在仓库根）。

## 目录

| 位置 | 是什么 |
|---|---|
| `sessions/registry.md` | 会话登记册——开工三问第一站 |
| `lines/` | 业务线页（在途/决策/相关会话/【续点】） |
| `knowledge/` | 断言库 / 术语表 / topics/ 主题 / open-loops 未尽工作 |
| `inbox/` | 新知识入口（fact 带 source / decision 带 owner） |
| `profile/` | 开机块等（harness-boot.md） |
| `tools/` | 薄壳编译 / 语义索引检索 / 会话普查 / 自查 / 6h 值守 / 门禁 |
| `SSOT_REPORT.md` | 冷启动单文件（steward 生成：线/登记/断言 lint/索引 commit/草稿） |

## 常用命令

- 开工：走「开工三问」（技能 `ssmap` 或系统件仓库 `docs/SSMAP.md`，位置见 `profile/.kit-path`）
- 搜：`python3 ~/ssot/tools/kb_search.py "…"`（需嵌入服务，见系统件仓库 `docs/SEMANTIC.md`）
- 薄壳：`python3 ~/ssot/tools/sp_compile.py --mem`（生成候选；`--deploy` 切换下发）
- 自查：`python3 ~/ssot/tools/ssot_check.py`

## 协议速记

- 三不变量：原文不可变 / 单向提纯 / 一个事实一个家
- 内容永不外发；只 pull 永不 push；外发类动作逐批显式确认
