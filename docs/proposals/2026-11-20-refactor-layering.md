# 升级候选 · 代码分层重构（ssotlib）

> 2026-11-20 · 状态：P0 已落地（0.19.0）· 来源：0.18.0 审计

## 为什么要重构

0.18.0 审计的量化现状：

| 指标 | 数值 |
|---|---|
| 工具数 | 46 |
| 总行数 | 11,264 |
| 自带 `argparse` | 39 |
| 重复 JSON 读写点 | 80 |
| 工具互相 import | 16 |
| 最大文件 | `sp_index.py` 1185 / `sp_semantic.py` 965 / `ssot_check.py` 750 |

直接症状：`is_entry` / 标记解析在 `ssot_check` 与 `sp_purify` 各有一份，改一处漏一处（A558 事故的根因）。

## 目标结构

```
ssotlib/                 # 纯标准库，无第三方依赖
  paths.py               # root / config / env 解析
  entries.py             # 条目、标记、conf 解析（is_entry 唯一实现）
  store.py               # jsonl/json 原子读写、坏行计数、schema
  index/                 # 版本目录、manifest、分块、嵌入
  asserts.py             # 断言解析（现 sp_assert_lib 升级）
  cli.py                 # 统一 argparse、退出码 0/1/2
tools/*.py               # 只做参数映射 + 调 ssotlib
```

依赖方向：`tools → ssotlib`；**禁止 tools 互相 import**。

## 五条设计原则

1. **单一真相**：条目解析只有 `entries.py` 一处。
2. **写操作默认 dry-run**：备份 + 单调校验（`sp_purify.py` 是样板）。
3. **失败显性**：禁止裸 `except: pass`，至少计数/落日志。
4. **退出码三态**：0 成功 / 1 产品失败 / 2 仪器失败。
5. **纯标准库**：公开仓不引第三方依赖。

## 迁移计划（strangle，不重写）

| 阶段 | 内容 | 风险 | 验收 |
|---|---|---|---|
| **0.19.0** | `entries.py` + `store.py` + `cli.py`；先迁 `ssot_check` / `sp_purify` / `sp_dispatch` / `sp_handoff` | 低 | 单测 + 现有 kit tests 全绿 |
| 0.19.x | `index/`（`sp_index` + `sp_semantic` + `sp_pending`） | 中高 | golden 回归 + 索引块数/检索命中不变 |
| 0.20 | `asserts.py` + candidates | 中 | 断言体检输出不变 |

## 验收判据（每阶段）

1. `tools/tests/run_all.sh` 全绿
2. `scripts/public-audit.sh` clean
3. `scripts/preflight.sh` 影子实例全绿
4. 行为不变：关键 CLI 输出/退出码与迁移前一致（抽样对比）
5. 新增模块有单测；`tools/` 里不再有重复实现

## 非目标

- 不改公开 CLI 参数与退出码语义
- 不引入第三方依赖
- 不重写工具逻辑，只搬移与收敛

## 第一批（P0）落地清单

1. `ssotlib/__init__.py`
2. `ssotlib/entries.py`：`ENTRY_RE`、`is_entry()`、`marker_count()`、`conf` 解析
3. `ssotlib/store.py`：`read_jsonl()`、`write_json_atomic()`、坏行计数
4. `ssotlib/cli.py`：`base_parser()`、`exit_code()`、dry-run 开关
5. 改 `ssot_check.py` / `sp_purify.py` 引用上述模块，删本地副本
6. 新增 `tools/tests/test_ssotlib_entries.py`、`test_ssotlib_store.py`

## 落地记录（P0，0.19.0）

- **目录落点修正**：共享层落在 `tools/ssotlib/`，不是仓库根 `ssotlib/`。
  理由：`python3 tools/xxx.py` 的 `sys.path[0]` 就是 `tools/`，放这里 import 不需要每个入口
  重复注入路径（那本身就是要消掉的重复）；安装脚本与 `kit_manifest.shipped` 也按 `tools/`
  相对路径工作，零特殊处理。
- `entries.py`：`ENTRY_RE` / `is_entry` / `has_marker` / `marker_count` / `pending_count` /
  `head_marker_count` / `normalize_conf` / `parse_conf` / `inbox_stats`。
- `store.py`：`read_json` / `iter_jsonl` / `read_jsonl`（坏行计数）/ `write_json_atomic` /
  `write_jsonl_atomic` / `append_jsonl`。
- `cli.py`：`base_parser` / `add_dry_run` / `exit_code` / `run`（0/1/2 三态）。
- 已迁移：`ssot_check.py`、`sp_purify.py`（删本地副本，改为 re-export/引用）、
  `sp_pending.py`（原子写改 `store`）。
- 行为不变证据：同一夹具下，v0.18.0 与 0.19.0 的 `ssot_check` / `sp_purify` 输出与退出码
  **逐字节一致**（P0 验收第 4 条）。
- 遗留：`sp_dispatch` / `sp_handoff` 本轮未迁——它们没有条目解析副本，等 0.19.x 与
  `index/` 一起处理；`tests/` 里的 `test_sp_purify.py` 保留（黑盒 CLI 行为）。

## 落地记录（0.19.x，索引层）

- 新增 `tools/ssotlib/index/`：
  - `layout.py`：`SEM/VERS/ACTIVE/LEGACY_DB`、`active_version` / `resolve_db` /
    `list_versions` / `set_active` / `write_root_manifest` / `prune_versions` / `pack_paths`。
    active 指针与根清单改用 `store.write_json_atomic`（原子不变，权限显式 0644）。
  - `embed.py`：`DOC_PREFIX` 与 `QUERY_PREFIX` 同文件成对定义；`embed_batch` / `embed_one`。
  - `pack.py`：`build_pack` / `build_pack_incremental` / `load_pack` / `pack_fresh`；
    numpy 改为函数内惰性导入（装完不跑索引不需要第三方依赖）。
- 消掉的重复：`sp_index.active_version…prune_versions` 六个函数、`sp_semantic._resolve_db`、
  两处嵌入 HTTP 调用、以及 **`sp_index → sp_semantic` 的工具互 import**（refresh_pack 改用共享件）。
- 兼容：`sp_semantic.load_pack` 仍是薄包装，保留 daemon 的 `_PACK_OVERRIDE` 注入点；
  `sp_semantic.embed` / `QUERY_PREFIX` 等既有名字不变（其他工具在用）。
- 行为不变证据：8 条查询输出逐字节一致、`sp_index --plan --json` 全等、golden 5/5 PASS、
  DB/向量包/BUILD 的 size+mtime+首尾校验和未变。
- 遗留：`sp_pending` 已在 0.19.0 用 `store`；`sp_index` 仍 import `sp_policy` /
  `sp_fingerprint` / `sp_assert_lib`（属 0.20 的 asserts/candidates 迁移）。

## 落地记录（0.20，断言与候选）

- `ssotlib/asserts.py`：`HEAD_RX` / `NUM_RX` / `ID_RX` / `STATUS_RX` / `SUP_RX` / `TAG_RX`、
  `parse` / `parse_text` / `ids` / `numbers` / `reserved_ids` / `lint`；`sp_assert_lib.py`
  降为兼容薄壳（旧导入名不变）。
- `ssotlib/candidates.py`：`norm` / `fp` / `tokens` / `jaccard` / `overlap` / `polarity` /
  `clean_claim` / `rstrip_lines` / `is_junk` / `sentences`（`NEG_RX` / `POS_RX` 同文件，
  保持「先否后肯」口径）。
- 删掉的重复：`ssot_check`、`sp_assert_alloc`、`sp_compile` 三处本地 `^## A` 正则；
  `sp_assert_audit` / `sp_assert_meta` / `sp_index` 的 `sp_assert_lib` 工具间 import。
- `sp_candidate_dedup` 改用 `ssotlib.index.embed.embed_one`，不再 importlib 加载 965 行的
  `sp_semantic.py`。
- 行为不变：同一夹具下 `ssot_check` 输出逐字节一致（含 dup/missing/reserved/标签口径）；
  断言相关回归（audit/meta/supersede/index/alloc）全绿。
- 工具互 import 现状（本次后）：`sp_index` 仍 import `sp_policy` / `sp_fingerprint` /
  `sp_pending`；`sp_supersede` import `sp_assert_meta`——留待后续小步收敛。

## 落地记录（0.21，索引线去环）

- 新增 `ssotlib/policy.py`（原 `sp_policy` 全量搬移）、`ssotlib/fingerprint.py`、
  `ssotlib/pending.py`（原 `sp_pending` 去掉 CLI 的核⼼）、`ssotlib/index/chunking.py`
  （原 `sp_index.chunk_file`）。
- 薄壳：`sp_policy.py` / `sp_fingerprint.py` 只 re-export；`sp_pending.py` 只保留 argparse。
- 去掉的互 import：`sp_index → sp_policy/sp_fingerprint/sp_pending`、`sp_coverage/sp_classify/
  sp_exit/sp_retire_candidates → sp_policy`、`sp_embed_bench → sp_fingerprint`、
  `sp_convert → sp_pending`、`sp_assert_audit → sp_index`。
- 行为不变：`sp_index --plan --json`、`sp_pending --decide --json`、`sp_coverage --json`、
  `policy.summary` / `fingerprint.hardware_fp` 全等。
- 仍未收敛的互 import（后续小步）：采集/会话簇（`sp_archive`/`sp_recall` → `sp_sources`，
  `sp_subagent`/`sp_s0scan` → `sp_convert`，`sp_line_split`/`sp_rebirth_check`/`sp_rejects` →
  `sp_session_io`）与 LLM 管道簇（`sp_llm_*`）。

## 落地记录（0.22，采集线）

- `ssotlib/sources.py`：`sp_sources` 的发现逻辑（ROOTS/env 覆盖/parse_since/discover/
  iter_files）；`sp_sources.py` 只留 CLI。
- `ssotlib/session_io.py`：`sp_session_io` 全量搬移（CC / Codex rollout / S1 三形状 +
  系统注入过滤 + `stats`）；薄壳保留旧名。
- LLM 管道的 6 处 `importlib` 加载 `sp_semantic`（只为 `embed` + `QUERY_PREFIX`）改为
  `ssotlib.index.embed`；同时清掉多余的 `import importlib.util`。
- 行为不变：`sp_sources --json` 逐字节一致；`test_session_lifecycle_tools` 仍 PASS。
- 仍未收敛：`sp_archive`/`sp_s0scan`/`sp_subagent` → `sp_convert`（`scrub`/`SECRET_RX`/
  `norm_content`/`local`/`DROP_TYPES`），LLM 簇内部互相 import。采集中枢 sp_convert 的
  共享件抽取留作下一小步。

## 落地记录（0.23，采集线收口）

- `ssotlib/ingest.py`：`SECRET_RX` / `scrub` / `norm_content` / `local` / `DROP_TYPES`
  从 `sp_convert` 搬出；`sp_convert` 反向引用共享件，`lstr`/`slugify` 等转换专用逻辑留在工具。
- 去掉的互 import：`sp_archive` / `sp_recall` / `sp_s0scan` / `sp_subagent` → `sp_convert`。
- 测试：`test_ssotlib_ingest.py`（脱敏形态、三形状归一、UTC+8、单一真相）；示例密钥用
  字符串拼接构造，避免 public-audit 把「测试样例」当真实凭据。
- 结果：采集、索引、断言三条线均为 `tools → ssotlib` 单向；仅剩实验性 LLM 簇内部互 import。

## 落地记录（0.24，shell 失败模式）

- 新增 `set -euo pipefail`：`scripts/session-gate.sh`（门禁，必须 fail loud）、
  `tools/steward.sh`（值守，失败要停而不是继续跑半套）。
- steward 内 `[ -f ... ] && DEC=$(...)` 改为 `if`——这是 `set -e` 的典型误杀点。
- 三个 hooks 保留 `set -u` 并写明 fail-open 理由：hook 失败不应阻塞用户会话；
  且 `[ -f "$ROOT/.xxx-off" ] && exit 0` 在文件不存在时返回 1，加 `set -e` 会直接终止 hook。
- `tools/tests/shell_strict_test.sh` 把「非测试脚本必须 set -e + 例外清单收敛」变成回归。
- 私有侧：`sp_ask.sh` 标注「薄包装需传播子进程退出码」例外；`eg2_watchdog.sh` 补 `set -u`。
  私有 `steward.sh`（L1 值守，与 kit 版不同）未动，留作单独一次小步。

### 0.24.1 补记（bash 3.2）

`$VAR` 后紧跟全角/中文时，macOS 自带 bash 3.2 会把多字节字符并入变量名（`ALLOW）：` →
变量 `ALLOW\xef...`），`set -u` 下直接 unbound。CI 的 `shell: /bin/bash` 就是 3.2，
本机 Homebrew bash 5 不报。规则：**变量在非 ASCII 字符前一律 `${VAR}`**。

## 落地记录（0.25，argparse）

- 56 处 `argparse.ArgumentParser(epilog=…, formatter_class=RawDescriptionHelpFormatter)`
  统一改为 `cli.base_parser(epilog=…, root=False)`；不新增 `--root`，不改任何工具参数。
- 验收：迁移前抓取 56 个工具的 `--help`，迁移后逐个对拍，**输出与退出码逐字节一致**。
- 实现坑：Python AST 的 `col_offset` 是 **UTF-8 字节偏移**，不是字符偏移。按字符拼接会
  在多字节行上错位；第一版因此把 `) \n` 吃掉、被 `ast.parse` 拦下（未写盘），改用字节切片后正常。
- 工具互 import 与 argparse 两项审计债至此收口。

## 落地记录（0.26，异常处理第一批）

审计口径复核：私有侧 `except Exception` 共 220 处（无裸 `except:`），其中 151 处是
「静默」（`pass`/`continue`/返回默认值）。但**静默 ≠ 有害**，按 try 里的操作分三类：

| 类 | 数量（约） | 处置 |
|---|---|---|
| 循环里逐行解析失败 → `continue` | 48 | 批量数据噪声，后续加坏行计数（未做） |
| 配置/旧值读取失败 → 默认值 | ~40 | 文件缺失属正常；损坏应告警（未做） |
| 状态写入 / 遥测写入失败 → `pass` | ~12 | **本批处理** |
| 探测（subprocess/HTTP）失败 → 默认值 | ~20 | 区分「没在跑」与「出错」（未做） |

本批只动最危险的一组：

- 状态写入（BUILD 清单）：`sp_index.write_build`、`sp_exit.touch_build` 改为抛
  `cli.InstrumentError`（退出码 2）。依据：写失败却继续，会让 daemon/体检读到旧清单。
- 遥测/审计日志：`sp_semantic` / `sp_search` / `sp_classify` / `sp_exit` / `sp_dispatch` /
  `sp_assert_meta` / `sp_mail` 改为 `cli.warn_once`，主流程仍不因日志失败而中断。
- 明确保留静默的：锁信息 `stamp`（诊断）、版本 STATUS 文件（advisory）、旧 meta 读取
  （缺字段只是少保留分类）、逐行解析（噪声）。

### 0.27 异常处理第二批（坏行计数）

- 逐行解析的 48 处静默 `continue` 中，先处理**账本/日志类**（丢了会影响状态判断）：
  `sp_candidates.load_index`、`sp_triage.extract_from_ledger` / `ledger_counts`、
  `sp_retire_candidates.load_hits`、`sp_subagent.parse_agent`、`sp_recall.scan_s1`、
  `sp_export.main`（meta 读取）。
- 做法：局部 `bad` 计数 + `cli.warn_once('bad:<path>', …)`，只在 `bad>0` 时输出到
  stderr；坏行仍跳过，不中断批次；`--json` 的 stdout 不受污染。
- 未处理：纯语料扫描（sp_llm_*）、逐文件 `continue` 的目录遍历——噪声大、价值低。

### 0.28 异常处理第三批（损坏状态）

- `store.read_json_strict`：`FileNotFoundError` 静默（没配/没装是常态），
  解析失败/权限问题 → 默认值 + `warn_once`。
- 迁移点：`sp_assert_alloc._load`（坏了会导致撞号）、`sp_assert_meta.load_meta`、
  `sp_bootstrap.load_state`、`sp_migrate.contract_num/load_state`、
  `ssotlib.policy.load_policy`（坏了会让监控会话进索引）、
  `layout.active_version`（坏了会退回旧库）、`sp_index.contract_schema`。
- 仍保留静默：只读报表类（`ssot_check` 各项）、纯展示字段（`build_commit`）。

### 0.29 异常处理第四批（探测语义）

- `cli.probe_warn(key, label, exc)`：`FileNotFoundError` / `ConnectionRefusedError`
  视为「没装 / 没运行」→ 静默；`TimeoutExpired` / `PermissionError` / 协议错 → `warn_once`。
- 迁移：`fingerprint.llama_version`、`sp_embed_bench.health`、`sp_index.git_commit`。
- 其余探测（`ssot_check.git`、`sp_line_status` 等）仍是「失败给默认值」，因为它们的默认值
  （`-` / 0）本身就是报表语义，不构成状态误判。
- 私有 `steward.sh`：加 `set -o pipefail` + `trap … ERR`（不中止，错误进日志）；
  与 kit 版不同，未随 kit 发布。
