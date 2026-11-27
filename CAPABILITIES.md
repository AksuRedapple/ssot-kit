# kit 能力清单（v0.31.2 · 2026-11-27）

> 本仓库是可直接安装、升级和测试的参考实现。发布门禁见 `scripts/release-check.sh`、`scripts/preflight.sh` 与 `scripts/public-audit.sh`。
> 分层：**核心四件**（日常必用）→ **自动化**（后台/批量）→ **LLM 管道**（实验性，需模型额度）。

## 共享层（ssotlib）

`tools/ssotlib/` 是工具的共同底座（纯标准库，随 kit 安装）。**条目判定只有一份实现**：
`entries.py` 的 `ENTRY_RE` / `is_entry` / 标记计数 / conf 解析；`store.py` 负责 JSON/JSONL
原子写与坏行计数；`cli.py` 统一退出码（0 成功 / 1 产品失败 / 2 仪器失败）；
`index/` 收敛索引层——版本目录与 active 指针（`layout.py`）、doc/query 前缀成对（`embed.py`）、
向量包构建与压实（`pack.py`，numpy 只在真正读写向量包时导入）；`asserts.py` 唯一实现断言解析与
体检计数；`candidates.py` 提供候选文本口径（归一化/2-gram/极性）；`policy.py` / `fingerprint.py` /
`pending.py` 收敛索引线的策略、指纹与交接；`index/chunking.py` 是唯一切块实现；
`sources.py` / `session_io.py` 收敛采集线的源发现与会话读取（三形状 + 系统注入过滤）；
`ingest.py` 收敛脱敏/内容归一/时区（采集转换与归档共用）；命令行基座统一走 `cli.base_parser`。

> 依赖方向：`tools/*.py → ssotlib`。禁止工具之间互相 import，也禁止再复制 `ENTRY_RE`。

## 核心四件

| 工具 | 用途 | 最小用法 |
|---|---|---|
| `sp_index.py` | 建/更新语义索引（源级增量 + 向量包增量/压实；`--plan` 预览 class 策略；失败不覆盖旧库） | `python3 tools/sp_index.py --incremental` |
| `sp_semantic.py` | 按意思搜（多模式 + 查询路由）；首次查询自动唤醒 daemon，空闲 30 分钟回收；嵌入服务 `:8399` 同样按需拉起 | `python3 tools/sp_semantic.py "<问题>" --mode route3 --top 5` |
| `sp_compile.py` | 正本 → agent 记忆薄壳（可选 `--target` 换落点） | `python3 tools/sp_compile.py --mem --deploy` |
| `ssot_check.py` | 体检：台账/收件箱/索引/覆盖/接手面/线页漂移/conf 归一化；含 `[semantic-idle]` 生命周期观测 | `python3 tools/ssot_check.py` |

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
| `sp_sources.py` | 会话源发现（harness 真源；覆盖审计的分母，不拿归档自证） | `python3 tools/sp_sources.py` |
| `sp_archive.py` | S0 归档（opt-in；同卷 hardlink；`--scrub` copy-on-write 脱敏，源不动） | `python3 tools/sp_archive.py --apply` / `--scrub` |
| `sp_s0scan.py` | S0 归档密钥形态巡检（只报计数/路径，不打印内容） | `python3 tools/sp_s0scan.py --write-state` |
| `sp_recall.py` | 关键词兜底检索（不依赖索引；S1/S0/live 三层，输出脱敏） | `python3 tools/sp_recall.py "<关键词>" --raw` |
| `sp_drafts.py` | 收尾草稿 → registry 候选行（只读，不自动转正） | `python3 tools/sp_drafts.py --list` |
| `sp_classify.py` | S1 会话分类（session_class）backfill / 规则扫描 / 手工覆盖 | `python3 tools/sp_classify.py --scan` |
| `sp_exit.py` | 索引退出：stable sid manifest / tombstone / verify / 审计 | `python3 tools/sp_exit.py --retire <manifest> --apply` |
| `sp_retire_candidates.py` | P4 零命中退休候选（只读；top-k 日志聚合，人工裁决） | `python3 tools/sp_retire_candidates.py --days 180` |
| `sp_pending.py` | 采集→索引交接标记；steward 按 pending 规模/窗口决定 run/defer | `python3 tools/sp_pending.py --decide` |
| `sp_golden.py` | golden 回归；本机 agent 用 `--init/--suggest` 产出查询，基线只落实例 | `python3 tools/sp_golden.py --init` / `--check` |
| `sp_policy.py` | 策略读取库（index-policy / retired），供上面四件共用 | 被 `sp_index` / `sp_coverage` 调用 |
| `sp_assert_audit.py` | 断言库体检（状态/断链/环/引用/切块成本；只读） | `python3 tools/sp_assert_audit.py` |
| `sp_assert_meta.py` | 断言机器状态 sidecar（active/superseded/refuted/vacant/unknown） | `python3 tools/sp_assert_meta.py --scan` |
| `sp_supersede.py` | 断言取代提案/确认（append-only 事件 + meta） | `python3 tools/sp_supersede.py --propose A012 --by A031 --apply` |
| `sp_assert_lib.py` | assertions.md 解析（audit/meta/index 共用） | 被上面三件调用 |
| `sp_index_merge.py` | 合并分片索引（兼容 assertion_id/status/superseded_by） | `python3 tools/sp_index_merge.py --out ...` |
| `sp_embed_bench.py` | 嵌入吞吐基准（只读；输出 hardware/model/llama/backend 指纹） | `python3 tools/sp_embed_bench.py --quick` |
| `sp_fingerprint.py` | 环境指纹单一实现（bench/BUILD/status 共用） | 被 `sp_embed_bench` / `sp_index` 调用 |
| `sp_embed_autotune.py` | 探测 + 基准 → `profile/embed-profile.json`（不自动重启） | `python3 tools/sp_embed_autotune.py --bench --quick --apply` |
| `serve_embed.sh` | 嵌入服务启动；读 profile，env 可覆盖 | `EMBED_CONFIG_DRY=1 bash tools/serve_embed.sh` |
| `sp_takeover_lint.py` | 线页接手面四规则自检 | `python3 tools/sp_takeover_lint.py` |
| `sp_line_status.py` | 线页「现在时」状态行派生 | `python3 tools/sp_line_status.py --apply` |
| `sp_bootstrap.py` | 全量 dump 编排（发现→转换→建库→抽取） | `python3 tools/sp_bootstrap.py --plan` |
| `sp_purify.py` | 安全提纯：只追加、默认 dry-run、apply 前备份、标记数单调校验 | `python3 tools/sp_purify.py --apply` |
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

## 技能

| 技能 | 用途 |
|---|---|
| `ssot-ops` | 记忆中枢操作路由（读档/归位/提纯/检索） |
| `ssot-toolbox` | 工具统一手册（何时用/命令/判据/坑） |
| `ssmap` | 语义地图 |

## 公开边界

本仓库只发布框架、模板与文档。个人/组织材料、真实会话、`evidence/`、`S2-index/`、`knowledge/` 内容、凭据与机器特定配置均不进入公开仓。
