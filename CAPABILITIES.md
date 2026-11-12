# kit 能力清单（v0.13.2 · 2026-11-13）

> 本仓库是可直接安装、升级和测试的参考实现。发布门禁见 `scripts/release-check.sh`、`scripts/preflight.sh` 与 `scripts/public-audit.sh`。
> 分层：**核心四件**（日常必用）→ **自动化**（后台/批量）→ **LLM 管道**（实验性，需模型额度）。

## 核心四件

| 工具 | 用途 | 最小用法 |
|---|---|---|
| `sp_index.py` | 建/更新语义索引（源级增量 + 向量包增量追加/压实；失败不覆盖旧库） | `python3 tools/sp_index.py --incremental` |
| `sp_semantic.py` | 按意思搜（多模式 + 查询路由） | `python3 tools/sp_semantic.py "<问题>" --mode route3 --top 5` |
| `sp_compile.py` | 正本 → agent 记忆薄壳（可选 `--target` 换落点） | `python3 tools/sp_compile.py --mem --deploy` |
| `ssot_check.py` | 体检：台账/收件箱/索引/覆盖/接手面/线页漂移/conf 归一化 | `python3 tools/ssot_check.py` |

## 自动化

| 工具 | 用途 | 最小用法 |
|---|---|---|
| `sp_convert.py` | 各 harness 原始会话 → S1 五件套（一次一个源） | `python3 tools/sp_convert.py --src dsh --incremental` |
| `sp_opencode.py` | opencode sqlite → S1（v2 优先，legacy 补未迁移；只读、幂等） | `python3 tools/sp_opencode.py --limit 20` |
| `sp_candidates.py` | 候选账本：撞正本/去重/状态机；冲突检测走倒排 token 增量近邻（不做全库 O(n²)） | `python3 tools/sp_candidates.py --src all --session <sid8>` |
| `sp_triage.py` | 候选 → 审阅表 → A/R → 收件箱 | `python3 tools/sp_triage.py extract` |
| `sp_dispatch.py` | 开局上下文（预算分级） | `python3 tools/sp_dispatch.py --level pointer` |
| `sp_handoff.py` | 收工交接四段 + 检查 | `python3 tools/sp_handoff.py --check` |
| `sp_coverage.py` | 覆盖审计（原始/转录/索引缺口；OpenCode 分母=v2 根+legacy-only 根） | `python3 tools/sp_coverage.py` |
| `sp_takeover_lint.py` | 线页接手面四规则自检 | `python3 tools/sp_takeover_lint.py` |
| `sp_line_status.py` | 线页「现在时」状态行派生 | `python3 tools/sp_line_status.py --apply` |
| `sp_bootstrap.py` | 全量 dump 编排（发现→转换→建库→抽取） | `python3 tools/sp_bootstrap.py --plan` |
| `scan_sessions.py` | 存量会话普查 → TSV | `python3 tools/scan_sessions.py > /tmp/scan.tsv` |

## LLM 管道（实验性）

| 工具 | 用途 | 最小用法 |
|---|---|---|
| `sp_llm.py` | worker（`codex exec --output-schema`，预算/日志） | 由下面三个调用 |
| `sp_llm_extract.py` | 会话分块 → 候选（quote 必须原文子串） | `--sid <8位> --max-chunks 3` |
| `sp_llm_review.py` | 账本 → A/R 建议（不落盘） | `--limit 12` |
| `sp_llm_distill.py` | 候选 → 线页/断言草稿 | `--from-ledger --limit 12` |
| `sp_llm_gate.py` | 三道闸计算器 | `--extract` / `--review --labels` |
| `sp_assert_ingest.py` | 草稿断言 → 正本（撞正本 + 连续编号） | `--dir <草稿目录> --apply` |

## 安装

| 脚本 | 用途 |
|---|---|
| `tools/install/setup.sh` | 首装骨架 + 技能分发（多 harness 探测、`--dry`） |
| `tools/install/update.sh` | 升级：pull → 迁移(有才跑) → 体检 |
| `tools/install/install-service.sh` / `install-steward.sh` | 常驻服务 / 6h 值守 |

## 公开边界

本仓库只发布框架、模板与文档。个人/组织材料、真实会话、`evidence/`、`S2-index/`、`knowledge/` 内容、凭据与机器特定配置均不进入公开仓。
