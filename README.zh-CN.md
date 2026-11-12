# ssot-kit · Agent 知识治理系统

[English](README.md) · [![CI](https://github.com/AksuRedapple/ssot-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/AksuRedapple/ssot-kit/actions/workflows/ci.yml)

> 给同时跑多个 agent、几十个会话的人：让知识不再散落、会话可以接续、常驻记忆不撑爆上下文。
> **单机即完整系统**（clone 后你即 owner）；多机分发（上游维护 → 下游只 pull）是可选模式。**零内容入仓。**

**实践连载**：[可换届的组织](https://ouya15.cn/insights/series/org-governance.html) · [案例说明](docs/CASE-STUDY.md)

## 它解决什么

三个真实问题（都是会出事故的那种）：

1. **记忆有装载预算**——agent 的常驻记忆文件（`CLAUDE.md` / `MEMORY.md` 这类入口）有硬性体积上限，超限即**静默截断**：最新条目先被裁，且没有任何报错。
2. **会话找不到接续**——开了几十个会话后，"这个需求该新开还是接续、接续接哪个"，没有地方可查。
3. **知识散落**——结论沉在一个个会话里，找不到、接不上。

## 方案（六件）

| 件 | 一句话 |
|---|---|
| **薄壳编译** | 入口文件是**编译产物**：正本 → 极小的"指针+纪律"薄壳；索引层不要，细节按需拉（`tools/sp_compile.py`） |
| **会话台账** | 一行一会话（登记册）+ 每业务线一页（含【续点】）；开工三问 / 收尾一行（`docs/SSMAP.md`） |
| **知识库** | inbox（fact 带 source / decision 带 owner）→ 单向提纯进知识层（`docs/PROTOCOLS.md`） |
| **语义检索（可选）** | 本地嵌入模型（EmbeddingGemma + llama.cpp），按意思搜，不出机（`docs/SEMANTIC.md`） |
| **读侧自动化（可选）** | SessionStart 注入 / 回忆句式触发检索 / Stop 机械草稿 + 6h 值守；无 shell hook 的 harness 走扩展/插件（opencode、Pi）；把「应该做」降成结构（`docs/HOOKS.md`） |
| **可信度与新鲜度** | inbox `conf: 实测/推断/待核`；薄壳/索引记 `built_at_commit`；`SSOT_REPORT.md` 冷启动单文件；断言编号 lint（只报不改号） |

## 与现有方案的关系

- **Mem0 / Zep / Letta 类**：面向「应用内嵌记忆 API」（事实抽进库、供应用调用）。本项目面向**个人/小团队的多工具工作流**——真相就是本机 markdown 文件，不引入服务端存储；核心差别是"谁拥有记忆"。
- **跨工具共享记忆服务器类**：共享靠服务器中转。本项目走**文件 + 编译**：不常驻服务；入口文件由正本编译下发；带出处纪律（每条事实可对账到源）与装载预算工程（薄壳 + 回归闸）。
- **手维护 `CLAUDE.md` / `AGENTS.md`**：那正是问题 1 的现场。本项目把它升级为：正本 → 编译 → 薄壳，配套"裁尾/盲区"这类故障的机制性护栏。

一句话定位：**不是又一个记忆服务器，而是「文件即真相 + 编译式入口」的记忆治理模式与全套落地件。**

## 快速开始

| 你在哪 | 读哪 |
|---|---|
| 首次部署 | [SETUP.md](SETUP.md)（agent 执行） |
| 已部署、要升级 | [UPGRADE.md](UPGRADE.md) |

## 验收（给 agent）

- 意图 + 判据 + 回执格式：[docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)

## 系统件

- `instance/` —— 实例骨架（`~/ssot/` 空壳；setup 展开；只补缺不覆盖）
- `tools/` —— 薄壳编译 / 语义索引检索 / 会话普查 / 自查 / 6h 值守 / 发布门禁
- `hooks/` —— SessionStart / UserPromptSubmit / Stop 草稿（可选安装）+ `hooks/pi/` Pi 全局扩展
- `skills/` —— 技能（装到 agent 的 skills 目录）
- `tools/install/` —— `setup.sh`（首装）· `update.sh`（升级应用）· `install-service.sh` · `install-steward.sh`（`scripts/` 下同名脚本为兼容包装）
- `scripts/` —— `install-hooks.sh` · `install-pi-extension.sh` · `install-steward.sh` · 发布与公开面门禁
- `docs/` —— [QUICKSTART](docs/QUICKSTART.md) / [ARCHITECTURE](docs/ARCHITECTURE.md) / [GLOSSARY](docs/GLOSSARY.md) / [UNINSTALL](docs/UNINSTALL.md) / [PROTOCOLS](docs/PROTOCOLS.md) / [METHOD](docs/METHOD.md) / [SSMAP](docs/SSMAP.md) / [SEMANTIC](docs/SEMANTIC.md) / [HOOKS](docs/HOOKS.md)
- `docs/CASE-STUDY.md` —— 从真实问题到公开实现与连载证据的作品集入口

## 红线

- 本仓库**永远不得出现**：个人材料、组织内部材料、真实会话内容、凭据；CI 通过 `scripts/public-audit.sh` 与 GitHub secret scanning 双重设闸
- 使用机只读：**只 pull，永不 push**；内容层永不离开各自主机
- 下游痛点/提案经人工转交回上游：上游迭代 → CHANGELOG 记账 → 下游 pull 即得

## 状态

- **版本**：v0.13.1（2026-11-12）——`git pull` + `tools/install/update.sh` 即可升级
- **CI**：GitHub Actions（macOS）跑 release metadata / shell+Python 语法 / 随包测试 / 隔离 preflight
- **公开面**：License ✅ · 中英文文档 ✅ · 快速开始（10 分钟）✅ · 术语表/卸载指南 ✅ · 工具清单 ✅
- **闭环**：工作机外部视角审计 X01–X10 全部处理（0.7.2 → 0.8.1，见 CHANGELOG）
- **验证**：随包回归测试、隔离安装/升级/迁移 preflight、公开面隐私与断链审计均通过
- **待办**：补充更多端到端示例并继续对齐英文长文档 ⏳

## 维护者

建议通过 fork + Pull Request 贡献；每条变更写 `CHANGELOG.md`，合并前由 CI 校验版本、测试、隔离升级与公开面边界。

## Releases and changelog

- `CHANGELOG.md` follows the [Keep a Changelog](https://keepachangelog.com/) structure and semantic versioning.
- Active work is recorded under `[Unreleased]`; release moves it to a dated version section.
- `scripts/release-check.sh` enforces `VERSION` ↔ newest CHANGELOG section ↔ `CAPABILITIES.md`.
- GitHub Actions runs packaged tests and isolated install/upgrade preflight on every PR and push; version tags must be `v<VERSION>`.

---

English: [README.en.md](README.en.md) · [SETUP.en](SETUP.en.md) · [ARCHITECTURE.en](docs/ARCHITECTURE.en.md)
