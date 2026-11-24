# MAINTENANCE · 变更分级与验证闸

> 目的：让「验证强度」跟「变更风险」匹配，而不是每次都把全量测试、夜间测试、影子安装全跑一遍。
> 适用：本仓库的维护者与 agent。实例使用者的操作手册见 [COLDSTART](COLDSTART.md)。

## 1 先分四级，再决定跑什么

| 级别 | 典型变更 | 必跑 | 不必跑 |
|---|---|---|---|
| **A 文档/说明** | `docs/*.md`、README、CHANGELOG、注释、错别字 | `release-check.sh`（若动版本）＋`public-audit.sh`＋`shell_strict_test.sh`；发布前 `preflight.sh` 一次 | 全量 `run_all`、`nightly`、覆盖率、重复 preflight |
| **B 工具/测试/模板/技能** | `tools/*.py`、`tools/tests/*`、`instance/*`、`skills/*`、`hooks/*`、`install/*` | 相关测试＋`run_all.sh tools/tests`（或 `--fast`）＋`release-check`＋`public-audit`＋`preflight` | 与本变更无关的实例内容对账 |
| **C 发版** | `VERSION`、CHANGELOG 版本段、CAPABILITIES、tag | B 级全部，加 tag/push 后的 CI；发布前只跑一次 preflight | 发布后再跑一遍全量（CI 已覆盖） |
| **D 实例内容层** | `~/ssot` 的 `lines/`、`knowledge/`、`inbox/`、boot | `ssot_check.py`；冷启动相关加 `coldstart-check.sh` | 本仓库的 kit 测试 |

判断口诀：**改的是「仓库里的框架」还是「实例里的内容」**；框架再看是文档还是代码。

## 2 顺序：批量改完，再跑闸

1. 先把同一意图的改动**一次性改完**（含文档互链、CHANGELOG）。
2. 再跑该级别的一组闸；失败只修本次变更相关的问题。
3. 发版：`release-check` → `public-audit` → 必要测试 → `preflight` 一次 → commit/tag/push。
4. CI **异步**：push 后先汇报，CI 红了再回来修，不阻塞收口。
5. 不在同一轮里追别的线的状态（线页版本漂移、别人刚发的版本、夜间测试抖动）——除非它影响本次变更。

## 3 停止规则（防止无限返工）

- 同一个闸连续失败两次，且原因与本次变更无关 → 记录现象、跳过该闸、继续收口；另开一条线处理。
- 并发会话导致的临时失败（索引正在重建、daemon 被占用、别人刚发版）→ 单独重跑失败项，不重跑全量。
- `public-audit` / `shell_strict` 这类静态闸优先修，因为它们最便宜。

## 4 发版清单（C 级）

- [ ] `VERSION`、CHANGELOG 的 `## [x.y.z] - YYYY-MM-DD`、CAPABILITIES 标题三者一致
- [ ] `release-check.sh` 通过
- [ ] `public-audit.sh` clean
- [ ] B 级测试通过（CI 会再跑一次）
- [ ] `preflight.sh --quiet` 绿（只跑一次）
- [ ] commit → push main → tag `v<VERSION>` → push tag → GitHub Release
- [ ] 汇报远端 `VERSION` / tag / CI 状态（CI 可后补）

## 5 反模式

- docs-only 却跑 110 个测试 + nightly + 覆盖率：慢，且容易被并发抖动带偏。
- 每改一处就跑一次 preflight：影子安装最贵，留到最后一次。
- 为了「顺手」去改无关文件、对账别的线：把一次小变更拖成大变更。
- CI 红了才想起本地没跑静态闸：先跑 `public-audit` / `shell_strict`，再 push。
- 把「验证通过」当成「没损伤」：涉及删改/脱敏时仍要按 [COLDSTART](COLDSTART.md) 的恢复纪律留证据。
