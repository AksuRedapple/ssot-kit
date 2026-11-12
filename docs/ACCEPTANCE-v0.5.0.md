# ACCEPTANCE · v0.5.0 可信度与新鲜度

> 日期：2026-10-21 ｜ 环境：mini 实例 `~/ssot` + 隔离 HOME `/tmp/fh5`（kit）｜ 只读验收，未改 mini hooks

## 验收矩阵

| # | 项 | 方法 | 结果 |
|---|---|---|---|
| 1 | conf 格式 | `instance/inbox/README.md` / `docs/PROTOCOLS.md` / 卡片模板 | 行格式含 `conf: 实测|推断|待核`；缺省允许 |
| 2 | conf 覆盖 | `ssot_check` 扫 inbox 行 | mini：`2/177`（新写入的 v0.5 两行带 conf）；kit：`0/0` |
| 3 | 断言 lint | `ssot_check` 解析 `^## A(\d+)` | mini：**399 条 / 最新 A388 / 重复 16（146,175,178-179,206,304,320,332-339）/ 缺号 5（326-330）/ 标签 71**；只报不改号 |
| 4 | built_at_commit（壳） | `sp_compile --mem` 头 + report | `正本 commit a81e3ad`；`--mem --deploy` 后现役 MEMORY 5,321B，`--check` 通过 |
| 5 | built_at_commit（索引） | `sp_index` 写 `S2-index/semantic/BUILD.json` | `commit a81e3ad / chunks 271736 / built_at 2026-10-21T02:18:57+08:00` |
| 6 | 检索头显示 commit | `sp_semantic "A381…"` | 首行含 `· commit a81e3ad ·`；hook 的 `tail -n +3` 不受影响 |
| 7 | SSOT_REPORT | `ssot_check --report ~/ssot/SSOT_REPORT.md` | 生成短线/登记/inbox/断言/索引/草稿/演练 8 行；kit 临时实例同命令通过 |
| 8 | 索引落后检测 | 读取 BUILD.commit 与 `git rev-parse HEAD` | 当前一致；落后时报告 `落后 N commits`（实现存在，未制造落后） |
| 9 | kit 端复现 | `/tmp/fh5` 首装 + `kb_index` + `ssot_check --report` + `sp_compile --mem` | `kb-index/BUILD.json` 16 块；报告生成；壳头 `commit -`（非 git 根，预期） |
| 10 | 隐私闸（开发实例） | `sp_index --incremental` 扫当前 27 万块 | 通过（无完整密钥形态）；命中时拒绝索引并提示 `--allow-secret-files` |
| 11 | 隐私闸（kit） | 临时根放一个含 `ghp_…` 的文件 | 完成行 `🔒 1 文件因密钥形态跳过`；该路径 chunks=0，正常文件照常索引 |

## 复现命令

```bash
# mini
python3 ~/ssot/tools/ssot_check.py --root ~/ssot --report ~/ssot/SSOT_REPORT.md
python3 ~/ssot/tools/sp_compile.py --mem --deploy
python3 ~/ssot/tools/sp_index.py --incremental   # 写 BUILD.json
python3 ~/ssot/tools/sp_semantic.py "A381 是什么断言" --top 1

# kit（隔离）
T=/tmp/fh5; HOME=$T bash scripts/setup.sh --root $T/ssot --skills-dir $T/skills
HOME=$T python3 tools/kb_index.py --root $T/ssot --db $T/ssot/kb-index/kb.db --full
HOME=$T python3 $T/ssot/tools/ssot_check.py --root $T/ssot --report $T/ssot/SSOT_REPORT.md
HOME=$T python3 $T/ssot/tools/sp_compile.py --mem
```

## 边界

- `SSOT_REPORT.md`、`S2-index/semantic/BUILD.json` 是生成物，已进开发实例 `.gitignore`；不入版本库。
- 断言 lint 只报号不自动重排；修复编号需另立专项（会牵动正文引用）。
- `built_at_commit` 只说明索引对应的正本提交；索引落后时报告 `落后 N commits`，不自动重建。
- 本轮未改开发机现役 hooks；`SSOT_REPORT` 由 `steward.sh` 每 6h 生成，首次已手工跑通。
