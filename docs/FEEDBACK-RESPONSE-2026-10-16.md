# 上游回复 · 工作机施工单（2026-10-16/17）

> 对应文件：工作机《ssot-kit 工作机首装全记录与逐条改造指令》
> 回复日期：2026-10-19 ｜ 版本：**0.3.1**（上游已提交，下一次 `git pull` 可取）

## 一、逐条结论

| 条目 | 结论 | 改动 / 说明 |
|---|---|---|
| P0-1 SEMANTIC 安装 | **已修** | 官方 Release 首选、brew 降备选；b11681 参考版本；体积 532MiB；新增「零、自检」 |
| P0-2 SETUP 第 3 步 | **已修** | 改为 `sp_compile.py --mem --deploy`；删除手工并入；注明「勿手改 MEMORY.md」 |
| P0-3 硬编码路径 | **已修** | 模板/技能改中性指针；setup/update 注入 `~/ssot/profile/.kit-path`；文档用 `KIT` 变量 |
| P1-4 版本双轨 | **已修** | 补 0.3.0 条目；VERSION 0.3.1；`sp_compile` v0.3 ≤ VERSION |
| P1-5 compile/ 入索引 | **已修** | `kb_index.gen()` 排除 `compile` |
| P1-5b 超长行崩索引 | **已修** | 硬切 1600 + 拆批重试 + 单块跳过计数；有跳过的文件不记 md5，下轮重试；UPGRADE 收录假绿教训 |
| P1-6 .kbignore | **已修** | `kb_index.py` 支持根目录 `.kbignore`（fnmatch，相对 root） |
| P1-7 魔法数 | **已修** | `MEM_WARN=24000` 与 `HARD_LIMIT=25000` 注释互指 |
| P1-8 普查盲区 | **已修** | 递归三布局 + app 主库按 sid8 双向补全；输出第 6 列 `class` |
| P2-15 检索可用性 | **已修** | `install-service.sh`（launchd/systemd）+ 开机块完整命令 + ssmap 检索节 + search-log 留痕 |
| P2-11 存量记忆 | **已修（文档）** | PROTOCOLS《存量记忆处置三选》，默认推荐「冻结+索引」 |
| P2-12 写入口张力 | **已修（文档）** | 开机块「写入口」加优先级声明 |
| P2-13 corpus 骨架 | **已修** | `instance/sessions/corpus/_CLEANING.md`；setup/update 补缺 |
| P2-14 s1 卡模板 | **部分** | 四段式模板已进 kit（`instance/knowledge/_card-template.md`）；5 会话试产待下游 |
| P2-16 运维教训 | **已修（文档）** | PROTOCOLS《脚本改写纪律》+ UPGRADE《四源重建法/五证校验》 |
| P2-9 会话入索引 | **下批** | 需吸收下游 `ssot_pipeline.py` 并去个人化（导出/脱敏/入料三件） |
| P2-9b 双层清洗 | **下批** | 同上；L1 正则与 L2 triage 已在本回复留档，待与原型合并 |
| P2-10 删除安全闸 | **下批** | 三证判据明确，但需下游文件命名约定；先只做只读 guard，不内置删除 |
| P2-14 试产 | **待下游** | 模板已给；用 5 个新会话试产并回传偏差 |

## 二、验收记录（上游实测，2026-10-19）

| 项 | 命令 / 方法 | 结果 |
|---|---|---|
| P0-1 | 本机 8399 活服务自检 | `dim 768 / norm 1.0 / nan False` |
| P0-2 | 隔离 HOME 首装 → `sp_compile --mem --deploy` → `--check` | 薄壳一致（SSOT 8 行 + 开机块 10 行），二次部署内容不变 |
| P0-3 | `grep -rn "ssot-kit" instance/ skills/ \| grep -v 系统件仓库` | 0 命中；`profile/.kit-path` 正确写入 |
| P1-5 | 含 `compile/`、`skip/`、240KB 单行、正常文件的临时根 | compile=0 块、skip=0 块、正常=1 块；`max chunk len 1600`；exit 0 |
| P1-5b | monkeypatch 模拟批失败/单块 500 | 拆批 `[3]→[1,2]→[1,1]`，单块失败返回 None 并计数 |
| P1-6 | `.kbignore` 写 `skip/*` | 该路径 chunks=0 |
| P1-8 | 本机真实目录 + 合成三布局 | 77 会话（盘上 61 + app-only 16）；flat/transcript/nested 三类均识别 |
| P2-15 | `install-service.sh --dry` + `plutil -lint` | plist 合法；**未在本机实际加载**（本机 8399 已有服务在跑，避免抢占）；重启自启待下游验收 |
| P2-13 | 隔离 HOME setup | `sessions/corpus/_CLEANING.md` 存在 |

## 三、下游下轮 pull 后建议动作

1. `KIT="$(cat ~/ssot/profile/.kit-path)"; cd "$KIT" && git pull && bash scripts/update.sh`
2. 按新版 `docs/SEMANTIC.md` 零节跑三条自检（模型已就位则无需重拉）
3. 重建索引：`python3 ~/ssot/tools/kb_index.py --full`，确认完成行无「块跳过」
4. 跑 `python3 ~/ssot/tools/scan_sessions.py`，核对总行数 ≥ 860 且 app-only 有标注
5. 按需 `bash scripts/install-service.sh`，重启后 `curl 127.0.0.1:8399/health`

## 四、待确认

- **P2-10**：三证的文件命名约定（registry 行 / s0 语料 / s1 卡）请下游给一个真实样例路径；确认后做只读 `guard`，删除动作仍走人工 + 废纸篓。
- **P2-14**：卡模板字段是否够用；5 个试产卡的「归位建议」实际可执行率请回传。
- **P2-9/9b**：下游 `ssot_pipeline.py` 是否可以脱敏后作为参考实现入库；若可以，请只提供七子命令的接口与参数，不带任何本机路径/业务词。
