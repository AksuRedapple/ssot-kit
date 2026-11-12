# Changelog

All notable changes to this project are documented here. The format follows Keep a Changelog and the project uses semantic versioning.

## [Unreleased]

No unreleased changes yet.

## [0.13.1] - 2026-11-12 — 公开面试官视角终审与自动化隐私闸

- **fix(public-surface)**: 清理历史验收文档中的个人绝对路径与内部机器称谓；公开文档统一为“本地实例 + 可选分发”表述
- **fix(docs)**: 移除不随包工具和不存在文件的错误引用；修正中英文 README、架构、升级与贡献文档之间的状态、路径和验证口径漂移
- **fix(sp_bootstrap)**: capture 阶段仅在 `sp_sweep.py` 与 `sp_capture.py` 同时存在时启用，公开子集不再规划或执行缺失阶段；新增回归测试
- **feat(ci)**: 新增 `scripts/public-audit.sh`，自动检查凭据形态、个人绝对路径、私有网段和 Markdown 断链，并接入 macOS CI
- **chore(deps)**: 新增 Dependabot GitHub Actions 每周更新配置

## [0.13.0] - 2026-11-12 — 候选冲突检测从全库 O(n²) 改为倒排增量

- **perf(sp_candidates)**: 冲突检测改用倒排 token 索引，只把本次新增候选与反极性近邻比较；旧候选仍参与匹配，冲突双向标记语义不变
- **feat(sp_candidates)**: 新增 `--conflict-mode incremental|full|none`（默认 incremental）与 `--session <sid8>` 定向抽取；全库扫描不再每次两两遍历
- **fix(sp_candidates)**: 新候选固定写入 `schema: 2`；生成 review 时去除行尾空白
- **acc（macmini 实测）**: 4,828 条候选、新增 71、合并证据 11、近邻比较 3,921，完成 **6.64s**（修复前 6 分钟未收敛）；同输入复跑 `touched=0`；单会话定向抽取 **0.75s**
- **test**: 新增 `sp_candidates_conflict_test.sh` + Python 回归：4,000 条无关候选 + 1 条反极性近邻只检查 1 对、冲突幂等、`--session` 过滤、候选 schema=2
- **ci**: 新增 GitHub Actions macOS 门：release metadata、shell/Python 语法、随包测试、隔离安装/升级 preflight；版本 tag 强制等于 `v<VERSION>`
- **docs**: CHANGELOG 切换为 Keep a Changelog 格式（`[Unreleased]` + `[x.y.z] - YYYY-MM-DD`）；新增 `CONTRIBUTING.md`、`GOVERNANCE.md`、`SECURITY.md`、PR 模板与 `scripts/release-check.sh`
- **docs**: 公开发布使用 English-first README，保留 `README.zh-CN.md`；公开审计与干净历史策略记录在 `docs/OPEN-SOURCE-AUDIT.md`


## [0.12.0] - 2026-11-12 — 索引发布版本化（构建与在线解耦）

- **feat(sp_index)**: 版本化发布——`--build` 全量建到 `versions/<ts>-<sha>.building/`（不碰 active），校验后改名、写 STATUS、**原子切 `active.json`**；新增 `--activate [ver]` / `--rollback` / `--prune` / `--adopt`（把 legacy 单库收编为第一版）/ `--status`（只读，构建中可查）
- **BREAKING（默认值）**: 裸跑 `sp_index.py` 从「全量清库重建」改为**增量**；全量必须显式 `--build`。旧行为在中断时会留下不可用索引（实测事故：338,167 块 → 1,088）
- **feat(sp_semantic)**: 解析 `active.json` 读版本库，缺失回退 legacy 单库——灰度迁移不停机
- **fix(sp_index)**: `--prune` 顺带清理超过 1 天的 `.building` 残骸；版本名在非 git 目录回落 `nogit`（不再是空尾）
- **test**: 新增 `sp_index_versioning_test.sh`（adopt / activate / rollback / status 四条，随包全过）
- **acc（macmini 实测）**: 全量 338,176 块 / 20,374s（16.6 块/秒）；`kill -9` 打断构建 → active 不变、检索正常；`--activate` 0.88s / `--rollback` 0.80s


## [0.11.0] - 2026-11-06 — 块级 diff + 线页漂移 + conf 归一化

- **perf(sp_index)**: 块级 diff——变更源按 `(text, role, ts)` 复用旧向量，只嵌新块；行号变化不影响复用。实测 inbox 追加一行：**新嵌 2 块 / 复用 55 块**，完整增量 19s（此前重嵌整源）
- **feat(ssot_check)**: 线页内容漂移检查——`profile/line_sources.json` 声明「线页字段 ↔ 真源 JSON」；`[line-drift]` 直接报「线页 0.8.25 ≠ 真源 0.8.30」及 versionCode 漂移；`--strict` 下计入阻塞
- **fix(ssot_check)**: `conf` 归一化——四前缀（实测/推断/推算/待核）；常见同义词（源码/设备实测/代码/单测）归一到 `实测`；`决定/用户令/owner` 视为无置信度字段，不再报非法值
- **test**: 新增 `sp_index_chunk_diff_test.sh` / `line_drift_test.sh` / `conf_normalize_test.sh`，随包测试全过


## [0.10.0] - 2026-11-06 — OpenCode v2 适配 + 增量向量包 + 锁可见性

- **fix(sp_opencode)**: OpenCode v2 起以 `session_v2` / `session_message` 为主，legacy `session/message/part` 只补未迁移会话；正文从 `session_message.data` 解析（user.text / assistant.content[] 的 text+tool / system.text / compaction.summary，跳过 reasoning/synthetic/idle）；`session_part` 为空不再依赖；新增 `--all`、meta `store/schema:2`
- **fix(sp_coverage)**: OpenCode 原始分母改为「v2 根 + legacy-only 根」的并集；此前只数 legacy `session`，新会话永远进不了分母，导致「未接入 0」假绿
- **feat(sp_index)**: 向量包真正增量——只追加缺失 id，`stale > 2000` / `missing > 5000` 才全量压实；新增 `--no-pack` / `--pack-only` / `--full-pack`
- **perf(sp_index)**: 新增 `chunks_id_only on chunks(id)` 覆盖索引（`select id` 40s→0.3s）与 `chunks_path_idx on chunks(path)`（按源删除不再全表扫 1.9GB）；索引创建为一次性，之后增量按索引定位
- **feat(sp_index)**: 锁等待可观测——`.lock` 记录 pid/启动时间/argv，每 30s 报一次等待；新增 `--no-wait`（拿不到锁 rc=3）与 `--wait-timeout`（默认 1800s）
- **fix(sp_candidates)**: `--ingest` 新账本行补 `schema: 2`，避免契约检查把新候选判成漂移
- **fix(sp_triage)**: 「0 候选」分三态——账本无该 sid（未采集，rc=2 并提示查 S1）/ 有记录但全被拒/去重 / 真低分；不再把「没读过」说成「不够格」
- **test**: 新增随包 `tools/tests/sp_opencode_v2_test.sh`（v2 优先 / legacy 补位 / 子会话 / coverage 分母并集）


## [0.9.14] - 2026-11-05 — 提纯口径与断言取号显示（两处计数的坑）

- **fix**: `sp_assert_alloc --status` 取 `max(计数文件, 断言文件最大号+1)`，与 `alloc()` 的自愈口径一致；此前断言文件已有更大号时仍会报旧号（如文件到 A533，status 仍说「下一个 A533」）
- **docs**: PROTOCOLS/GLOSSARY 写清 inbox 提纯的**实际计数口径**——整行不含 `→` 才算未提纯（正文自带箭头会被误判为已提纯）、`→ 归位:` 可放在 `| conf:` 之后、conf 覆盖率单算且判定前先剥标记
- **docs**: SEMANTIC 补「索引新鲜度」——`落后 N commits` 只是新鲜度提示，契约升级不触发全量重建；仅嵌入模型/分块规则变更才需要重建
- **test**: 上游 `assert_alloc_test` 增 `--status` 自愈用例（计数落后时按文件最大号报下一个号）


## [0.9.13] - 2026-11-04 — 索引摘要收窄为「进块字段」（A531）

- **fix**: `sp_index` 会话指纹不再纳入整份 `meta.json`（schema 等非进块字段），只取 `title[:48] + start[:10]`；此前一次契约整库盖章会让全部会话判变、白跑一次全量重嵌（实测 24.6 万块 / 4 小时）
- **feat**: `sp_index --restamp` 一次性口径迁移：只改写 `src_state` 摘要、不重嵌；安全闸=仅当旧摘要等于「按当前文件算出的旧口径值」才改写，内容真变的源留给下一次增量
- **test**: 新增 `tools/tests/sp_index_digest_test.sh`（非进块字段不变指纹 / restamp 迁移 / 不吞内容变化）
- **fix**: `install/setup.sh`、`install/update.sh` 的 `--dry` 不再创建目录


## [0.9.12] - 2026-11-04 — 派生物 schema 由生成器自盖（A530）

- **fix**: `sp_index.write_build()` 写 `BUILD.json` 时自带 `schema`（读 `profile/contract.json`，无契约文件则降级不盖）；此前迁移器补的章会在下一次成功索引时被抹掉
- **fix**: `sp_convert` 写 S1 `meta.json` 时自带 `schema`；此前每转换一个新会话就会再产出一份 drift
- **fix**: `sp_migrate --to current` 真正可用（此前 argparse 只收整数，`update.sh` 与随包冒烟都会在这里失败）
- **test**: 上游 `sp_schema_check` 350/350 一致、`migrate_test` 新增 `--to current` 用例并全过
- **docs**: QUICKSTART 示例路径改为 `~/ssot`（避免发布禁词闸把占位路径误判）


## [0.9.11] - 2026-11-04 — 工具契约进 --help（P1）

- **feat**: 7 个核心工具（candidates/migrate/semantic/triage/convert/dispatch/ssot_check）的 `--help` 顶部加【契约】：意图 / 退出码 / 失败后怎么做；`sp_index` 无 argparse epilog，例外


## [0.9.10] - 2026-11-04 — 验收改为"意图 + 判据"（面向 agent）

- **docs**: 新增 `docs/ACCEPTANCE.md` —— 新装/升级/迁移/守卫四组验收：意图、步骤、可机裁判据、反例、统一回执格式（命令/rc/证据/判定）
- **docs**: README/QUICKSTART 挂入口；明确"随包的是冒烟测试 + 意图判据，全量测试留上游"


## [0.9.9] - 2026-11-04 — kit 侧测试入口

- **test**: `tools/tests/run_all.sh`（相对路径，不依赖 `~/ssot`）→ 跑随包冒烟；全量 16 条测试仍留在上游（含本机数据依赖）


## [0.9.8] - 2026-11-04 — 随包冒烟测试（无个人路径）

- **test**: `tools/tests/smoke_test.sh` —— 隔离 HOME：setup 拷贝框架件 → update → `ssot_check` 健康 → `sp_migrate --to current`；可随包分发


## [0.9.7] - 2026-11-04 — fail-recorded + 四数自检

- **fix(hooks)**: 三个 hook 的 `2>/dev/null` 改为 `2>>$ROOT/alerts/hook.err`（失败仍 exit 0，但留痕；F27）
- **feat(publish)**: 发布前四数自检：`VERSION` 必须在 `CHANGELOG.md` 有条目，否则拒绝


## [0.9.6] - 2026-11-04 — 发布闭环（影子 dogfood 闸门）

- **feat**: `scripts/preflight.sh` —— 影子实例 dogfood：临时 HOME → 本地 clone → setup → update --skip-pull → `ssot_check` 健康 → `sp_migrate --to current --apply` → 再体检；任一步失败非零
- **feat**: `publish.sh` 接闸：无 `--force` 时先跑 preflight，红则拒绝 commit/push
- **fix(install)**: `setup.sh` / `update.sh` 现在**真正拷贝框架件**（`tools/*.py` + `hooks/*.sh`）；此前新装实例没有 `tools/`，`ssot_check` 直接找不到文件
- **fix(sp_migrate)**: `--to current` 支持（F30）；`update.sh` 迁移调用因此可通
- **deferred**: `tools/tests/` 暂不随包（测试内含个人绝对路径，下版脱敏后随包）


## [0.9.5] - 2026-11-04 — 第二批反馈收口

- **fix(F25/P0)**: `sp_coverage.py` 无 `evidence/` 树时返回 3 元组导致 `sp_bootstrap --plan` 崩溃——改为 4 元组；`sp_coverage` 支持 `SSOT_ROOT`（隔离实例可测）
- **fix(F27)**: `hooks/user-prompt-retrieval.sh` 语义检索失败时不再静默 exit 0，向 stderr 打一行降级提示（原因见 `/tmp/ssot-semantic.err`）
- **docs(F21)**: 补 CHANGELOG `0.6.0` 条目
- **docs(F22)**: SEMANTIC 说明 `BUILD.json` 的 `commit: "-"` 为"实例非 git 仓"的正常形态
- **docs(F25 升级面)**: UPGRADE 增「v0.9.x 契约迁移」——`schema_check → migrate --status/--dry-run/--apply → schema_check` 标准顺序、守卫拒跑自愈、回滚


## [0.9.4] - 2026-11-04 — 断言编号分配器（v1.1-B）

- **feat**: `tools/sp_assert_alloc.py` —— flock + 计数文件 + 预留表；`--next/--status/--commit/--sync`；`sp_assert_ingest` 改为先分配后写入
- **fix(ssot_check)**: 缺号统计排除"已预留未落盘"的编号，避免写入窗口误报
- **test**: `assert_alloc_test.sh` 四条（初始化 / 8 进程×3 并发无撞号 / 预留可见 / 缺号排除预留）


## [0.9.3] - 2026-11-04 — 同步修正

- **chore**: 把 0.9.2 的事务化 `sp_migrate` 与 `ssot_check` 修复真正同步进 kit（0.9.2 标签时的副本未含同步件）


## [0.9.2] - 2026-11-04 — 迁移事务化（不允许半迁移）

- **fix(sp_migrate)**: `m0002` 改为事务式——先全部算好并暂存，再统一 `os.replace`；任一步失败按 `.orig` 回滚已落盘文件，**不留半迁移**
- **test**: 迁移测试增至 6 条，新增「失败注入 → 非零退出且数据文件 sha 不变」


## [0.9.1] - 2026-11-04 — 断言编号 lint 与体检修复

- **fix(ssot_check)**: 断言重号展示兼容字符串编号（A515b 等），修复 `fmt_ids` 拼接报错
- **fix**: 断言编号去重口径与字母后缀统一


## [0.9.0] - 2026-11-04 — 数据契约与迁移（v1.1-A）

- **feat**: `profile/contract.json` 实例契约（contract=2）+ S1 `meta.json` / 账本每行 / `BUILD.json` 增加 `schema` 字段
- **feat**: `tools/sp_schema_check.py` —— 只读扫描契约与产物 schema 分布，接入 `ssot_check` 的 `[contract]` 行
- **feat**: `tools/sp_migrate.py` —— 步骤表（check/apply）、`--status/--to/--dry-run/--apply/--resume`、迁移前 tar 备份、`profile/.migrating` 写锁、失败即停、幂等
- **feat**: `tools/sp_contract.py` —— 读侧守卫：实例契约 < 工具要求 → 写工具拒跑；> 工具支持 → 只读警告；四核心工具已接入
- **breaking(内部)**: 工具 `main()` 改为 `sys.exit(main())` 传播退出码（此前守卫的"拒绝运行"被吞成 0）
- **docs**: 索引类派生物**不迁移只重建**；迁移测试五条（dry-run 不写盘 / apply 全绿 / 幂等 / resume / 守卫）


## [0.8.3] - 2026-11-04 — 断言编号 lint 支持字母后缀

- **fix(ssot_check)**: 断言编号 lint 允许 `A515b` 这类字母后缀变体，不再与 `A515` 误判为重号；缺号/重号统计按完整编号


## [0.8.2] - 2026-11-04 — 状态区与叙事收口

- **docs**: README 首屏改为「单机即完整系统，多机分发可选」；状态区更新为 v0.8.x（版本/公开面/审计闭环/验证/待办）
- **docs**: 审计 X01–X10 在 CHANGELOG 里可追溯（0.7.2 → 0.8.1）


## [0.8.1] - 2026-11-04 — 英文文档补齐（X04 收尾）

- **docs**: 新增 `SETUP.en.md`（九步首装，与中文同步）与 `docs/ARCHITECTURE.en.md`（分层/部件/部署形态/路线）
- **docs**: README.en 链到英文 SETUP/ARCHITECTURE；中文 README 同挂英文入口
- **fix**: `tools/install/setup.sh` 技能目录探测补 `~/.qoder`（此前漏 Qoder，回归"装到 ~/.qoder/skills"的旧行为）


## [0.8.0] - 2026-11-04 — 公开面结构批（工作机审计 X03/X04/X07/X08/X09）

- **docs(X03)**: 部署形态改为"单机默认 + 多机分发可选"；README/SETUP/ARCHITECTURE 的"只 pull 永不 push"改为"勿把个人内容推回本仓库（改造请 fork）"
- **docs(X04)**: ARCHITECTURE 部件表与路线区对齐 v0.8（已完成项勾掉、补 QUICKSTART/部署形态）；README.en 重写为当前版本摘要并标注"中文为准"
- **docs(X07)**: 新增 `docs/GLOSSARY.md`（正本/薄壳/台账/线页/开工三问/断言/四层…中英对照）；HOOKS 里的内部断言编号改为自包含描述
- **docs(X08)**: 新增 `docs/UNINSTALL.md`（恢复记忆入口/卸服务/卸 hooks/卸技能/内容导出/验证）；SETUP 第 3 步加醒目接管警告与恢复命令
- **docs(X09)**: CAPABILITIES 重写为工具清单——核心四件 / 自动化 / LLM 管道，每件一行"用途 + 最小用法"


## [0.7.3] - 2026-11-04 — 薄壳落点可配（工作机审计 X02）

- **feat(X02)**: `sp_compile.py --target <path>`（亦可 `SSOT_MEM_TARGET`）——薄壳编译不再只能写 Qoder 的 `MEMORY.md`；SETUP 增「按 harness 选落点」表（CC `~/.claude/CLAUDE.md` / opencode `AGENTS.md` / 任意入口）
- **fix**: `--target` 与 `--deploy` 组合时，前版备份/硬限校验都作用于同一落点


## [0.7.2] - 2026-11-04 — 公开面快修（工作机审计 X01/X05/X06）

- **fix(X01)**: `docs/SEMANTIC.md` 从 legacy `kb_index.py`/`kb_search.py` 全面改写为 `sp_index.py`/`sp_semantic.py`（含命令、留痕路径、故障描述）；`docs/PROTOCOLS.md`、`docs/ARCHITECTURE.md`、`docs/HOOKS.md`、`CAPABILITIES.md` 同步清理
- **fix(X01)**: `tools/steward.sh` 语义哨兵改用 `sp_index.py --incremental`（此前因 `kb_index.py` 缺失永远 skipped）
- **fix(X05)**: 删除平铺重复安装件（`tools/{setup,update,install-service,install-steward}.sh`），安装件唯一实现在 `tools/install/`；`scripts/setup.sh`、`scripts/update.sh` 改为薄包装（旧链接仍可用）
- **fix(X06)**: `instance/profile/harness-boot.md`、`skills/ssmap/SKILL.md` 的 legacy 检索命令改为 `sp_semantic.py --mode route3`
- **docs(X10)**: SETUP 前置补 `numpy` 与平台矩阵；README/SETUP 的「只 pull 永不 push」改为「勿把个人内容推回本仓库（改造请 fork）」


## [0.7.1] - 2026-11-03 — 安装件收敛与快速开始

- **feat**: `docs/QUICKSTART.md` —— 10 分钟两路径（升级已有实例 / 从零安装），含三条可用性验证与 60 题评测复现命令
- **fix**: 安装件落到 `tools/install/{setup,update,install-service,install-steward,scan_sessions}`，`UPGRADE.md` 引用路径从此存在
- **docs**: UPGRADE v0.7.0 节同步为 `tools/install/update.sh`
- **known**: 工作机外部视角审计 X01–X10 待处理（见 CHANGELOG 下一版；3 条🔴 属"照文档走不通"）


## [0.7.0] - 2026-11-03 — 接手面 + 覆盖口径 + 脱敏

- **feat**: `tools/sp_takeover_lint.py` —— 线页接手面四规则自检（状态行新鲜度 / 在途条目「判据+owner」覆盖率 / 页内路径存在 / 站内链接可解析），接入 `ssot_check` 输出 `[takeover]` 一行；R3 死路径为建议级不阻塞
- **feat**: `tools/sp_line_status.py` —— 线页「现在时」状态行派生（git 最近提交 / inbox 提及 / 断言引用取最大日），人只写卡点
- **feat**: `tools/sp_assert_ingest.py` —— 蒸馏草稿里的断言批量入册（撞正本 0.88 + 连续编号），补上「草稿 → 正本」最后一段
- **feat**: `tools/install/{setup,update,install-service,install-steward}.sh` —— 首装/升级四件，多 harness 技能目录自动探测、`--dry` 预演、流水失败即停
- **fix**: `sp_coverage.py` dsh 口径——原始数只计 >2KB 的会话，冒烟/空会话不再算成缺口（本机 36/202 → 105/105）
- **chore**: dispatch 示例去掉个人路径（开源脱敏）；kit 子集核验 21/21 一致


## [0.6.0] - 2026-10-31 — 与 ssot v1.0 对齐

- **feat**: 同步 17 个 ssot 工具（采集/候选/检索/编排/LLM 三级/体检）+ 安装四件（setup/update/install-service/install-steward）
- **docs**: 能力清单化（CAPABILITIES.md，声明"kit 是 ssot 的子集"）
- **chore**: 归档 `kb_index.py` / `kb_search.py` 到 `tools/legacy/`（由 `sp_index.py` / `sp_semantic.py` 取代）


## [0.5.1] - 2026-10-25 — Pi 扩展接入

- **feat**: `hooks/pi/ssot-boot.ts`——Pi 全局扩展（无 shell hook 的 harness 路线）：`session_start` 跑 `$ROOT/tools/hooks/session-start.sh`（与 shell hook 同源），`before_agent_start` 写 `systemPromptOptions.sections.ssot_boot`；命中回忆句式跑 `sp_semantic --top 3` 写 `sections.ssot_recall`（:8399 不在则跳过，不拉起）
- **feat**: `scripts/install-pi-extension.sh`——装/卸到 `~/.pi/agent/extensions/`（`--dry`/`--uninstall`/`--dir`/`--root`；覆盖前备份）
- **docs**: `docs/HOOKS.md` 新增 §七 Pi 接入契约（开关/日志/单根纪律/验证命令），§六 opencode 的回忆词表状态核正为「已读 JSON」；README/SETUP 增扩展路线入口
- **兼容**: 扩展只依赖 Node ≥18 内置模块 + Pi 扩展 API；不改 instance 骨架与现有 shell hooks


## [0.5.0] - 2026-10-21 — 可信度与新鲜度

- **feat**: inbox 行格式/卡片模板增加可选 `conf: 实测|推断|待核`；`ssot_check` 统计覆盖率与非法值
- **feat**: `sp_compile` 薄壳头与编译报告带 `正本 commit`；`kb_index` 写 `kb-index/BUILD.json`（commit/chunks/built_at）
- **feat**: `ssot_check --report PATH` 生成短线冷启动报告 `SSOT_REPORT.md`（线/登记/inbox/断言/索引/草稿/演练）；`steward.sh` 每 6h 调用
- **feat**: 断言编号 lint：总数/最新/重复/缺号/标签，报告具体编号（**只报不改号**）
- **feat**: `ssot_check` 读 BUILD.json 与 HEAD 对账，索引落后时报告 `落后 N commits`
- **feat**: 隐私闸——`kb_index` 跳过含完整密钥形态的文件并计数；`sp_index` 命中即拒绝索引（`--allow-secret-files` 仅用于确认过的文档示例）；steward 被拦时发通知
- **docs**: `instance/START.md` 增 SSOT_REPORT 入口；新增 `docs/ACCEPTANCE-v0.5.0.md`
- **mini 同步**: `sp_compile`/`sp_index`/`sp_semantic`/`ssot_check`/`steward.sh` 已同步并跑通；薄壳 `--check` 通过


## [0.4.0] - 2026-10-21 — 读侧自动化与门禁

- **feat**: `hooks/` 三件——`SessionStart`（指针/现场态）、`UserPromptSubmit`（回忆句式触发 top-3）、`Stop`（机械草稿，同 sid 默认 600s 去抖，不写语义）
- **feat**: `scripts/install-hooks.sh`——幂等合并 settings（保留已有 hooks）、自动备份、`--dry`、`--uninstall`；Qoder 默认 / Claude 用 `--settings`
- **feat**: `tools/steward.sh` + `scripts/install-steward.sh`——6h 索引增量 + 自查 + 草稿计数；launchd/systemd，可卸载
- **feat**: `tools/session-gate.sh`——发布/交接门禁，查当前 sid8 是否在 `sessions/registry.md`；退出码 0/1/2
- **feat**: `tools/recall-phrases.json` 作为回忆句式单一真源；hook 读取 + 缺文件 fallback；8399 不在时 hook 可按需拉起（`SSOT_EMBED_AUTOSTART=0` 可关；steward 只探测不拉起）
- **fix**: `kb_index` 排除 `sessions/_pending`（Stop 草稿不入检索），并在排除目录/`.kbignore` 变更后清理孤儿块
- **docs**: 新增 `docs/HOOKS.md`；`PROTOCOLS.md` 增子 agent 检索与发布/交接门禁；开机块/ssmap 增「子 agent brief 必带检索规则+path:line」
- **docs**: 新增 `docs/ACCEPTANCE-v0.4.2.md`（隔离 HOME 的 hooks/门禁/去抖/索引卫生验收矩阵）
- **边界**: `update.sh` 只同步脚本，不自动改 settings/定时器；opencode 插件当前仍内嵌句式副本（下一轮迁移到 `recall-phrases.json`，见 `docs/HOOKS.md` §五）


## [0.3.1] - 2026-10-19 — 工作机反馈批一（施工单 2026-10-16/17）

- **fix(P0-1)**: `docs/SEMANTIC.md` llama.cpp 首选改官方 Release 二进制（brew 降为备选并注明滞后）；参考版本 **b11681**；模型体积改 **≈532MiB（557,950,176 B）**；新增「零、自检」（health / 768 维 / 无 NaN / 范数≈1 / 小样索引）
- **fix(P0-2)**: `SETUP.md` 第 3 步改为 `sp_compile.py --mem --deploy` 薄壳下发，删除手工并入（会被第 6 步覆盖）
- **fix(P0-3)**: 去掉模板/技能硬编码仓库路径；`setup.sh`/`update.sh` 注入 `~/ssot/profile/.kit-path`；`SETUP/UPGRADE/METHOD` 改用 `KIT` 变量
- **fix(P1-4)**: 补 0.3.0 条目；`VERSION` → 0.3.1；规则：改 `sp_compile`/协议 = 必升 VERSION + 记 CHANGELOG
- **fix(P1-5)**: `kb_index.py` 排除 `compile/` 生成物
- **fix(P1-5b)**: 块器超长行硬切（`max_len=1600`）+ 批量嵌入失败拆批重试 + 单块跳过计数（有跳过的文件下轮重试）；`UPGRADE.md` 收录「`| tail` 假绿」教训
- **feat(P1-6)**: `kb_index.py` 支持 `~/ssot/.kbignore`（fnmatch，相对 root）；`SEMANTIC.md` 补说明
- **fix(P1-7)**: `ssot_check.MEM_WARN(24000)` 与 `sp_compile.HARD_LIMIT(25000)` 注释互指
- **feat(P1-8)**: `scan_sessions.py` 递归覆盖三种盘上布局（flat / `transcript/` / 目录布局）+ app 主库（`chat_sessions`）按 sid8 双向补全；输出加第 6 列 `class`（`app-only` 可辨）
- **feat(P2-15)**: 检索可用性闭环——新增 `scripts/install-service.sh`（launchd/systemd --user，`--dry` 可预览）；开机块检索纪律给完整命令（8399）；`ssmap` 增「语义检索（开工三问第 1.5 站）」；`kb_search.py` 追加 `kb-index/search-log.tsv` 留痕，并修正旧路径提示
- **docs(P2-11)**: `PROTOCOLS.md` 增《存量记忆处置三选》（冻结保留 / 冻结+索引[默认] / 渐进提纯）
- **docs(P2-12)**: 开机块「写入口」加优先级声明（本纪律优先于 harness 出厂记忆机制）
- **feat(P2-13)**: 实例骨架新增 `sessions/corpus/_CLEANING.md`；setup/update 补缺清单同步
- **docs(P2-16)**: `PROTOCOLS.md` 增《脚本改写纪律》（读→改→写分离）；`UPGRADE.md` 增《四源重建法 + 五证校验》
- **feat(P2-14 部分)**: 新增 `instance/knowledge/_card-template.md`（四段式 s1 卡 + 大文件读法）
- **待下批**: P2-9（会话原文入索引全链路）/ P2-9b（双层清洗管道）/ P2-10（删除安全闸）/ P2-14 的 5 会话试产——需吸收下游原型并去个人化，见 `docs/FEEDBACK-RESPONSE-2026-10-16.md`
- 下游回复：`docs/FEEDBACK-RESPONSE-2026-10-16.md`


## [0.3.0] - 2026-10-16 — 薄壳全量生成（v0.3）

- `sp_compile.py` v0.3：`MEMORY.md` 改为**全量生成薄壳**——表头 + SSOT 段 + 开机块（源 `profile/harness-boot.md`）
- 存量 `*.md` 整体冻结为档案：预算裁剪 / 去重退休机制退役，新知识写 `~/ssot/inbox/`
- 本版起 `VERSION` 与 `sp_compile` 自述版本对齐（此前 `VERSION` 停在 0.2.1）


## [0.2.1] - 2026-10-16 — 开源就绪面

- 新增 `LICENSE`（MIT）· `README.en.md`（英文版）
- README 重写为公共口吻：问题三则 / 方案四件 / **与现有方案的关系**（vs 应用内嵌记忆 API、vs 记忆服务器类、vs 手维护 CLAUDE.md）/ 状态区
- 定位显式化：「文件即真相 + 编译式入口」的记忆治理模式 + 配套落地件
- 状态区固定：种子用户 dogfooding 中；开源准备（License ✅ / 英文 README ✅ / 首发演示 ⏳ / 内容零外泄闸 ✅）


## [0.2.0] - 2026-10-16 — 双机分发架构

- **重构为上游-下游分发**：上游（macmini）迭代系统件并 `publish`；下游（工作机）`git pull + update.sh` 升级
- **根路径统一为 `~/ssot`**（与上游同名同构；工具零改动直跑）
- 新增：`instance/` 实例骨架 · `tools/sp_compile.py`（薄壳编译）· `tools/ssot_check.py`（自查）· `docs/ARCHITECTURE.md`（系统全貌）· `docs/PROTOCOLS.md`（协议合订）· `UPGRADE.md`（升级通道）· `VERSION`
- 变更：`setup.sh` 改为实例展开（幂等）；`scan_sessions.py` / `kb_*.py` / `serve_embed.sh` 迁入 `tools/` 并对齐新根
- 红线明确：仓库零内容（发布白名单制）；下游只 pull 永不 push
- 注：0.1.0 的位置约定（`~/ssot-work`）已由本版取代


## [0.1.0] - 2026-10-16 — 初始骨架

- 会话台账 SSMAP + 知识库 + 可选语义检索：指南（SETUP/docs）+ 脚本基建（setup/scan/语义三件）+ 模板


## 工作机提案（经用户转交）

（空——待第一条）
