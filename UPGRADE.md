# UPGRADE · 升级指南（工作机侧 / 下游）

> 上游（macmini）持续迭代系统件；本机**只 pull**，一条命令升级。

## 升级（一条命令）

```bash
KIT="$(cat "$HOME/ssot/profile/.kit-path" 2>/dev/null || echo "$HOME/ssot-kit")"
cd "$KIT" && git pull && bash scripts/update.sh
```

> 仓库可放任意路径（首装时记录在 `~/ssot/profile/.kit-path`）；升级后该指针会自动刷新。

**会更新（框架层，直接覆盖）：**
- `~/ssot/tools/` ← 仓库 `tools/`
- `~/.qoder/skills/<框架技能>/` ← 仓库 `skills/`（如 `ssmap`）

**不会动（内容层，永不覆盖）：** `~/ssot/` 下 `lines/`、`knowledge/`、`inbox/`、`sessions/`、`profile/` 的已有文件——你的台账与知识原样保留。

**模板层（`instance/` → `~/ssot/`）：只补缺**——本机不存在的文件才会拷入，已有文件绝不覆盖。

## 升级后

1. 看 `CHANGELOG.md`（本仓库）了解这轮变化；版本号见 `VERSION`
2. 若变更涉及协议（CHANGELOG 会标注），开机块/技能已在 update 中同步，无需手工操作
3. 建议升级后跑一次自查：`python3 ~/ssot/tools/ssot_check.py`
4. **可选自动化**：`update.sh` 同步 `tools/hooks/`、`tools/steward.sh`、`tools/session-gate.sh`，但**不会**自动改 settings 或定时器；需要时显式跑
   `bash scripts/install-hooks.sh` / `bash scripts/install-steward.sh`（先 `--dry`；卸载加 `--uninstall`）。详见 `docs/HOOKS.md`。

## 发提案（痛点 → 上游）

工作机使用中的痛点/改进想法：把下面三样**告诉用户带回去**，不要带任何业务内容或真实数据——

1. 痛点描述（我要做什么事、卡在哪里）
2. 期望行为（希望系统怎么表现）
3. 复现步骤（怎么触发）

上游处理后写进 `CHANGELOG.md` 的「工作机提案」区；下次 `git pull` 即可拿到改进。

## 排错（实战教训）

### 「假绿」：长任务不要用 `| tail` 包管道

`python3 kb_index.py | tail` 会掩盖进程 exit code——索引进程崩溃了，日志末尾也可能像正常结束。
**完成判定 = 制品侧四证**：① 产物存在 ② 数量/块数对 ③ 抽样检索命中 ④ `echo $?` 为 0。
长任务直接跑或 `; echo exit=$?`，不要只信日志最后一行。

### 文件被脚本清空：四源重建法

改写脚本若把 `open(p,'w').write(open(p).read()...)` 写在一起，会**先截断后读**，整份文件清空。
恢复优先级（四源）：① 会话原稿（聊天记录里的完整版本）→ ② 操作留痕（剔除清单/中间导出）
→ ③ 汇总产物（派生文件）→ ④ 逐条编辑记录。
重建后做**五证校验**：总数对 / 删除项不在 / 关键新增在 / 关键旧项在 / 格式行完整。

## 纪律

- 只 pull、永不 push；不改动仓库文件
- 内容层（`~/ssot/` 的个人/工作材料）永不外发
## 工作机升级到 v0.7.0（2026-11-03 起）

老版本实例（已装过 0.5/0.6）**不需要重装**，pull + 一个脚本即可：

```bash
cd <ssot-kit 克隆目录>
git pull --ff-only
bash tools/install/update.sh --root ~/ssot    # 实例不在 ~/ssot 就改 --root
```

`update.sh` 依次做：

1. `git pull --ff-only`（在克隆目录里；失败即停，实例不动）
2. `sp_migrate.py --to current`（**存在才跑**；0.7.0 无破坏性变更，可跳过）
3. `ssot_check.py`（输出体检，末尾 `== 完成 ==（健康）` 为通过）

它**只覆盖框架层**（`tools/`、`hooks/`、`skills/`、`scripts/`），
**不动内容层**（`lines/`、`knowledge/`、`inbox/`、`sessions/`、`profile/`、`evidence/`）。

### 0.7.0 落地后你能用到的

| 新件 | 用法 | 可见信号 |
|---|---|---|
| `tools/sp_takeover_lint.py` | `python3 tools/sp_takeover_lint.py` | `ssot_check` 多一行 `[takeover] …` |
| `tools/sp_line_status.py` | `python3 tools/sp_line_status.py`（dry）`--apply`（写回） | 每条线页顶部生成「现在时」状态行 |
| `tools/sp_assert_ingest.py` | `python3 tools/sp_assert_ingest.py --dir <草稿目录> --apply` | 断言连续编号入册，撞正本 0.88 |
| `tools/install/{setup,update}.sh` | 首装/升级（多 harness 探测、`--dry` 预演） | `--dry` 只打印不落盘 |
| `sp_coverage.py` dsh 口径 | `python3 tools/sp_coverage.py` | 冒烟/空会话不再算缺口 |

### 验收（升级后跑这三条）

```bash
python3 tools/sp_takeover_lint.py | head -1     # 期望: 21 页 · … · 断链 0
python3 tools/ssot_check.py | grep -E "takeover|build|完成"
bash tools/tests/run_all.sh tools/tests --fast  # 期望: fail=0
```

### 回滚

```bash
cd <ssot-kit>
git checkout v0.6.0          # 或上一版 tag
bash tools/install/update.sh --skip-pull
```

内容层从未被改，回滚只影响工具。

## v0.9.x 契约迁移（0.7.0 → 0.9.x 必读）

v0.9.0 起引入**实例数据契约**：`profile/contract.json`（`contract: 2`）。升级顺序固定为三步：

```bash
# 1) 看现状(只读):当前契约、产物 schema 分布、漂移
python3 ~/ssot/tools/sp_schema_check.py
python3 ~/ssot/tools/sp_migrate.py --status

# 2) 预演(不写盘):将改多少份
python3 ~/ssot/tools/sp_migrate.py --to 2 --dry-run

# 3) 实升(自动 tar 备份;失败不留半迁移;可 --resume)
python3 ~/ssot/tools/sp_migrate.py --to 2 --apply
python3 ~/ssot/tools/sp_schema_check.py     # 期望:✅ 全部一致
```

**契约文件从哪来**：`tools/install/update.sh` 同步框架件时会带 `profile/contract.json` 模板；若实例里没有，`sp_migrate --status` 会按旧实例处理并提示。

**守卫拒跑怎么办**：写工具报「实例契约 v1 < 工具要求 v2」时，不是 bug——先跑第 3 步迁移；迁移后仍报错，把 `python3 tools/sp_schema_check.py --json` 的输出发给上游。

**索引不需要迁移**：向量包是派生物，迁移只碰 S1 `meta.json` / 账本 / `BUILD.json`；索引不可用就重建（`sp_index.py --incremental`）。

**回滚**：迁移前自动备份在 `~/ssot/backups/pre-migrate-*.tar.gz`；恢复该 tar 即回到迁移前（索引仍需重建）。

## 0.12.0 迁移（一次性，做一次就够）

升级到 0.12.0 后，索引目录仍是 `S2-index/semantic/index.db`（legacy 单库）——**功能不受影响**。
要切到版本化布局，跑一条：

```bash
python3 ~/ssot/tools/sp_index.py --adopt      # 把现有单库收编成第一版，并切 active
python3 ~/ssot/tools/sp_index.py --status     # 应显示 active: <时间戳>-<sha>
```

之后：

- **日常增量**：`sp_index.py`（裸跑即可，默认已是增量）；
- **全量重建**：`sp_index.py --build`（建新版本，完成自动切；线上全程可用）；
- **出问题**：`sp_index.py --rollback`（秒级，不重建）；
- **旧行为**（清库重建，不推荐）：`sp_index.py --build` 已取代它；没有保留"就地清库"入口。

> 回滚兜底：升级前建议 `cp -c S2-index/semantic/index.db{,.bak}`（APFS clone 秒级）；有版本目录后不再需要手工备份。
