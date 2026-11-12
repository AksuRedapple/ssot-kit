# 快速开始（10 分钟）

> 两种路径：**A 升级已有实例**（最常用）｜**B 从零安装**。
> 前置：`python3` ≥ 3.10、`numpy`、`git`。语义检索另需嵌入模型（约 800 MB）与常驻服务，见路径 B 第 4 步。

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

# 2) 把框架件放进实例
cp tools/*.py ~/ssot/tools/
mkdir -p ~/ssot/tools/hooks && cp hooks/*.sh ~/ssot/tools/hooks/

# 3) 体检（此时语义层还没建，相关行会显示 0/缺省，属正常）
python3 ~/ssot/tools/ssot_check.py

# 4) 语义层（可选；需嵌入模型 + 常驻服务）
#    模型与启动方式见 docs/SEMANTIC.md
python3 ~/ssot/tools/sp_index.py --incremental
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
| 文档里提到 `kb_index.py` | 该脚本已归档 | 用 `sp_index.py` / `sp_semantic.py` 替代（文档清理中） |
