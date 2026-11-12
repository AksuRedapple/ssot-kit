# HOOKS · 读侧唤起、Stop 草稿与 6h 值守

> 三层自动化，全部可选、全部本地、全部可卸载。目标不是「更多 hook」，而是把三件靠自觉的事降成结构：
> 开局知道去哪读、回忆时真的去查、收尾不漏记。
> 没有 shell hook 的 harness 走**扩展/插件路线**：opencode（§六）、Pi（§七）。

## 一、三个 hook

| 事件 | 脚本 | 做什么 | 不做什么 |
|---|---|---|---|
| `SessionStart` | `tools/hooks/session-start.sh` | 注入 SSOT 指针、检索命令、项目 `.memory` 现场态 | 不注入长文、不跑检索 |
| `UserPromptSubmit` | `tools/hooks/user-prompt-retrieval.sh` | 命中「还记得/上次/之前」等句式才查 top-3 并注入 | 不每轮查、不推送 |
| `Stop` | `tools/hooks/stop-draft.sh` | 同 sid 去抖（默认 600s）写一行机械草稿到 `sessions/_pending/<sid8>.md` | 不写「干到哪了」、不做语义判断 |

安装（Qoder）：

```bash
cd <系统件仓库>
bash scripts/install-hooks.sh
```

Claude 用同一份脚本、换 settings：

```bash
bash scripts/install-hooks.sh --settings ~/.claude/settings.json
```

预览 / 卸载：

```bash
bash scripts/install-hooks.sh --dry
bash scripts/install-hooks.sh --uninstall
```

行为：幂等合并，保留 settings 里已有的其它 hooks；写入前自动备份 `settings.json.bak-<ts>`；`--dry` 不落盘、不打印既有配置内容。

## 二、Stop 草稿：只写机械事实

`Stop` 在多数 harness 里是**每轮**触发，不是会话结束触发。所以：

- 同 sid 默认 600 秒去抖（`SSOT_DRAFT_DEBOUNCE` 可改）；
- 只写 `时间 / sid / cwd`，**不写标题、不写正文、不做语义判断**；
- 子 agent（`isSidechain`）跳过；
- 关停：`touch $ROOT/.stop-draft-off` 或 `SSOT_STOP_DRAFT_OFF=1`。

草稿文件示例：

```
# a1b2c3d4 · 收尾草稿（机械事实，待转 registry）

- 2026-10-21 14:03:11 | sid: a1b2c3d4-... | cwd: /path/to/project
```

转正：周值班/收尾时读 `sessions/_pending/*.md`，把「这条线干到哪了」补成 registry 行；草稿本身不是台账。

## 三、6h 值守

```bash
bash scripts/install-steward.sh          # macOS=launchd / Linux=systemd --user
bash scripts/install-steward.sh --dry    # 只打印单元文件
bash scripts/install-steward.sh --uninstall
```

值守脚本 `tools/steward.sh` 每 6 小时做三件事：

1. 嵌入服务 8399 在 → `tools/sp_index.py` 增量索引；不在则跳过并记账；
2. `tools/ssot_check.py` 自查（登记册/inbox/线页/薄壳/索引）；
3. 统计 `sessions/_pending` 草稿数。

日志：`alerts/steward.log`；launchd/systemd 自身的 stdout/stderr 分别落 `alerts/steward.stdout.log` / `steward.stderr.log`。

## 四、发布/交接门禁

```bash
bash ~/ssot/tools/session-gate.sh publish --sid <会话id>
bash ~/ssot/tools/session-gate.sh handoff --sid <会话id>
```

- 0：当前 sid8 在 `sessions/registry.md` 有行；
- 1：无行 → 先补台账再发布/交接；
- 2：无法验证（缺 sid 或 registry）。

建议挂进发布脚本/交接清单的**入口**，而不是事后补。门禁只查「有没有这一行」，不判断这一行写得好不好。

## 五、回忆句式单一真源与 8399 按需拉起

回忆/取证句式放在 `tools/recall-phrases.json`（`regex` 字段）。kit hook 每次读它，缺文件才用内嵌 fallback——改词只改 JSON。

消费者现状：

| 消费者 | 状态 |
|---|---|
| `tools/hooks/user-prompt-retrieval.sh` | ✅ 已读 JSON |
| opencode `~/.config/opencode/plugins/ssot-boot.ts` | ✅ 已读 JSON（缺文件/坏 JSON 才回退内嵌副本；插件在进程启动时加载，改后需重启） |
| Pi `~/.pi/agent/extensions/ssot-boot.ts` | ✅ 已读 JSON（同上；改后 `/reload`） |

8399 不在时，UserPromptSubmit hook 会**按需拉起**：

- 仅当 `$ROOT/models/embeddinggemma-2-BF16.gguf` 与 `$ROOT/tools/serve_embed.sh` 都在；
- 用 `$ROOT/.embed-start.lock` 防重复拉起；最多等 5 秒，失败静默降级；
- 关掉：`SSOT_EMBED_AUTOSTART=0`；
- `tools/steward.sh` **只探测、不拉起**；与 opencode 插件/本 hook 并存时，重复 spawn 会因端口占用自然失败，不会破坏已起的服务。

## 六、opencode 接入契约

opencode 无 SessionStart hook，走插件（`~/.config/opencode/plugins/ssot-boot.ts`）：

- 开机注入复用 `session-start-context.sh`；**改输出格式不影响透传，改路径/文件名需同步插件常量**；
- 回忆触发读 `tools/recall-phrases.json`（缺文件/坏 JSON 才回退内嵌副本）；改词只改 JSON；
- opencode 专属规则写 `opencode.json` 的 `instructions`，**不要建全局 `~/.config/opencode/AGENTS.md`**——它会顶掉 `~/.claude/CLAUDE.md` 的回退链（本机实测，2026-10；详细记录属内容层，不在本仓库）；
- 插件按需拉起 8399 与本 hook 的 autostart 可并存；插件有 in-memory 去重，本 hook 有文件锁。

## 七、Pi 接入契约（扩展路线）

Pi 没有 CC/Qoder 的 shell hook，等价物是**全局扩展**（`~/.pi/agent/extensions/*.ts`，jiti 直跑，改完 `/reload`）：

```bash
bash scripts/install-pi-extension.sh --dry          # 预览
bash scripts/install-pi-extension.sh                # 装到 ~/.pi/agent/extensions/ssot-boot.ts
bash scripts/install-pi-extension.sh --uninstall    # 卸载
```

扩展做两件事（源码 `hooks/pi/ssot-boot.ts`）：

| 事件 | 做什么 | 不做什么 |
|---|---|---|
| `session_start` | 跑 `$ROOT/tools/hooks/session-start.sh`（与 shell hook 同源），结果缓存 | 不每轮重跑（cwd 变更才重跑） |
| `before_agent_start` | 把开机块写进 `systemPromptOptions.sections.ssot_boot`；命中回忆句式时跑 `sp_semantic --top 3` 写 `sections.ssot_recall` | 不返回 `systemPrompt`（整段替换、缓存不友好）；不拉起 8399 |

契约与要点：

- `ROOT` = `$SSOT_ROOT` 或 `~/ssot`；**改 `session-start.sh` 的输出格式不影响透传，改路径/文件名需同步扩展常量**；
- 开关：`SSOT_PI_BOOT=0`（全关）/ `SSOT_PI_RECALL=0`（只关检索）/ `SSOT_PI_VERBOSE=1`（日志）；日志 `~/.cache/ssot-pi-boot/debug.log`；
- 用户级入口另放 `~/.pi/agent/AGENTS.md`（Pi 自动作为 context file 加载）；skill 根走 `~/.pi/agent/skills` **单根**，`~/.agents/skills` 留空避免双根重名；
- 验证：`SSOT_PI_VERBOSE=1 pi -p --no-session --no-tools "把上下文中以 [SSOT] 开头的行原样输出"`；命中回忆句式应回 `path:line`。

## 八、边界与卫生

- 全部本地执行，不发外部请求；输出只进当前会话上下文。
- 运行依赖：`bash`、`python3`、`curl`；Stop 脚本必须快速返回，失败也不阻塞会话（统一 `exit 0`）。
- hook 是提醒，不是强制力；真正的强制力在门禁与发布流程。
- 升级 `update.sh` 只同步脚本，不会自动改 settings 或定时器——安装/卸载由你显式跑。
- 安装后用 `--dry` 或隔离 HOME 先验，再应用到现役配置：

```bash
TMP=$(mktemp -d)
HOME=$TMP bash scripts/setup.sh --root $TMP/ssot --skills-dir $TMP/skills
HOME=$TMP bash scripts/install-hooks.sh --root $TMP/ssot --settings $TMP/.qoder/settings.json
HOME=$TMP bash scripts/install-steward.sh --dry --root $TMP/ssot
```
