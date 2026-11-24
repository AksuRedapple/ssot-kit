# SEMANTIC · 可选语义检索层

> 主系统（台账 + 知识库）不依赖本层——grep 与台账已可用。装上本层后，可以「按意思搜」全部知识。

> 说明：`BUILD.json` 的 `commit` 为 `-` 表示实例不是 git 仓（正常形态），不是错误。
> 先做解释器自检：`python3 -c 'import sys,numpy;print(sys.version.split()[0],numpy.__version__)'`；失败时设 `SSOT_PY` 指向带 numpy 的 python（见 [COLDSTART.md](COLDSTART.md) §3）。

## 组成

> 前置：`python3` ≥3.10 + `numpy`（`pip install numpy`）。仅 macOS 已实测；Linux 可用但未系统验证。

- **嵌入模型**：EmbeddingGemma（多语言，~300M 激活；BF16 GGUF **≈532MiB**，文本嵌入主文件 557,950,176 B）
- **服务**：llama.cpp 的 `llama-server`（OpenAI 兼容 `/v1/embeddings`，纯本地）
- **脚本**：`~/ssot/tools/` 下 `sp_index.py`（建索引）+ `sp_semantic.py`（检索）+ `serve_embed.sh`（起服务）；随升级通道更新

## 零、自检（装完先跑）

按本文装完后，先过这三条，再建索引：

```bash
# ① 服务活着
curl -s http://127.0.0.1:8399/health          # → {"status":"ok"}

# ② 嵌入维度 / NaN / 范数
curl -s http://127.0.0.1:8399/v1/embeddings \
  -H 'Content-Type: application/json' -d '{"input":["自检"]}' \
  | python3 -c "import sys,json,math;v=json.load(sys.stdin)['data'][0]['embedding'];n=math.sqrt(sum(x*x for x in v));print('dim',len(v),'norm',round(n,4),'nan',any(x!=x for x in v))"
# 期望：dim 768 · norm≈1.0 · nan False

# ③ 索引可建（小样，不碰正式索引）
# 索引是整库的（没有 --root/--db 参数）；首次跑就是全量
python3 ~/ssot/tools/sp_index.py --incremental
```

**判据**：① 健康 ② `dim 768 / nan False / norm≈1.0`。任何一条不过，先修安装，别急着建全量索引。

## 一、装 llama.cpp

**首选：官方 Release 二进制**（版本可控、不滞后）。到
`https://github.com/ggml-org/llama.cpp/releases` 选 **macOS arm64** 资产
（注意资产是 `.tar.gz` 不是 zip），解压到固定目录：

```bash
mkdir -p ~/.local/opt/llama-nightly
# 以实际下载的资产名为准（下面为示例）
tar -xzf ~/Downloads/llama-b11681-bin-macos-arm64.tar.gz -C ~/.local/opt/llama-nightly --strip-components=1
export PATH="$HOME/.local/opt/llama-nightly:$PATH"
llama-server --version
```

**版本要求**：实测可用 build = **b11681（0.7.0-dev）**。**装载失败先升版本**——报
`unknown model architecture: 'gemma-embedding2'` 就是版本太老。

**备选：Homebrew**（注意 brew 稳定版常滞后，装载失败即升 nightly）：
```bash
brew install llama.cpp            # 若报 unknown model architecture，改用上面的官方 Release
```

> 不要把 brew 当默认路径：2026-10 实测 brew 稳定版 build 11429 装不上本模型。

## 二、拉模型（权重不入库，按需自拉）

放到 `~/ssot/models/embeddinggemma-2-BF16.gguf`。

```bash
mkdir -p ~/ssot/models
# 官方 GGUF 仓（HuggingFace）
curl -L -o ~/ssot/models/embeddinggemma-2-BF16.gguf \
  "https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/main/embeddinggemma-2-BF16.gguf"
# 国内网络慢：换镜像域名 hf-mirror.com（同路径）；或使用代理
```

体积口径：该文件 **557,950,176 B ≈ 532MiB**（BF16 文本嵌入主文件，sha256 与上游 LFS 一致）。
网传的「GB 级」体积是含 mmproj 等附件的整包口径，不是本文件。

⚠️ **必须用 BF16 档**：fp16 档在部分后端上会静默输出 NaN（索引全废且无报错）。

## 三、起服务

```bash
nohup bash ~/ssot/tools/serve_embed.sh > /tmp/embed.log 2>&1 &
sleep 3 && curl -s http://127.0.0.1:8399/health   # → {"status":"ok"}
```

默认端口 8399；改端口用环境变量 `EMBED_PORT`，模型路径放默认位即无需配置。
若 `llama-server` 不在 PATH，用 `LLAMA_SERVER=/path/to/llama-server` 指定。
**常驻**（可选，推荐）：`bash scripts/install-service.sh`——见 §六（在系统件仓库根执行，仓库位置见 `~/ssot/profile/.kit-path`）。

## 三·五、配置自适应（可选，保守版）

默认配置写死在 `serve_embed.sh`，但会优先读 `profile/embed-profile.json`（`EMBED_C/B/UB/PARALLEL` 可覆盖）。建议流程：

```bash
# 1) 只读探测：硬件 / 模型 / 当前服务 / 建议值（不写盘、不重启）
python3 ~/ssot/tools/sp_embed_autotune.py --probe

# 2) 只读基准：当前端口上测 batch × workers（不写索引）
python3 ~/ssot/tools/sp_embed_bench.py --quick

# 3) 写 profile（只写 profile，不改服务；下次启动生效）
python3 ~/ssot/tools/sp_embed_autotune.py --bench --quick --apply

# 4) 重启（按你的安装方式二选一）
bash ~/ssot/tools/serve_embed.sh
launchctl kickstart -k "gui/$(id -u)/com.ssot.embed"
```

- **workers 默认 1**：同机 8 路并发实测为负收益（139→124 块/秒）；并发只作为 opt-in 网格，不假设线性扩展。
- 想测隔离配置，先在 8398 起临时服务，再 `--port 8398 --bench`；不要用 autotune 重启 8399，也不要让它碰 active 索引。
- `--restore` 可回滚 `profile/embed-profile.json.bak`。
- 缓存键含硬件、模型、llama-server 版本；换机器/换模型后重新跑一次。
- profile 含本机模型绝对路径与硬件信息，属机器本地配置；不要提交到公开仓。

## 四、建索引 + 检索

```bash
python3 ~/ssot/tools/sp_index.py --incremental      # 增量建索引（源文件未变则跳过）
python3 ~/ssot/tools/sp_semantic.py "那条线之前在聊什么" --mode route3 --top 5
```

- 索引产物：`~/ssot/kb-index/kb.db`（sqlite；建议加入本机 .gitignore，不入任何版本库）
- 索引默认**排除** `compile/`（薄壳候选等生成物，与正本重复）、`sessions/_pending/`（Stop 草稿）、`.index/ models/ .git/ __pycache__/`
- **隐私闸**：文件命中完整密钥形态（`sk-…`/`ghp_…`/`AKIA…`/`hf_…`/私钥块）时**跳过不索引**，并在完成行报告数量；先在 `.kbignore` 或脱敏中处理，不要为了多索引而绕过
- 首次建索引约 1-3 分钟（视语料大小）；改完台账可重跑（增量，秒级）
- 想连**会话原文**一起搜：把会话导出为 md 放进 `~/ssot/sessions/corpus/` 再重跑索引
- 检索留痕：每次检索会在 `~/ssot/logs/semantic-calls.jsonl` 留一行（时间 + query + 耗时 + 命中数），用数据回答「到底有没有在用」

### 索引新鲜度（别把「落后 N commits」当重建令）

- `ssot_check` 的 `[build] 落后 N commits` 只是新鲜度提示：索引对应 `BUILD.json` 里的 commit，落后了跑一次 `--incremental` 即可
- **契约升级不触发全量重建**：索引是派生物、不纳入迁移；`sp_migrate` 只给 meta/账本/BUILD 补 `schema`，不碰 `kb-index/kb.db`
- 只有**嵌入模型或分块规则变更**才需要全量重建；日常增量交给 steward 定时跑
- 重建期间独占索引库，别的进程会 `database is locked`——动手前先确认没有 steward 索引进程在跑

### 增量包与并发（v0.10.0）

- **索引增量 ≠ 向量包增量**：`index.db` 只重嵌变了的源；`pack-vecs.f32` 以前每次全量重建（308k 块约 50s）。v0.10.0 起默认只追加 missing 行，`stale > 2000` / `missing > 5000` 才全量压实。
- **三个开关**：`--no-pack`（只更索引）、`--pack-only`（只更包）、`--full-pack`（强制压实）。批量写入可先 `--no-pack`，最后统一 `--pack-only`。
- **两个索引**：`chunks_id_only on chunks(id)` 让 `select id` 走覆盖索引（40s→0.3s）；`chunks_path_idx on chunks(path)` 让 `delete ... where path=?` 不再全表扫 1.9GB。首次在老库上创建约 80s，之后自动存在。
- **锁等待可见**：`.lock` 记录 pid/启动时间/argv；等锁每 30s 报一次。自动化用 `--no-wait`（拿不到锁 rc=3），手动可用 `--wait-timeout 300`。
- **块级 diff（v0.11.0）**：变更源先取旧块，按 `(text, role, ts)` 复用未变块的向量，只把新块送嵌入；行号变化不影响复用。实测 inbox 追加一行：新嵌 2 块 / 复用 55 块。

## 五、排除清单（.kbignore）

在实例根 `~/ssot/.kbignore` 写一行一 pattern（`#` 注释，`fnmatch` 语义，相对 root）：

```
# 敏感档案与生成物不入索引
knowledge/archive-sensitive/*
lines/_draft-*
```

重建索引时命中即跳过；适合放「不可入库」的历史档案或本机生成物。语料清洗规则与统计建议
另放 `sessions/corpus/_CLEANING.md`，保证「语料≠原文」可追溯。

## 五·二、断言库体检（P2 phase 0，只读）

```bash
python3 tools/sp_assert_audit.py            # 人读
python3 tools/sp_assert_audit.py --json     # 机读
python3 tools/sp_assert_audit.py --strict   # 有硬问题 rc=1
```

- 检查：重复编号、断号、缺 `status`、`已被取代但无 superseded_by`、断链、取代环、引用覆盖。
- 切块测算：当前 700/1400 字窗口有多少块跨多条断言、多少断言被切开；改成“一条 `## A` 一块”后多少块/超长。
- **只读**：不改 `assertions.md`、不改 schema、不重建索引；用于决定 P2-1 的切块与迁移成本。

**P2-1 状态层（v0.16 候选）**

```bash
python3 tools/sp_assert_meta.py --scan          # 从 Markdown 扫状态 → sidecar
python3 tools/sp_assert_meta.py --apply         # 写 knowledge/assertions.meta.json
python3 tools/sp_assert_meta.py --set A012 --status superseded --by A031 --reason "..."
```

- 机器状态放 sidecar，不重写 `assertions.md`；状态：`active / superseded / refuted / vacant / unknown`。
- `sp_index` 把 `assertions.md` 按“一条 `## A` 一块”切；>1400 字二次切分；`vacant` 跳过。
- `chunks` 增 `assertion_id/status/superseded_by`；旧库自动 `ALTER TABLE`；`sp_index_merge` 兼容旧分片。
- `sp_semantic` 结果带 `A编号/status`；active/unknown 优先，superseded 排后并标 `⚠ 已被 Axxx 取代`；`--active-only` 可隐藏。

**P2-2 取代提案**

```bash
python3 tools/sp_supersede.py --from-conflict          # 只读列出冲突
python3 tools/sp_supersede.py --propose A012 --by A031 --reason "旧路径" --apply
python3 tools/sp_supersede.py --confirm A012 --by A031 --reason "确认" --apply
```

- propose 只写 `knowledge/supersede-events.jsonl`；confirm 才写 sidecar（status=superseded）。
- 不自动改 Markdown 正本；人工确认是硬要求。

## 五·三、环境指纹（v0.16 候选）

```bash
python3 tools/sp_embed_bench.py --quick --json   # 输出 env: hardware_fp/model_fp/llama_version/backend
python3 tools/sp_index.py --status               # model: fp=...；与 BUILD.model_fp 不一致会提示 --full
```

- `sp_fingerprint.py` 是单一实现：硬件、模型 md5 前 12、llama-server 版本、backend。
- **只有 `model_fp` 是硬键**：模型文件（同一 GGUF）变了才需要 `--full` 重建；换机器、8GB→16GB、换 backend、llama build 变化都只是 **soft env**，不失效向量。
- `BUILD.json` 记 `model_fp/llama_version/backend/hardware_fp`；`--status` 把 `model` 标 `[hard]`、`env` 标 `[soft: 只影响性能/bench]`。
- 指纹只用于“环境同一性/漂移提示”，不作吞吐 SLA；bench 仍应取多次中位数。

## 五·四、S0 敏感层与可选脱敏（v0.16 候选）

> 关键事实：**索引干净 ≠ 归档干净**。S1 转换会脱敏，但 `evidence/*/S0-archive/` 是原文。

```bash
# 只读预览：哪些 S0 文件含密钥形态（不打印内容）
python3 tools/sp_archive.py --scrub --dry --only pi
# 归档时脱敏（copy-on-write；源文件字节不变；不是 hardlink）
python3 tools/sp_archive.py --scrub --apply --only cc --since 30d
# 全库巡检（只报文件数/样本路径，写 alerts/s0-scan.json）
python3 tools/sp_s0scan.py --write-state
```

- `--scrub` 默认关闭；开启后该文件是实体副本（不能 hardlink），磁盘会增加。
- 已 scrubbed 的文件按 `src_mtime+size` 幂等跳过；`--rescrub` 强制重写。
- 二进制/超大文件不脱敏，manifest 记 `scrubbed: false` 与 `note`。
- `sp_s0scan` 由 steward 每周跑一次；`ssot_check` 显示 `[archive] S0 密钥形态 x/y 文件 · policy=high/scrub=off`。
- `profile/evidence-policy.json` 记 `sensitivity:high / scrub_default:false / scan_interval_days:7`；默认保留原文。
- `evidence/` 视同敏感层：`tmutil addexclusion ~/ssot/evidence`（或同步工具排除）；不要提交到公开仓。
- 只想验某个源：`sp_s0scan.py --only pi`（只报该 harness 的计数/路径）。

## 五·七、pending-index 交接（v0.17 候选）

```bash
sp_convert.py --src cc --incremental     # 结束写 S2-index/pending-index.json（sessions/est_blocks）
sp_index.py --plan --json                # pending_sources / pending_blocks（精确）
sp_pending.py --decide --json            # run | defer | skip
sp_pending.py --status                   # 标记内容
```

- steward 每次窗口先 `--decide`：pending=0 跳过；低于阈值执行；超阈值/窗口外只记 `index: deferred`。
- 阈值/窗口可用 `profile/steward-index.json`（`{threshold, window, force}`）或 env `SSOT_STEWARD_INDEX_THRESHOLD/WINDOW/FORCE`。
- `sp_index` 成功按 generation 清标记；索引期间又来新转换则保留。
- `--no-pack` 不清标记，标 `pack_stale:true`；`--pack-only` 且 pending=0 才清。
- `ssot_check [pending-index]` 显示未结算规模；不依赖 `[build]` 的 commit 落后。

## 五·六、P4 退休候选（只读）

```bash
python3 tools/sp_semantic.py "<查询>"          # 自动记 topk_paths/topk_sids（cap 20）
python3 tools/sp_semantic.py "<敏感查询>" --no-log   # 本次不写日志
python3 tools/sp_retire_candidates.py --days 180    # 零命中候选，只报告
```

- 日志在 `S2-index/search-log.jsonl`（本机 600 权限）；只记路径/sid，不记正文。
- 零命中 ≠ 无价值；报告只作候选，人工确认后走 `sp_exit.py`。
- 不做全局 TTL；P4 只解决“看得到哪些源长期没被检索”。

## 五·五、索引生命周期（分类与退出，v0.15 候选）

**分类摄入（opt-in）**

```bash
python3 tools/sp_classify.py --init                 # 建 profile/index-policy.json（默认 enabled，无规则）
python3 tools/sp_classify.py --scan                 # 预览：每条 S1 的 class/reason
python3 tools/sp_classify.py --scan --heuristic     # 只作为候选，不要直接 apply
python3 tools/sp_classify.py --apply                # 按 rules 写入 meta（幂等）
python3 tools/sp_classify.py --set <sid8> --class monitor --reason "钉钉值守"
python3 tools/sp_index.py --plan                    # 看 include/skip 与 would-remove
python3 tools/sp_index.py --apply-policy            # 显式删 policy 跳过的块
```

- class：`human / automation / monitor / decision / unknown`，缺省 human。
- 规则优先、启发式只作建议；含真实决策的自动化会话必须人工改回。
- `--all-classes` 可强制全量索引；`--class c1,c2` 单类补录。
- 无 policy 文件 = 关闭（向后兼容）；`sp_coverage` 把 policy 跳过单列，不算缺口。

**退出（只删索引，不删 S0/S1）**

```bash
python3 tools/sp_exit.py --make-manifest --class monitor --out logs/exit.jsonl
python3 tools/sp_exit.py --retire logs/exit.jsonl --reason "值守会话" --apply
python3 tools/sp_exit.py --verify logs/exit.jsonl
python3 tools/sp_golden.py --capture --apply        # 退出前录基线
python3 tools/sp_golden.py --check                  # 退出后 recall 不退化
```

- 用 `meta.sid` 对账，不用目录名；`profile/retired.jsonl` 是追加式 tombstone，`sp_index` 永久跳过。
- 审计在 `logs/index-ops.jsonl`；`BUILD.json` 记 `policy/db_bytes/pack_bytes/retired_sources`。
- `--unretire <sid> --apply` 解除，下一次 `--incremental` 重新入索引。
- 物理空间不会立即下降；`--full-pack` 才压实。
- `golden-queries.jsonl` / `golden-baseline.json` 是**实例数据**（含真实 query 与 sid）；公开仓只放 `instance/profile/golden-queries.jsonl` 模板，`public-audit.sh` 会拒绝基线/退休表出现在 kit 根。
- **golden 由你的 agent 自己产出**：`sp_golden.py --init` → `--suggest`（从本机 lines/断言标题出候选）→ 补 `expect_sids` → `--capture --apply` → `--check`。kit 只负责机制，不携带任何真实基线。

## 六、常驻服务（可选）

在**系统件仓库根**执行（仓库位置见 `~/ssot/profile/.kit-path`）：

```bash
bash scripts/install-service.sh --dry     # 只打印将生成的单元文件
bash scripts/install-service.sh           # macOS=launchd / Linux=systemd --user，开机自启
```

服务名 `com.ssot.embed`；日志 `/tmp/ssot-embed.log`。安装前确保 `llama-server` 在 PATH
（或传 `--llama /path/to/llama-server`）。

## 七、已知坑

- fp16 → 静默 NaN（见上）
- 太老的 llama.cpp 可能不支持该模型架构——报错就升版本
- 服务挂了（端口无响应）时，`sp_index` / `sp_semantic` 会明确报错，不会静默降级
- 超长单行（如 240KB JSON 粘贴）曾导致嵌入 500 → 进程崩溃；现版对超长行硬切（≤1600 字符）并对失败块拆批重试/计数跳过
