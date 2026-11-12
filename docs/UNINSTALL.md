# 干净退出（卸载 / 恢复原状）

> 目标：把本系统装过的东西全部撤掉，或只恢复"被替换的 agent 记忆入口"。
> 顺序建议：先恢复记忆入口 → 再卸服务 → 最后处理实例目录。

## 0 先备份

```bash
tar -czf ~/ssot-backup-$(date +%Y%m%d).tgz -C ~ ssot
```

## 1 恢复 agent 记忆入口（最重要）

编译薄壳会替换你原来的入口文件（默认 `~/.qoder/memory/MEMORY.md`）。

```bash
ls -lt ~/ssot/compile/ | grep -i "MEMORY.*bak"     # 找前版备份
cp ~/ssot/compile/MEMORY.<时间戳>.bak-* ~/.qoder/memory/MEMORY.md
```

若没有备份：把 `~/.qoder/memory/MEMORY.md` 删掉即可——它只是入口，知识在 `~/ssot` 正本里，没有丢失。

## 2 卸常驻服务

```bash
# 语义服务（embedding）
bash tools/install/install-service.sh --uninstall
# 值守（steward）
bash tools/install/install-steward.sh --uninstall
# 或手动
launchctl unload ~/Library/LaunchAgents/com.ssot.*.plist 2>/dev/null
```

## 3 卸 hooks（如果你装过）

```bash
bash scripts/install-hooks.sh --uninstall        # 按其提示确认
```

## 4 卸技能

本系统安装的技能都在 `~/.qoder/skills/`（或你指定的 skills 目录）。删掉对应目录即可，例如：

```bash
ls ~/.qoder/skills | grep -E "ssot|ssmap|memo|session"
rm -rf ~/.qoder/skills/<逐个确认后的目录>
```

## 5 处理实例目录

`~/ssot` 里分两类东西：

| 类型 | 路径 | 建议 |
|---|---|---|
| 你的内容 | `lines/ knowledge/ inbox/ sessions/ evidence/` | **导出保留**（这是你的资产） |
| 系统件/派生 | `tools/ hooks/ skills/ S2-index/ compile/` | 可直接删 |

```bash
# 只保留内容
mkdir -p ~/ssot-keep && cp -R ~/ssot/{lines,knowledge,inbox,sessions,evidence} ~/ssot-keep/
rm -rf ~/ssot
```

## 6 验证已退干净

```bash
curl -s -m 2 http://127.0.0.1:8399/health || echo "embedding 服务已停"
launchctl list | grep -i ssot || echo "无 ssot 常驻"
grep -RL "" ~/.qoder/memory/MEMORY.md >/dev/null 2>&1; head -3 ~/.qoder/memory/MEMORY.md 2>/dev/null || echo "记忆入口已恢复/删除"
```
