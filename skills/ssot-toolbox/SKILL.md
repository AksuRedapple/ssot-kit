---
name: ssot-toolbox
description: SSOT 工具统一手册（何时用/命令/判据/坑）｜触发: ssot 工具/工具怎么用/四层文档
---

# ssot-toolbox · SSOT 工具手册

> 工具存在 ≠ 可用：没有手册的工具，等于只有作者本人会用。本手册只列**随包分发**的工具。

## 0 怎么用

1. 先看总表找到工具 → 2. 看该工具的「何时用 / 命令 / 判据」→ 3. 跑之前先看「坑」

## 1 总表（按任务类型）

| 我要… | 工具 | 一句话 |
|---|---|---|
| 按预算给新会话注入上下文 | `tools/sp_dispatch.py` | 三级分发：pointer/summary/full |
| 搜旧事（按意思） | `tools/sp_semantic.py` | 向量检索，`--expand` 别名扩展 |
| 重建/增量更新索引 | `tools/sp_index.py` | 全量 vs `--incremental` |
| 把会话变成 S1 转录 | `tools/sp_convert.py` | 多源转换 |
| 从会话抽候选结论 | `tools/sp_candidates.py` | 抽取→撞正本→去重→审 |
| 交接一摊活 | `tools/sp_handoff.py` | 四段模板 + `--check` |
| 写/同步入口文件 | `tools/sp_compile.py` | SSOT → 入口候选 |
| 断言体检 | `tools/sp_assert_audit.py` | 状态/重复/断号/断链/环/引用 |
| 断言编号 | `tools/sp_assert_alloc.py` | A 编号分配（不手写） |
| 健康检查 | `tools/ssot_check.py` | 六检查一屏 |
| 安全提纯 | `tools/sp_purify.py` | 默认 dry-run，只追加，自动备份 |
| 索引合并 | `tools/sp_index_merge.py` | 分片库 → 等价库 + `--verify` |
| 索引版本 | `tools/sp_pending.py` / `sp_index.py --status` | 版本目录 + 原子指针 |
| 环境指纹 | `tools/sp_fingerprint.py` | hardware/model/backend 单一实现 |
| 覆盖度 | `tools/sp_coverage.py` | 会话/块/源三数 |
| 契约校验 | `tools/sp_contract.py` | schema 一致性 |

## 2 核心命令

```bash
# 开局注入
python3 tools/sp_dispatch.py --level pointer

# 按意思搜
python3 tools/sp_semantic.py "<问题>" --expand --top 5

# 增量索引（日常）
python3 tools/sp_index.py --incremental

# 健康检查
python3 tools/ssot_check.py

# 安全提纯
python3 tools/sp_purify.py            # dry-run
python3 tools/sp_purify.py --apply    # 备份后写盘
```

## 3 关键判据

| 工具 | 判据 |
|---|---|
| `sp_dispatch` | pointer ≤300 tok；能力行来自 `BUILD.json` |
| `sp_semantic` | 命中带 `path:line`；`chunks=0` 时不可用 |
| `sp_index` | 块数/维度 768/文本可读；全量会先清库 |
| `sp_convert` | 会话数/行数/角色分布/时间线 + 抽样无乱码 |
| `sp_candidates` | 幂等（二次跑新增 0）；断言库 sha1 不变 |
| `sp_handoff` | 四段齐/事实带 source/否决段 ≥1 |
| `ssot_check` | `== 完成（健康）`；inbox 积压清零 |
| `sp_purify` | 标记数只增不减；apply 前有备份 |

## 4 坑（高频）

- `sp_index.py` 全量**先清库**，务必先备份
- `sp_semantic` 的 `chunks=0` 时直接不可用（先看 `BUILD.json`）
- 提纯脚本**只追加、不重写**；改前 `git status`，dirty 先备份
- 批量改写前先 dry-run，看计划再 `--apply`
- 会话转换跨平台时注意 UTF-8（Windows 默认 cp936）

## 5 新增工具的最低文档要求

| 层 | 要求 |
|---|---|
| help | `argparse` 带 `epilog`（示例+纪律） |
| GUIDE | `GUIDE.md` 一节（用途/命令/判据） |
| skill | 本手册或专用 skill 有一节 |
| assertion | 有坑就写 assertion，有机制就写 topic |

没有四层，不算交付。
