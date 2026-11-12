# _CLEANING · 会话语料清洗记录

> 本目录存放导出的会话语料（md），本文件记录清洗规则与统计，保证「语料 ≠ 原文」可追溯。
> 入库前红线：凭证脱敏 + 域词脱敏（机制见系统件仓库 `docs/SEMANTIC.md`；词表各机自配）。

## 规则版本

- **L1 确定性规则 v0**：技能全文转储截除（段首 80 字符内出现 `Base directory for this skill:` → 整段丢弃；段中出现 → 截尾）；注入标记剥除（`[Request interrupted by user…]` / `<system-reminder>` / `[SYSTEM NOTIFICATION` / `<user-pasted-text>`，容忍 `**【U】** ` 内联前缀）；app 权威标题注入；空白归一。
- **L2 AI 判卷 v0**：脚本 triage（BIG / MARKER / CRED? / LOWCN）→ AI 逐段裁决为 `file | seg_idx | KEEP/DROP/TRUNCATE:n/REPLACE | 理由` → 脚本 apply + 逐条审计日志。**不允许 AI 直改语料文件**；宁留勿杀。

## 统计（最近一次）

| 项 | 值 |
|---|---|
| 会话数 | - |
| 文件数 | - |
| 清洗前块数 | - |
| 清洗后块数 | - |
| 疑难段裁决 | KEEP - / TRUNC - / REPL - |
| 日期 | - |

## 重跑

```bash
python3 ~/ssot/tools/kb_index.py        # 增量；语料变更后自动重嵌
python3 ~/ssot/tools/kb_search.py "…"   # 检索（留痕见 kb-index/search-log.tsv）
```
