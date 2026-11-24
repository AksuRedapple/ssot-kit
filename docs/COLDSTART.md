# COLDSTART · 冷启动与升级后的 60 秒自检

> 目标：让「体检绿」和「冷启动真的能用」是同一件事。
> 适用：新装、升级后、换 harness 后、以及 agent 接手一条旧实例时。
> 一键：`bash scripts/coldstart-check.sh`（在 kit 克隆目录里跑；`--strict` 把警告也判失败）。

## 1 四条断链（症状 → 原因）

| 症状 | 可能原因 | 检查 |
|---|---|---|
| agent 搜不到最近知识，但磁盘上有 | 开机/START 仍指向 legacy 工具或旧库 | `grep -n "tools/" profile/harness-boot.md START.md`；看是否指向 `tools/legacy/` |
| `sp_semantic` 报 `ModuleNotFoundError: No module named 'ssotlib.index'` | 升级只拷了 `ssotlib/*.py`，漏子包 | `ls tools/ssotlib/index/__init__.py`；跑 `update.sh` 修复 |
| `sp_semantic` 报 `numpy` 缺失 | `python3` 解析到不带 numpy 的解释器（launchd/非登录 shell 常见） | `python3 -c 'import numpy'`；不行就 `export SSOT_PY=...` |
| 体检 `[build]` 与冷启动用的库不是同一个 | legacy 库与 S2 并存，体检只看 S2 | 看 `S2-index/semantic/active.json` 与 `kb-index/BUILD.json` 是否同时存在 |
| MEMORY.md 被截断 | 体积超过 harness 注入上限（约 24–25KB） | `wc -c ~/.qoder/memory/MEMORY.md`；超了跑 `sp_compile --mem` |
| 线页写着「已结/搁置」却被当成活跃 | `sp_line_status` 词表只有 `暂停/完成/活跃` | 先 `sp_line_status.py --dry-run` 看计划，不要直接 `--apply` |

## 2 60 秒自检

在 kit 克隆目录：

```bash
bash scripts/coldstart-check.sh
```

它只做五件事，不改实例：

1. **解释器**：`python3`（或 `SSOT_PY`）能否 import numpy；
2. **指令引用**：`profile/harness-boot.md` 与 `START.md` 里的 `tools/*` 是否存在、是否落在 `tools/legacy/`；
3. **索引**：S2 `active.json` 指向的版本 BUILD 是否存在；有没有并存的 legacy 库；
4. **预算**：`MEMORY.md` 体积、线页过期数、`已结/搁置` 状态词；
5. **汇总**：阻断项非零退出，警告只提示。

手动等价命令：

```bash
python3 -c 'import sys,numpy; print(sys.version.split()[0], numpy.__version__)'
python3 ~/ssot/tools/ssot_check.py
grep -RnoE 'tools/[A-Za-z0-9_./-]+\.(py|sh)' ~/ssot/START.md ~/ssot/profile/harness-boot.md
ls ~/ssot/tools/ssotlib/index/__init__.py
```

## 3 解释器契约

**不要假设 `python3` 就是那个带 numpy 的 python。** macOS 上至少有三类：

- `~/.zshenv` / Homebrew 的 `python3`（交互 shell 常见，通常带 numpy）；
- `/usr/bin/python3`（系统 Python，视安装而定）；
- launchd、cron、hook 启动时拿到的最小 PATH。

约定：

```bash
# 找到带 numpy 的解释器后，写进当前 shell / launchd 环境
export SSOT_PY="$(command -v python3)"
"$SSOT_PY" -c 'import numpy'
```

- 文档里的 `python3` 命令，若你的环境不满足，替换成 `"$SSOT_PY"`；
- 语义检索、索引、`sp_compile` 必须用同一个解释器；
- 出现 `numpy` 缺失时，先修解释器，不要重装索引。

## 4 指令层：boot / START 只认当前工具

- 开机块正本：`profile/harness-boot.md`；读档入口：`START.md`。
- `update.sh` **不动内容层**（这是设计），所以旧实例的 boot/START 可能仍指向 `tools/legacy/` 下的工具。
- 判据：boot/START 里出现的每个 `tools/*.py` 都必须存在，且不得位于 `tools/legacy/`。
- 修复顺序：先 `coldstart-check.sh` 看命中 → 手工改 boot/START（或等 `update.sh --migrate-boot` 的显式迁移）→ 再跑一次自检。
- 不要把 `tools/legacy/` 的工具写回 boot；legacy 只用于回溯与一键恢复。

## 5 索引：active 才是冷启动用的那个

- 唯一在线指针：`S2-index/semantic/active.json` → `versions/<ver>/BUILD.json`。
- `ssot_check` 的 `[build]` 读的是 active；`coldstart-check.sh` 也按 active 解析。
- 如果还有 `kb-index/BUILD.json` 或 `S2-index/kb/`，说明 legacy 双栈还在：
  - 先确认 boot/START 是否还指向 legacy；
  - 确认不需要后，再按 `sp_exit`/迁移流程退役；不要直接删目录。
- 索引落后（源比 `built_at` 新）时：`sp_index.py --incremental`；全量会先清库，先备份。

## 6 预算与线页

- `MEMORY.md` 硬限约 25KB（`sp_compile.HARD_LIMIT`），告警线 24KB；超限时 `--deploy` 会拒切，不会写坏入口。
- 线页超过 30 天未更新 → 先读状态行与 `最近:`，确认是「真的停了」还是「只是没写日期」。
- `sp_line_status.py` 默认 dry-run；`--apply` 前先看逐页计划，避免把「已结/搁置」统一改成「活跃」。

## 7 升级后的顺序（推荐）

```bash
KIT="$(cat "$HOME/ssot/profile/.kit-path" 2>/dev/null || echo "$HOME/ssot-kit")"
cd "$KIT" && git pull --ff-only
bash tools/install/update.sh --root ~/ssot      # 框架层；含 ssotlib/** 递归
bash scripts/coldstart-check.sh                 # 本文件
python3 ~/ssot/tools/ssot_check.py              # 体检单
```

- `update.sh` 不改内容层；boot/START/线页要改时显式 `--apply`。
- 升级后若 `[install-drift]` 报缺文件，先重跑 `update.sh`，不要手工 cp 单个文件。
- 语义层升级后，先 `--status`/`--check` 确认解释器与索引版本，再重建。

## 8 给 agent 的开工块（可粘贴进 boot）

```text
冷启动先跑：bash scripts/coldstart-check.sh（kit 目录）或等价五查：
解释器 numpy / boot-START 引用存在且非 legacy / S2 active 存在 / MEMORY <24KB / 线页无过期。
任一失败：先修，不要用停更的 legacy 库回答“最近”。
```

## 9 相关

- [QUICKSTART](QUICKSTART.md)：安装/升级的最短路径
- [UPGRADE](../UPGRADE.md)：update.sh 同步清单
- [SEMANTIC](SEMANTIC.md)：嵌入服务与索引
- [HOOKS](HOOKS.md)：SessionStart / Stop 钩子
- [PROTOCOLS](PROTOCOLS.md)：会话与知识协议
