# ACCEPTANCE · v0.4.2 读侧自动化与门禁

> 日期：2026-10-21 ｜ 环境：隔离 HOME `/tmp/fh3`（临时实例 + 临时 settings）｜ **未触碰真实 hooks 与 opencode 插件**
> 目的：证明 hooks / Stop 草稿 / 6h steward / 发布门禁在干净实例上可安装、可去抖、可卸载，且不污染检索索引。

## 验收矩阵

| # | 项 | 方法 | 结果 |
|---|---|---|---|
| 1 | setup 展开 | `HOME=$T bash scripts/setup.sh --root $T/ssot` | hooks / recall-phrases / session-gate 均落位 |
| 2 | hooks 安装 | `install-hooks.sh --settings $T/.qoder/settings.json` | 新增 SessionStart/UserPromptSubmit/Stop；原有 SessionStart 保留 |
| 3 | hooks 幂等 | 再跑一次 install | 三事件各 1 组，无重复 |
| 4 | hooks 卸载 | `--uninstall` | 只移除 ssot-kit 条目；原有 hook 保留 |
| 5 | SessionStart | 在带 `.memory/context.md` 的目录跑 hook | 输出 SSOT 指针 + 检索命令 + 现场态 |
| 6 | UserPromptSubmit | 临时实例建 17 块小索引；命中「还记得上次…」 | 注入 top-3（path:line），非回忆句静默 |
| 7 | Stop 去抖 | 同 sid 连发两次（debounce=600）→ 1 行；sleep 2 后 debounce=1 再发 → 2 行 | 通过；sidechain 不写 |
| 8 | 发布门禁 | 无行 → exit 1；补 registry 行 → exit 0；缺 sid → exit 2 | 通过 |
| 9 | 6h steward | `SSOT_STEWARD_SKIP_INDEX=1` 跑一次 | 记录 index 跳过、自查结论、pending 草稿数 |
| 10 | steward timer | `install-steward.sh --dry` + `plutil -lint` | plist 合法；StartInterval=21600 |
| 11 | 索引卫生 | `kb_index` 对含 `_pending/`、`.kbignore` 的临时根 | `_pending`/skip 块=0；删除源后孤儿块=0 |

## 复现命令（摘）

```bash
T=/tmp/fh3
HOME=$T bash scripts/setup.sh --root $T/ssot --skills-dir $T/skills
HOME=$T bash scripts/install-hooks.sh --root $T/ssot --settings $T/.qoder/settings.json
HOME=$T bash scripts/install-hooks.sh --uninstall --root $T/ssot --settings $T/.qoder/settings.json
printf '{"session_id":"abcd1234","cwd":"/tmp","isSidechain":false}\n' \
  | HOME=$T SSOT_ROOT=$T/ssot SSOT_DRAFT_DEBOUNCE=600 bash $T/ssot/tools/hooks/stop-draft.sh
HOME=$T SSOT_ROOT=$T/ssot bash $T/ssot/tools/session-gate.sh publish --sid abcd1234
HOME=$T SSOT_ROOT=$T/ssot SSOT_STEWARD_SKIP_INDEX=1 bash $T/ssot/tools/steward.sh
HOME=$T bash scripts/install-steward.sh --dry --root $T/ssot
```

## 未在本轮实测 / 边界

- **未实际加载 launchd/systemd timer**：本机已有现役 `com.ssot.steward`，用同一 label 加载临时实例会覆盖真实值守；只做 dry + `plutil -lint`，实际安装留给目标机。
- **未改开发机现役 hooks**：测试只在隔离 HOME 中运行；本批只把通用版放进 kit。
- **opencode 插件未改**：插件当前仍内嵌回忆句式副本；`tools/recall-phrases.json` 已是单一真源，插件下一轮改为读同一 JSON（插件启动时加载，改后需重启）。opencode 的 AGENTS.md 规则入口坑已在断言 A385。
- **8399 按需拉起**：hook 在模型存在且服务未起时会启动 `serve_embed.sh`；本轮隔离实例无模型，未实跑拉起路径（真实机器 8399 已在跑）。
