---
name: ssot-ops
description: SSOT 记忆中枢操作路由（读档/归位/提纯/检索）｜触发: SSOT/记忆中枢/读档/开工先看记忆/整理记忆
---

# ssot-ops

> 薄路由。操作细节以仓库根 `GUIDE.md` 为正本；本文件只管「何时用、先读哪、禁止什么」。

## 何时用

- 开局 / 接手：需要跨会话记忆（不只是当前项目）
- 会话中 / 收尾：有值得长期留下的结论、数字、决策、坑
- 用户提「以前 / 上次 / 那个项目 / 还记得」或「还有什么事没做完」
- 用户说「记一下 / 写到 ssot / 归位 / 提纯 / 按意思搜」

## 不接的活（路由）

| 请求 | 去哪 |
|---|---|
| 项目内 `.memory/` 现场态 | `memo` 类技能 |
| 会话登记 / 反查 registry | `session-digest` |
| 文章成篇 / 审稿发布 | `essay` / `site-writing-guide` |
| 面试演练 | `gauntlet-drill` |

## 四步

1. **读**：`START.md` → `lines/<线>.md` → 项目 `.memory/` → 需要出处再 `evidence/`
2. **搜**：`python3 tools/sp_semantic.py "<问题>" --expand --top 5`
3. **写**：追加 `inbox/YYYY-MM-DD.md`，一行一条
4. **提纯**：`python3 tools/sp_purify.py`（默认 dry-run，`--apply` 才写，先自动备份）

## 最小行格式

```
- YYYY-MM-DD [fact|decision|insight|assertion|state] 内容 | source: … | line: … | owner: …
```

- `fact` 必带 source；`decision` 必带 owner
- `assertion` 只收「有取证 + 会跨项目复现」

## 红线

1. 不手改入口文件（`START.md` 等是编译产物）
2. 不建第二个家（关键资产不放单一 harness 目录）
3. 单向提纯，永不反向；inbox 原文不删
4. `evidence/` 只读；原文不可变
5. source 不编造；不确定标「未知」

## 提纯口径（2026-11-20）

用户说「整理 SSOT」= **全机维护**（健康检查 + 全量 inbox 提纯 + 线页同步 + 索引），不是只提纯当前会话；agent 不得自行缩小范围。

## 验收（agent 自检）

- **意图**：读档/归位/检索后，能说清"读了什么、归到哪、还缺什么"，且不写正本。
- **判据**：① `sp_dispatch --level pointer` 输出非空 ② 归位行带 `→` ③ `ssot_check` 健康
- **反例**：只答"我查了"而无路径/无判据 → 视为未完成
