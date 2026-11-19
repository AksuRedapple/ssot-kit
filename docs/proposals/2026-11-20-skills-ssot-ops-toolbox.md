# 升级候选 · 技能入仓（ssot-ops / ssot-toolbox）

> 2026-11-20 · 状态：candidate

## 现状

公开仓 `skills/` 只有 `ssmap`。本机在用的 `ssot-ops`（薄路由）与 `ssot-toolbox`（16 工具手册）**未入仓、未脱敏**。

## 提案

把两份 skill 的**公开版**加入 `skills/`：

```
skills/
  ssmap/          # 已有
  ssot-ops/SKILL.md
  ssot-toolbox/SKILL.md
```

- `ssot-ops`：路由壳，只写「何时用 / 先读哪 / 禁止什么」，操作正本指向仓库 `GUIDE.md`。
- `ssot-toolbox`：工具手册，路径全部相对仓库根（`tools/…`），去掉本机专属数字与私有服务名。

## 脱敏清单（发布前逐项 grep）

| 模式 | 处理 |
|---|---|
| `/Users/<name>`、`~/ssot` | 改仓库相对路径 |
| 内网 IP / 端口 / 主机名 | 改 `127.0.0.1` / 占位符 |
| 个人名 / 设备名 | 改 `user` / `host` |
| 私有服务名（如内部产品线） | 改通用描述 |
| 会话 ID / 日期型项目代号 | 删除或泛化 |
| 本机实测数字（工具数/字符数） | 标注「本机实测」或删除 |

## 验收

```bash
grep -rnE '/Users/|192\.168\.|<personal>|<device>' skills/ssot-ops skills/ssot-toolbox
# 期望：0 命中

python3 - <<'PY'
import re,glob
for p in glob.glob('skills/ssot-*/SKILL.md'):
    t=open(p).read()
    assert t.startswith('---'), p
    assert 'name:' in t and 'description:' in t, p
print('frontmatter ok')
PY
```

## 影响面 / 回滚

- 纯文档新增，不改工具行为；回滚=删除目录。
