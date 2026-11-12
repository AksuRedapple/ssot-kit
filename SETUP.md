# SETUP · 首装指南（agent 执行）

> 目标：在当前 macOS 机器上把知识治理系统部署起来（实例 `~/ssot` + 技能 + 会话普查）。
> 请逐步执行，在关键节点停下与用户对齐。

## 规则（先读）

- 本仓库是**参考实现**：请勿把你的个人内容 push 回本仓库（需要改造就 fork）；发现问题欢迎开 issue / PR
- 产物落在 `~/ssot/` 与 `~/.qoder/skills/`；**绝不把内容外发到任何地方**
- 网络：如 GitHub 访问缓慢，按本机既有网络配置处理；**不要绕过组织或设备的网络策略**
- 不修改、不删除任何已有文件；模板层只补缺

## 前置

- macOS + `python3` ≥3.10 + `git` + `numpy`（`pip install numpy`）；若本机会话不在 Qoder，普查改用其自带的会话列表工具
- 平台：macOS ✅ 已实测；Linux 可用（把 launchd 换成 systemd --user）；Windows 未验证

## 步骤

### 1. 取得仓库
仓库可放任意路径（下例用 `SSOT_KIT_DIR`，默认 `~/ssot-kit`）：
```bash
KIT="${SSOT_KIT_DIR:-$HOME/ssot-kit}"
git clone https://github.com/AksuRedapple/ssot-kit "$KIT" 2>/dev/null || (cd "$KIT" && git pull)
```
安装后实际路径会写入 `~/ssot/profile/.kit-path`，模板与技能都按它找仓库。

### 2. 展开实例 + 装技能
```bash
KIT="${SSOT_KIT_DIR:-$HOME/ssot-kit}"   # 与第 1 步同一个路径
bash "$KIT/tools/install/setup.sh"
```
→ 生成 `~/ssot/`（START/lines/sessions/knowledge/inbox/profile/tools），装 `ssmap` 技能到 `~/.qoder/skills/`。

### 3. 装「开机块」（v0.3 起：直接薄壳下发）

> ⚠️ **这一步会整体替换你现有的 agent 记忆入口**（默认 `~/.qoder/memory/MEMORY.md`）。前版会自动备份到 `~/ssot/compile/`，但请先读 [docs/UNINSTALL.md](docs/UNINSTALL.md) 的恢复步骤再执行。
> 非 Qoder 用户用 `--target` 指定落点（见 §6）。

```bash
python3 ~/ssot/tools/sp_compile.py --mem --deploy
```
→ 落点变为编译薄壳（表头 + SSOT 段 + 开机块；开机块正本来自 `~/ssot/profile/harness-boot.md`）。
**不要手工编辑它**；改纪律 → 改 `profile/harness-boot.md` → 重编译下发。

**恢复原状**：`ls ~/ssot/compile/MEMORY.*.bak-*` 找备份 → `cp` 回原路径 → 删除 `~/ssot/compile/MEMORY.candidate.md`。

### 4. 存量普查（核心）
1. `python3 ~/ssot/tools/scan_sessions.py > /tmp/ssmap-scan.tsv`
2. 按 `docs/SSMAP.md` §三 聚类 → 草稿 `~/ssot/sessions/registry.md` + `~/ssot/lines/<线名>.md`
3. 「总览」给用户：几条线/每线几会话/哪些拿不准 —— **停下等确认** → 定稿

### 5. 自测两条回路
模拟「我要在〈某条线〉开新需求」走开工三问；模拟一次会话收尾记一行。结果贴给用户。

### 6. （可选）薄壳编译
```bash
python3 ~/ssot/tools/sp_compile.py --mem --deploy
```
→ 把 `~/ssot` 正本编译成 agent 记忆薄壳（`~/.qoder/memory/MEMORY.md`）。前版自动备份到 `~/ssot/compile/`。

### 7. （可选）语义检索层
按 `docs/SEMANTIC.md`：拉本地嵌入模型 → 起服务 → 建索引。

### 8. （可选）读侧唤起 + 6h 值守
```bash
bash scripts/install-hooks.sh            # SessionStart / UserPromptSubmit / Stop 草稿
bash scripts/install-steward.sh          # 6h：索引增量 + 自查 + 草稿计数
```
- 先 `--dry` 预览；Claude 用 `--settings ~/.claude/settings.json`；卸载加 `--uninstall`。
- 不会自动改你的 settings/定时器，必须显式跑；详见 `docs/HOOKS.md`。
- 发布/交接前可跑门禁：`bash ~/ssot/tools/session-gate.sh publish --sid <id>`。

### 9. （可选）Pi / opencode 扩展路线
Pi 没有 shell hook，用全局扩展（开机注入 + 回忆触发检索）：
```bash
bash scripts/install-pi-extension.sh --dry
bash scripts/install-pi-extension.sh     # → ~/.pi/agent/extensions/ssot-boot.ts
```
- 配套：`~/.pi/agent/AGENTS.md` 加 SSOT 指针；skill 根用 `~/.pi/agent/skills`（单根；`~/.agents/skills` 留空）。
- opencode 插件同理；两者契约与验证命令见 `docs/HOOKS.md` §六/§七。

## 兜底

哪一步在本机行不通（工具不同/路径不同/权限/网络限制），**不要硬做、不要绕**——停下报告：卡在哪、你建议怎么改。
