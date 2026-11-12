# 术语表（中英对照）

> 面向第一次接触本系统的读者。出现"这词什么意思"时先查这里。

| 术语 | 英文 | 一句话 |
|---|---|---|
| **正本** | canonical source | 唯一真相的文件（断言库、线页、台账）；其它地方都是它的副本或视图 |
| **薄壳** | thin shell | 常驻 agent 记忆的入口文件：只有指针与纪律，细节按需拉；由 `sp_compile.py` 生成 |
| **编译** | compile | 把正本压成薄壳的动作；产物可重复生成，不手工编辑 |
| **台账** | registry / ledger | 一行一会话的登记册：谁、哪条线、续点在哪 |
| **线页** | line page | 一条工作线的自包含页：现状、判据、在途、相关文件；读完即可接手 |
| **开工三问** | three opening questions | 开工前先问：新开还是接续？接哪条线？续点是什么？ |
| **收尾一行** | one-line close | 收工时在台账写一行：做了什么、续点在哪 |
| **贡献流** | inbox | 一行一条的待提纯输入（fact 带 source / decision 带 owner） |
| **提纯** | distill | 把贡献流里的条目归位到线页/断言；判定口径见 PROTOCOLS「写入协议」（整行不含 `→` = 未提纯） |
| **断言** | assertion | 一条可执行、可被引用的判断（事实/处方/教训），有编号（A1、A2…） |
| **撞正本** | clash with canonical | 新候选与既有断言语义重复时的判定；重复的不再入册 |
| **证据层 / 转录层 / 索引层 / 判断层** | S0 / S1 / S2 / S3 | 四层单向流动：原件 → 可读转录 → 可检索索引 → 可引用判断 |
| **S1 五件套** | S1 bundle | `meta.json` / `raw.jsonl` / `summary.json` / `transcript.jsonl` / `transcript.md` |
| **普查** | inventory scan | 盘点存量会话（有多少、转了多少、索引了多少） |
| **覆盖审计** | coverage audit | 每源"原始/S1/已索引"三列对账，找出没进系统的会话 |
| **值守** | steward | 定时任务：保鲜巡检、触发捕获、生成周报 |
| **保鲜** | freshness | 页面/条目的最后更新距今多久；超期进周报或告警 |
| **交接** | handoff | 收工时写的四段（目标/已确认事实/否决过的路/下一步），供下一个会话接手 |
| **预算** | budget | 给 agent 的上下文字数/token 上限；超限即截断，所以要分级下发 |
| **少漏 / 少幻觉** | recall / faithfulness | 两个独立目标：读路径负责"不漏"，写路径负责"可信" |

## 平台相关

| 词 | 含义 |
|---|---|
| **harness** | 跑 agent 的客户端（Qoder / Claude Code / Codex / DeepSeek Harness / opencode …） |
| **launchd / systemd --user** | macOS / Linux 的常驻服务方式 |
| **嵌入服务** | 本地 `llama-server`（:8399），提供 `/v1/embeddings` |
