# 升级候选 · 提纯护栏（sp_purify + inbox-guard）

> 2026-11-20 · 来源：本机一次「整理 SSOT」事故（A558）· 状态：candidate

## 问题

1. `ssot_check` 的「未提纯」把 inbox 里**所有 `- ` 开头的行**都算条目——结构化笔记（要点列表）被误计，导致给笔记行加无意义标记。
2. 批量提纯脚本对**已有 `→ 归位:` 的行也重算**，覆盖历史正确映射。
3. 为恢复标记 `git checkout` tracked 文件，丢掉工作区未提交编辑；untracked 文件无 HEAD 可回。

## 提案

| 编号 | 内容 | 文件 |
|---|---|---|
| P1 | `is_entry()`：只认 `- [type] …` / `- YYYY-MM-DD [type] …`，非条目不计 | `tools/ssot_check.py` |
| P2 | `tools/sp_purify.py`：默认 dry-run；只处理未标记行；`--remap` 才重算；`--apply` 先备份 `inbox/`；写完单调校验（标记数不得减少） | 新增 |
| P3 | `[inbox-guard]`：当前标记数 vs HEAD，回退即报（`--strict` 下阻塞） | `tools/ssot_check.py` |
| P4 | 文档：A558 摘要 + 三条操作纪律（只用工具、改前备份、单文件提交） | `docs/` |

## 验收

```bash
# 1) 非条目不计
printf -- '- 取件根：~/share\n' >> inbox/2026-01-01.md
python3 tools/ssot_check.py | grep inbox   # 未提纯不应 +1

# 2) 已有标记不被重写
python3 tools/sp_purify.py                 # 计划变更 0 条

# 3) apply 有备份、标记单调
python3 tools/sp_purify.py --apply         # 输出「备份：…」且「标记数：N → ≥N」

# 4) 回退告警
git checkout -- inbox/2026-01-01.md        # 标记减少
python3 tools/ssot_check.py | grep inbox-guard  # ❌ 标记数回退
```

## 影响面 / 回滚

- 只读检查 + 新工具；不改 inbox/lines 数据格式。
- 回滚：删除 `sp_purify.py`、回退 `ssot_check.py` 即可。

## 附带

- A558 断言（提纯只追加、改前快照、单调校验）。
- 与 v0.17.x 的 `pending-index`、`sp_convert` 无冲突。
