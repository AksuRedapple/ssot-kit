# 快速开始（10 分钟）

> 两种路径：**A 升级已有实例**（最常用）｜**B 从零安装**。
> 前置：`python3` ≥ 3.10、`numpy`、`git`。语义检索另需嵌入模型（约 800 MB）与常驻服务，见路径 B 第 4 步。
> **装完/升级后先跑**：`bash scripts/coldstart-check.sh`（四条断链：解释器 / boot 引用 / 索引 / 预算，见 [COLDSTART.md](COLDSTART.md)）。

## 路径 A：升级已有实例（推荐）

```bash
cd <ssot-kit 克隆目录>
git pull --ff-only
bash tools/install/update.sh --root ~/ssot      # 实例不在 ~/ssot 就改 --root
```

看到这段就说明框架层已更新、体检通过：

```
── ssot 升级（仓库 … → 实例 ~/ssot）
   跳过 pull（无 origin 或 --skip-pull）      ← 或 git pull 的输出
   无 sp_migrate.py（跳过数据迁移）
[takeover] 21 页 · 状态行 21 · … · 断链 0
== 完成 ==（健康）
✅ 升级完成
```

> `update.sh` 只覆盖框架层（`tools/ hooks/ skills/ scripts/`），**不动内容层**（`lines/ knowledge/ inbox/ sessions/ profile/ evidence/`）。
> `--dry` 可先预演；任一步失败即停，实例保持原状。

## 路径 B：从零安装

```bash
git clone <本仓库> ssot-kit && cd ssot-kit

# 1) 建实例骨架（只补缺，不覆盖已有文件）
bash tools/install/setup.sh --root ~/ssot

# 2) 框架件已由 setup.sh 递归同步（含 tools/ssotlib/**）
#    ⚠️ 不要再手工 `cp tools/*.py`——会漏掉 ssotlib/index/ 等子包，
#    升级后 sp_semantic 会 ModuleNotFoundError。缺文件就重跑 setup/update.sh。

# 3) 体检（此时语义层还没建，相关行会显示 0/缺省，属正常）
python3 ~/ssot/tools/ssot_check.py

# 3.5) 会话采集（可选，但语义检索要靠它才有会话原文）
#      先看真源有几个会话；确认后归档（默认 dry-run，加 --apply 才写）
python3 ~/ssot/tools/sp_sources.py
python3 ~/ssot/tools/sp_archive.py --apply

#      归档 → S1 → 索引（按实际使用的 harness 选 --src）
python3 ~/ssot/tools/sp_convert.py --src cc --incremental
python3 ~/ssot/tools/sp_convert.py --src qoder --incremental
python3 ~/ssot/tools/sp_opencode.py --limit 200

# 4) 语义层（可选；需嵌入模型 + 常驻服务）
#    模型与启动方式见 docs/SEMANTIC.md
python3 ~/ssot/tools/sp_index.py --incremental
```

> `evidence/` 里是会话原文，视同个人数据；不要提交到公开仓，也不要把 `SSOT_REPORT.md` 之类的体检产物原样外发。

**3.6）分类与退出（可选，索引层）**

```bash
python3 ~/ssot/tools/sp_classify.py --init
python3 ~/ssot/tools/sp_classify.py --scan      # 预览 class/reason
python3 ~/ssot/tools/sp_index.py --plan         # 预览 include/skip
# 确认后：sp_classify.py --apply → sp_index.py --incremental
# 退出：sp_exit.py --make-manifest → --retire --apply → --verify
```

## 三条可用性验证

**① 体检一行**

```bash
python3 ~/ssot/tools/ssot_check.py | grep -E "coverage|takeover|完成"
# 期望：[coverage] 人类源 x/y 会话 · [takeover] … 断链 0 · == 完成 ==（健康）
```

**② 一条检索（需要索引与常驻服务）**

```bash
python3 ~/ssot/tools/sp_semantic.py "同一事实禁止两条并行抽取路径" --mode route3 --top 3
```

期望头行给出库大小与耗时，并返回 `knowledge/assertions.md` 的命中（断言 A451 一类）。

**③ 一条断言引用**

```bash
grep -n "A451" ~/ssot/knowledge/assertions.md
```

## 60 题评测（复现召回基线）

```bash
python3 ~/ssot/tools/sp_semantic.py \
  --eval ~/ssot/knowledge/eval/retrieval-queries-v06.json \
  --mode hybrid2 --top 10
```

输出 `recall@5`；本机基线 **0.875**（`route3` 模式）。

> ⚠️ 考卷属于**内容层**，kit 不自带；实例里没有 `knowledge/eval/` 时这条命令会失败——这是预期，不是安装问题。

## 验收（给 agent）

意图与判据见 [ACCEPTANCE.md](ACCEPTANCE.md)：新装/升级/迁移/守卫四组，每组有"判据 + 反例 + 回执格式"。

## 故障排查

| 现象 | 原因 | 处置 |
|---|---|---|
| `sp_semantic` 报连不上/很慢 | 常驻服务没起 | 起服务（见 `docs/SEMANTIC.md`），或加 `--oneshot` 临时直跑 |
| `ssot_check` 报缺文件 | 框架层没同步 | 重跑 `bash tools/install/update.sh --root ~/ssot` |
| 文档里提到 `kb_search.py` / `kb_index.py` | 这些是旧工具 | 用 `sp_semantic.py` / `sp_index.py`；旧实例的 boot/START 需要手工或迁移脚本更新 |
| `sp_semantic` 报 `No module named 'ssotlib.index'` | 升级只拷了顶层 `ssotlib/*.py` | 重跑 `bash tools/install/update.sh --root ~/ssot`（已改为递归） |
| `sp_semantic` 报 numpy 缺失 | `python3` 不是带 numpy 的解释器 | `python3 -c 'import numpy'`；不行设 `SSOT_PY`，见 [COLDSTART.md](COLDSTART.md) §3 |
