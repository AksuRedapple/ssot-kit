# SEMANTIC · 可选语义检索层

> 主系统（台账 + 知识库）不依赖本层——grep 与台账已可用。装上本层后，可以「按意思搜」全部知识。

> 说明：`BUILD.json` 的 `commit` 为 `-` 表示实例不是 git 仓（正常形态），不是错误。

## 组成

> 前置：`python3` ≥3.10 + `numpy`（`pip install numpy`）。仅 macOS 已实测；Linux 可用但未系统验证。

- **嵌入模型**：EmbeddingGemma（多语言，~300M 激活；BF16 GGUF **≈532MiB**，文本嵌入主文件 557,950,176 B）
- **服务**：llama.cpp 的 `llama-server`（OpenAI 兼容 `/v1/embeddings`，纯本地）
- **脚本**：`~/ssot/tools/` 下 `sp_index.py`（建索引）+ `sp_semantic.py`（检索）+ `serve_embed.sh`（起服务）；随升级通道更新

## 零、自检（装完先跑）

按本文装完后，先过这三条，再建索引：

```bash
# ① 服务活着
curl -s http://127.0.0.1:8399/health          # → {"status":"ok"}

# ② 嵌入维度 / NaN / 范数
curl -s http://127.0.0.1:8399/v1/embeddings \
  -H 'Content-Type: application/json' -d '{"input":["自检"]}' \
  | python3 -c "import sys,json,math;v=json.load(sys.stdin)['data'][0]['embedding'];n=math.sqrt(sum(x*x for x in v));print('dim',len(v),'norm',round(n,4),'nan',any(x!=x for x in v))"
# 期望：dim 768 · norm≈1.0 · nan False

# ③ 索引可建（小样，不碰正式索引）
# 索引是整库的（没有 --root/--db 参数）；首次跑就是全量
python3 ~/ssot/tools/sp_index.py --incremental
```

**判据**：① 健康 ② `dim 768 / nan False / norm≈1.0`。任何一条不过，先修安装，别急着建全量索引。

## 一、装 llama.cpp

**首选：官方 Release 二进制**（版本可控、不滞后）。到
`https://github.com/ggml-org/llama.cpp/releases` 选 **macOS arm64** 资产
（注意资产是 `.tar.gz` 不是 zip），解压到固定目录：

```bash
mkdir -p ~/.local/opt/llama-nightly
# 以实际下载的资产名为准（下面为示例）
tar -xzf ~/Downloads/llama-b11681-bin-macos-arm64.tar.gz -C ~/.local/opt/llama-nightly --strip-components=1
export PATH="$HOME/.local/opt/llama-nightly:$PATH"
llama-server --version
```

**版本要求**：实测可用 build = **b11681（0.7.0-dev）**。**装载失败先升版本**——报
`unknown model architecture: 'gemma-embedding2'` 就是版本太老。

**备选：Homebrew**（注意 brew 稳定版常滞后，装载失败即升 nightly）：
```bash
brew install llama.cpp            # 若报 unknown model architecture，改用上面的官方 Release
```

> 不要把 brew 当默认路径：2026-10 实测 brew 稳定版 build 11429 装不上本模型。

## 二、拉模型（权重不入库，按需自拉）

放到 `~/ssot/models/embeddinggemma-2-BF16.gguf`。

```bash
mkdir -p ~/ssot/models
# 官方 GGUF 仓（HuggingFace）
curl -L -o ~/ssot/models/embeddinggemma-2-BF16.gguf \
  "https://huggingface.co/ggml-org/embeddinggemma-2-GGUF/resolve/main/embeddinggemma-2-BF16.gguf"
# 国内网络慢：换镜像域名 hf-mirror.com（同路径）；或使用代理
```

体积口径：该文件 **557,950,176 B ≈ 532MiB**（BF16 文本嵌入主文件，sha256 与上游 LFS 一致）。
网传的「GB 级」体积是含 mmproj 等附件的整包口径，不是本文件。

⚠️ **必须用 BF16 档**：fp16 档在部分后端上会静默输出 NaN（索引全废且无报错）。

## 三、起服务

```bash
nohup bash ~/ssot/tools/serve_embed.sh > /tmp/embed.log 2>&1 &
sleep 3 && curl -s http://127.0.0.1:8399/health   # → {"status":"ok"}
```

默认端口 8399；改端口用环境变量 `EMBED_PORT`，模型路径放默认位即无需配置。
若 `llama-server` 不在 PATH，用 `LLAMA_SERVER=/path/to/llama-server` 指定。
**常驻**（可选，推荐）：`bash scripts/install-service.sh`——见 §六（在系统件仓库根执行，仓库位置见 `~/ssot/profile/.kit-path`）。

## 四、建索引 + 检索

```bash
python3 ~/ssot/tools/sp_index.py --incremental      # 增量建索引（源文件未变则跳过）
python3 ~/ssot/tools/sp_semantic.py "那条线之前在聊什么" --mode route3 --top 5
```

- 索引产物：`~/ssot/kb-index/kb.db`（sqlite；建议加入本机 .gitignore，不入任何版本库）
- 索引默认**排除** `compile/`（薄壳候选等生成物，与正本重复）、`sessions/_pending/`（Stop 草稿）、`.index/ models/ .git/ __pycache__/`
- **隐私闸**：文件命中完整密钥形态（`sk-…`/`ghp_…`/`AKIA…`/`hf_…`/私钥块）时**跳过不索引**，并在完成行报告数量；先在 `.kbignore` 或脱敏中处理，不要为了多索引而绕过
- 首次建索引约 1-3 分钟（视语料大小）；改完台账可重跑（增量，秒级）
- 想连**会话原文**一起搜：把会话导出为 md 放进 `~/ssot/sessions/corpus/` 再重跑索引
- 检索留痕：每次检索会在 `~/ssot/logs/semantic-calls.jsonl` 留一行（时间 + query + 耗时 + 命中数），用数据回答「到底有没有在用」

### 索引新鲜度（别把「落后 N commits」当重建令）

- `ssot_check` 的 `[build] 落后 N commits` 只是新鲜度提示：索引对应 `BUILD.json` 里的 commit，落后了跑一次 `--incremental` 即可
- **契约升级不触发全量重建**：索引是派生物、不纳入迁移；`sp_migrate` 只给 meta/账本/BUILD 补 `schema`，不碰 `kb-index/kb.db`
- 只有**嵌入模型或分块规则变更**才需要全量重建；日常增量交给 steward 定时跑
- 重建期间独占索引库，别的进程会 `database is locked`——动手前先确认没有 steward 索引进程在跑

### 增量包与并发（v0.10.0）

- **索引增量 ≠ 向量包增量**：`index.db` 只重嵌变了的源；`pack-vecs.f32` 以前每次全量重建（308k 块约 50s）。v0.10.0 起默认只追加 missing 行，`stale > 2000` / `missing > 5000` 才全量压实。
- **三个开关**：`--no-pack`（只更索引）、`--pack-only`（只更包）、`--full-pack`（强制压实）。批量写入可先 `--no-pack`，最后统一 `--pack-only`。
- **两个索引**：`chunks_id_only on chunks(id)` 让 `select id` 走覆盖索引（40s→0.3s）；`chunks_path_idx on chunks(path)` 让 `delete ... where path=?` 不再全表扫 1.9GB。首次在老库上创建约 80s，之后自动存在。
- **锁等待可见**：`.lock` 记录 pid/启动时间/argv；等锁每 30s 报一次。自动化用 `--no-wait`（拿不到锁 rc=3），手动可用 `--wait-timeout 300`。
- **块级 diff（v0.11.0）**：变更源先取旧块，按 `(text, role, ts)` 复用未变块的向量，只把新块送嵌入；行号变化不影响复用。实测 inbox 追加一行：新嵌 2 块 / 复用 55 块。

## 五、排除清单（.kbignore）

在实例根 `~/ssot/.kbignore` 写一行一 pattern（`#` 注释，`fnmatch` 语义，相对 root）：

```
# 敏感档案与生成物不入索引
knowledge/archive-sensitive/*
lines/_draft-*
```

重建索引时命中即跳过；适合放「不可入库」的历史档案或本机生成物。语料清洗规则与统计建议
另放 `sessions/corpus/_CLEANING.md`，保证「语料≠原文」可追溯。

## 六、常驻服务（可选）

在**系统件仓库根**执行（仓库位置见 `~/ssot/profile/.kit-path`）：

```bash
bash scripts/install-service.sh --dry     # 只打印将生成的单元文件
bash scripts/install-service.sh           # macOS=launchd / Linux=systemd --user，开机自启
```

服务名 `com.ssot.embed`；日志 `/tmp/ssot-embed.log`。安装前确保 `llama-server` 在 PATH
（或传 `--llama /path/to/llama-server`）。

## 七、已知坑

- fp16 → 静默 NaN（见上）
- 太老的 llama.cpp 可能不支持该模型架构——报错就升版本
- 服务挂了（端口无响应）时，`sp_index` / `sp_semantic` 会明确报错，不会静默降级
- 超长单行（如 240KB JSON 粘贴）曾导致嵌入 500 → 进程崩溃；现版对超长行硬切（≤1600 字符）并对失败块拆批重试/计数跳过
