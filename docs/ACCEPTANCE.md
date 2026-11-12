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
