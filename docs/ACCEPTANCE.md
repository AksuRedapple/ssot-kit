# 验收：给 agent 的意图与判据（不是给人看的测试代码）

> 本仓库的安装、升级、迁移都由 **agent 执行**。所以这里不发布我们的测试代码（它依赖上游本机数据），
> 而是发布 **意图 + 可判定的验收标准**：agent 读完知道"要达成什么、怎么算达成、失败了怎么报"。

## 0 通用回执格式（agent 必须回传）

```
命令: <实际执行的命令>
结果: rc=<退出码>
证据: <关键输出 1–3 行,或文件路径>
判定: PASS / FAIL(原因)
```

没有"证据"的 PASS 视为未验证。

## 1 新装（意图：从零装出一个健康实例）

| 项 | 内容 |
|---|---|
| 意图 | 在干净机器上装出可自检的实例，且不覆盖任何已有文件 |
| 步骤 | `bash tools/install/setup.sh --root <实例>` |
| 判据 | ① `<实例>/tools/ssot_check.py` 存在 ② 跑它输出含 `完成 ==（健康）` ③ 退出码 0 |
| 反例 | 若实例目录里 `tools/` 为空 → FAIL（说明安装件没同步框架件） |

## 2 升级（意图：旧实例升到当前版本，内容层不动）

| 项 | 内容 |
|---|---|
| 意图 | 框架件更新、内容层（lines/knowledge/inbox/sessions/evidence）零改动 |
| 步骤 | `bash tools/install/update.sh --root <实例>` |
| 判据 | ① 升级前后 `lines/ knowledge/ inbox/` 的文件列表与 sha 不变 ② `ssot_check` 健康 ③ 迁移（若有）成功 |
| 反例 | 内容层任一文件被改 → FAIL |

## 3 迁移（意图：把数据契约推进到当前版本，失败不留半迁移）

| 项 | 内容 |
|---|---|
| 意图 | 产物 schema 全部达标；失败时实例保持迁移前状态 |
| 步骤 | `sp_migrate.py --status` → `--to current --dry-run` → `--to current --apply` → `sp_schema_check.py` |
| 判据 | ① dry-run 前后数据文件 sha 不变 ② apply 后 `sp_schema_check` 退出码 0 ③ 二次 apply 提示"已是最新" |
| 反例 | 注入失败（`ZB_MIGRATE_FAIL=1`）后数据文件 sha 变化 → FAIL |

## 4 守卫（意图：旧契约实例上写工具必须拒绝）

| 项 | 内容 |
|---|---|
| 步骤 | 在 `contract.json` 缺失或版本过低的实例上跑写工具（如 `sp_candidates.py`） |
| 判据 | 退出码非 0，且 stderr 含 `先跑 python3 tools/sp_migrate.py` |

## 5 一条命令的总体闸门

上游发布前跑 `bash scripts/preflight.sh`（影子实例 dogfood）；下游可用同一脚本自证：

```bash
bash tools/tests/run_all.sh     # 随包冒烟（隔离 HOME）
```

**判据**：输出 `全部通过` 且退出码 0。

## 6 OpenCode v2 / 覆盖审计 / 0 候选三态（v0.10.0）

| 项 | 内容 |
|---|---|
| 意图 | OpenCode 新会话能进 S1；覆盖分母不再只数 legacy；未采集的会话不被说成「0 候选」 |
| 步骤 | `sp_opencode.py --list` → `sp_coverage.py --json` → `sp_triage.py extract --sid nosuchsid` |
| 判据 | ① `--list` 的 store 列出现 `session_v2` ② coverage 的 opencode `raw` 等于 v2 根 + legacy-only 根 ③ `extract --sid nosuchsid` 退出码 2 且输出含「未进账本」 |
| 反例 | coverage 只报 legacy 根数（如 27）而 S1 也停在旧数 → FAIL；`extract` 对不存在的 sid 仍 rc=0 且写「0 条候选」→ FAIL |

## 7 线页内容漂移（v0.11.0）

| 项 | 内容 |
|---|---|
| 意图 | 线页里的版本/状态字段不能与真源脱节；mtime 新鲜不等于内容正确 |
| 步骤 | 在 `profile/line_sources.json` 声明 `file/source/app/field/pattern`，然后跑 `ssot_check.py` |
| 判据 | 一致时输出 `[line-drift] 声明过的线页与真源一致`；不一致时输出 `❌ <线>: 线页 X ≠ 真源 Y`，`--strict` 下非零退出 |
| 反例 | 线页写 0.8.25、`latest.json` 已 0.8.30，仍报「全部新鲜」→ FAIL |

## 8 为什么不用"随包全量测试"

我们的测试依赖上游本机数据（`~/ssot/evidence`、私有语料、索引），随包既跑不通也泄路径。
所以随包的是：**冒烟测试（可复现）+ 本文件的意图与判据**；全量测试留在上游。

## 9 会话层闭环（v0.14.0）

| 项 | 内容 |
|---|---|
| 意图 | 新装实例能把 harness 真源采进来，语义/关键词都能命中会话原文；覆盖审计不再拿归档当分母 |
| 步骤 | `sp_sources.py` → `sp_archive.py --apply` → `sp_convert.py --src <h> --incremental` → `sp_coverage.py` → `sp_recall.py "<词>"` |
| 判据 | ① `sp_sources` 有非零会话 ② 归档后 `sp_archive` 二次运行 0 新增（同卷 hardlink） ③ `sp_coverage` 的 covered 与 S1 对账 ④ `sp_recall` 不依赖索引能命中 |
| 反例 | 只看 `sp_coverage` 的「原始」列就宣称采全（分母是归档本身）→ FAIL；`sp_recall` 读 S0 输出未脱敏 → FAIL |

## 10 嵌入配置（v0.14.0）

| 项 | 内容 |
|---|---|
| 意图 | 配置可按机器落在 profile；启动/索引/观测都能消费；不自动重启、不默认并发 |
| 步骤 | `sp_embed_autotune.py --probe` → `--bench --quick --apply` → `EMBED_CONFIG_DRY=1 bash tools/serve_embed.sh` → `sp_index.py --status` |
| 判据 | ① dry-run 的 `-c/-b/-ub/--parallel` 与 profile 一致 ② `sp_index --status` 显示 `batch=…(profile)` ③ `BUILD.json` 含 `config` ④ workers 默认 1（无 >5% 收益不采纳并发） |
| 反例 | `install-service.sh` 用 `$ROOT/models/...` 覆盖 profile 的真实模型路径 → FAIL；把 48GB 机器的 `workers=8` 当默认 → FAIL |

## 11 索引分类（v0.15 候选）

| 项 | 内容 |
|---|---|
| 意图 | 自动化/值守会话默认只归档不入索引；分类可预览、可覆盖、可重建 |
| 步骤 | `sp_classify.py --init` → `--scan` → `--apply` → `sp_index.py --plan` |
| 判据 | ① `--plan` 显示 include/skip 与理由 ② policy 跳过的源块不会在增量后复活 ③ `--all-classes` 可恢复 ④ coverage 单列 `跳过` 且不报缺口 |
| 反例 | 无 policy 文件时默认开始跳过 → FAIL（必须 opt-in）；启发式直接 apply 且无预览 → FAIL |

## 12 退出（v0.15 候选）

| 项 | 内容 |
|---|---|
| 意图 | 退出可验收、可审计、可回滚，且不会被下次转换复活 |
| 步骤 | `sp_exit.py --make-manifest` → `--retire --apply` → `--verify` → `sp_golden.py --check` |
| 判据 | ① verify 按 sid 报 blocks=0 且 retired=true ② 重复 retire 无新日志 ③ `sp_index --incremental` 不复活 ④ S0/S1 仍在 ⑤ `logs/index-ops.jsonl` 有记录 |
| 反例 | 只看总块数变化就宣称退出成功 → FAIL；删掉 S1/S0 才能退出 → FAIL（退出只删索引） |

## 13 S0 敏感层（v0.16 候选）

| 项 | 内容 |
|---|---|
| 意图 | 承认“索引干净 ≠ 归档干净”；默认保留原文，可选 copy-on-write 脱敏 |
| 步骤 | `sp_archive.py --scrub --dry --only <h>` → `--scrub --apply --only <h>` → `sp_s0scan.py --only <h>` |
| 判据 | ① 源文件 sha256 不变 ② 目标含 `[REDACTED-SECRET]` 且不再是 hardlink ③ manifest 记 `sensitivity:high/scrubbed/redactions/src_sha` ④ 复扫 0 命中 |
| 反例 | 对 hardlink dest 原地写导致源被改 → FAIL；`--scrub` 默认开启 → FAIL |

## 14 环境指纹（v0.16 候选）

| 项 | 内容 |
|---|---|
| 意图 | 只把 `model_fp` 当硬键；硬件/backend/llama 变化只影响性能，不失效向量 |
| 步骤 | `sp_embed_bench.py --quick --json` → `sp_index.py --status` |
| 判据 | ① bench 输出 hardware/model/llama/backend ② status 有 `model:[hard]` 与 `env:[soft]` ③ model_fp 不一致才提示 `--full` |
| 反例 | 8GB→16GB 因 hardware_fp 变化就要求全量重建 → FAIL |

## 15 断言状态/取代（v0.16 候选）

| 项 | 内容 |
|---|---|
| 意图 | 断言一条一块；状态 sidecar；superseded 可见但不硬屏蔽 |
| 步骤 | `sp_assert_audit.py` → `sp_assert_meta.py --apply` → `sp_index.py --incremental` → `sp_semantic.py "<断言话题>"` |
| 判据 | ① chunks 有 assertion_id/status/superseded_by ② vacant 不入索引 ③ active 优先、superseded 排后并标注 ④ `sp_supersede --propose/--confirm` 只写事件/meta |
| 反例 | 把 700 字混合块整体标 superseded → FAIL；自动改 Markdown 正本 → FAIL |

## 16 P4 检索命中数据收集（v0.16.1）

| 项 | 内容 |
|---|---|
| 意图 | 记录 top-k 命中源，为“长期零命中”退休候选提供数据；不自动删 |
| 步骤 | `sp_semantic.py "<查询>"` → 查 `S2-index/search-log.jsonl` → `sp_retire_candidates.py --days 180` |
| 判据 | ① 日志含 `topk_paths/topk_sids`（cap 20） ② `--no-log` 不写 ③ 候选排除 retired/policy 跳过 ④ 低日志/低覆盖标记 low_confidence ⑤ 只读不删 |
| 反例 | 零命中直接自动 `sp_exit` → FAIL；日志写入正文/查询原文未脱敏 → FAIL |

## 17 pending-index 交接（v0.17 候选）

| 项 | 内容 |
|---|---|
| 意图 | 懒触发采集后，大索引不随机撞点；规模可见、承诺持久、可改期 |
| 步骤 | `sp_convert` → `sp_pending --status` → `sp_index --plan --json` → `sp_pending --decide` → steward |
| 判据 | ① convert 后 marker 存在且含 sessions/est_blocks ② plan 有精确 pending_blocks ③ 超阈值/窗口外 defer ④ 索引成功后 marker 清 ⑤ `--no-pack` 保留 pack_stale |
| 反例 | 大索引仍被 steward 无条件执行 → FAIL；索引期间新转换被 marker 清除吞掉 → FAIL |

## 18 ssotlib 共享层（P0，v0.19.0）

| 项 | 内容 |
|---|---|
| 意图 | 条目/标记/conf 只有一份实现（A558 根因），tools 不再互相 import |
| 步骤 | `ssotlib.entries` / `store` / `cli` ← `ssot_check.py` / `sp_purify.py` / `sp_pending.py` 引用 |
| 判据 | ① `ssot_check.ENTRY_RE is entries.ENTRY_RE` 且 `sp_purify` 同 ② `test_ssotlib_*` 全绿 ③ 新旧 `ssot_check`/`sp_purify` 输出逐字节一致 ④ 影子实例 setup 后能 import ssotlib |
| 反例 | 任一工具里再出现本地 `ENTRY_RE`/`is_entry` → FAIL；安装后 `ModuleNotFoundError: ssotlib` → FAIL |

## 19 索引层共享件（0.19.x，v0.19.1）

| 项 | 内容 |
|---|---|
| 意图 | 版本目录/嵌入/向量包只有一份实现；去掉 `sp_index → sp_semantic` 的工具互 import |
| 步骤 | `ssotlib.index.{layout,embed,pack}` ← `sp_index` / `sp_semantic` 引用；`sp_pending` 走 `store` |
| 判据 | ① 8 条查询输出逐字节一致 ② `sp_index --plan --json` 全等 ③ golden 5/5 ④ DB/pack/BUILD 未写（size+mtime+校验和） ⑤ 向量包 noop/append/rebuild 三路有测试 ⑥ daemon `_PACK_OVERRIDE` 仍生效 |
| 反例 | 检索分数或命中路径变化 → FAIL；跑一次查询就重写向量包 → FAIL；daemon 注入被绕过 → FAIL |
