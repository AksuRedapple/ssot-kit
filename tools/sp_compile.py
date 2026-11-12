#!/usr/bin/env python3
"""sp_compile · SSOT → harness 入口候选编译器 (v0.3)
用法:
  python3 sp_compile.py --mem            # → compile/MEMORY.candidate.md + report（只落 compile/）
  python3 sp_compile.py --mem --target ~/.claude/CLAUDE.md   # 指定落点(CC/opencode/任意入口)
  python3 sp_compile.py --mem --deploy   # 生成并切换（超限拒切；前版备份到 compile/）
  python3 sp_compile.py --check          # 现役薄壳 vs 实时生成 对账（0=一致，供 steward）
  python3 sp_compile.py --claude         # → compile/CLAUDE.candidate.md
纪律: 只读正本与旧入口；候选只落 compile/；切换仅经 --deploy（默认不动任何现行文件）。
v0.3（2026-10-16 薄壳化 · 用户拍板）：MEMORY.md 改为**全量生成薄壳**——表头 + SSOT 段 + 开机块
    （开机块源 = profile/harness-boot.md）。存量段/预算裁剪/去重退休机制整体退役：全部 *.md 已
    冻结为档案（正本转 SSOT 侧），新知识写 ~/ssot/inbox/——「裁尾事故」类问题从机制上消除。
v0.2（2026-10-15）：去重退休 + A-max 动态读 + --deploy 硬限校验 + 前版备份。
v0.1（2026-10-13）：SSOT 段生成。
"""
import os, re, sys, shutil, datetime, subprocess, json

SSOT    = os.path.expanduser('~/ssot')
COMPILE = os.path.join(SSOT, 'compile')
Q_MEM   = os.path.expanduser('~/.qoder/memory/MEMORY.md')

def _target():
    if '--target' in sys.argv:
        i = sys.argv.index('--target')
        if i + 1 < len(sys.argv):
            return os.path.expanduser(sys.argv[i + 1])
    return os.environ.get('SSOT_MEM_TARGET') or Q_MEM

MEM_PATH = _target()
CLAUDE  = os.path.expanduser('~/.claude/CLAUDE.md')

VERSION = 'v0.3'
HARD_LIMIT = 25000   # Qoder 装载硬限（薄壳远在其下；与 ssot_check 告警线 24000 对齐，留 1000B 余量）

def b(s):  # 含换行的整行字节
    return len(s.encode('utf-8')) + 1

def chunks_label():
    """能力声明必须来自构建产物：BUILD.json 的 chunks>0 才敢承诺可搜"""
    try:
        d = json.load(open(os.path.join(SSOT, 'S2-index', 'semantic', 'BUILD.json')))
        n = int(d.get('chunks') or 0)
        ts = (d.get('built_at') or '')[:16].replace('T', ' ')
        if n > 0:
            return f"{n:,} 块 · 建于 {ts}"
        return "**语义检索当前不可用（chunks=0，索引重建中）**"
    except Exception:
        return "**语义检索当前不可用（无 BUILD.json）**"


def a_max():
    try:
        txt = open(os.path.join(SSOT, 'knowledge', 'assertions.md')).read()
        ns = [int(m) for m in re.findall(r'^## A(\d+)', txt, re.M)]
        return max(ns) if ns else '-'
    except Exception:
        return '-'

def gen_ssot_lines():
    """SSOT 段：从正本结构生成指针行"""
    out = []
    out.append("- **[SSOT 全局记忆中枢](~/ssot/START.md)** — 跨 harness 记忆正本（不隶属任何工具目录）：读档入口 `~/ssot/START.md`；线索 `lines/`；贡献写 `inbox/`；证据 `evidence/`")
    ldir = os.path.join(SSOT, 'lines')
    for fn in sorted(os.listdir(ldir)) if os.path.isdir(ldir) else []:
        if fn.startswith('_') or not fn.endswith('.md'):
            continue
        txt = open(os.path.join(ldir, fn)).read()
        tm = re.search(r'^# 线：(.+)$', txt, re.M)
        sm = re.search(r'^> 状态: (.+?) —', txt, re.M)
        title = tm.group(1) if tm else fn[:-3]
        status = sm.group(1) if sm else '?'
        out.append(f"- **[线·{title}](~/ssot/lines/{fn})** — 状态: {status}；线页自包含，读完可接手")
    out.append("- **[用户画像](~/ssot/profile/user.md)** — 身份/目标/机器拓扑/敏感线（指针型）")
    out.append("- **[协作纪律](~/ssot/profile/collaboration.md)** — 委托自治/证据先于直觉/落盘纪律；全会话照做")
    out.append(f"- **[断言库](~/ssot/knowledge/assertions.md)** — 跨项目操作坑成文法 A{a_max()}（动跨机写脚本前按 tag 扫）")
    out.append("- **[术语表](~/ssot/knowledge/glossary.md)** — ss/pt/PBE/qqqq/打喷嚏/窄门…")
    out.append("- **[会话索引](~/ssot/sessions/registry.md)** — 会话登记表 append-only（一行/会话 + resume 指针）")
    out.append("- **[贡献入口](~/ssot/inbox/README.md)** — 任何 harness 写这里（fact 必带 source / decision 必带 owner）；本索引用行 ≤50 汉字")
    return out

def gen_boot_lines():
    """开机块：抽 profile/harness-boot.md 的 `- ` 行（正本改这里）"""
    src = os.path.join(SSOT, 'profile', 'harness-boot.md')
    return [l for l in open(src).read().splitlines() if l.startswith('- ')]

def git_commit():
    try:
        return subprocess.check_output(['git', '-C', SSOT, 'rev-parse', '--short', 'HEAD'],
                                       text=True, stderr=subprocess.DEVNULL).strip() or '-'
    except Exception:
        return '-'

def compile_mem():
    ssot_lines = gen_ssot_lines()
    boot_lines = gen_boot_lines()
    commit = git_commit()
    old_bytes = len(open(MEM_PATH).read().encode()) if os.path.isfile(MEM_PATH) else 0
    header = (f"# MEMORY（SSOT 编译薄壳 · 生成 {datetime.datetime.now():%Y-%m-%d} · 正本 commit {commit}）\n"
              f"> 正本在 ~/ssot：本文件由 sp_compile {VERSION} **全量生成**，勿手改（改正本 → 重编译下发）。\n"
              f"> 新知识写 ~/ssot/inbox/；本目录 *.md 为历史存量档案（冻结）；主题细则按需读。\n")
    os.makedirs(COMPILE, exist_ok=True)
    with open(os.path.join(COMPILE, 'MEMORY.candidate.md'), 'w') as f:
        f.write(header + '\n')
        f.write(f"<!-- ══ SSOT 段（生成 {len(ssot_lines)} 行 / {sum(b(l) for l in ssot_lines)} B） ══ -->\n")
        f.write('\n'.join(ssot_lines) + '\n\n')
        f.write(f"<!-- ══ 开机块（生成自 profile/harness-boot.md · {len(boot_lines)} 行） ══ -->\n")
        f.write('\n'.join(boot_lines) + '\n')
    cand = open(os.path.join(COMPILE, 'MEMORY.candidate.md')).read()
    nb = len(cand.encode())
    with open(os.path.join(COMPILE, 'MEMORY.report.md'), 'w') as f:
        f.write(f"# MEMORY.md 编译报告 · {datetime.datetime.now():%Y-%m-%d %H:%M} · sp_compile {VERSION}（薄壳）\n\n")
        f.write(f"- 正本 commit：{commit}\n")
        f.write(f"- 旧入口 ~/.qoder/memory/MEMORY.md：{old_bytes:,} B\n")
        f.write(f"- 候选：{nb:,} B（硬限 {HARD_LIMIT:,}，余 {HARD_LIMIT - nb:,} B）\n")
        f.write(f"- 组成：表头 3 行 + SSOT 段 {len(ssot_lines)} 行 + 开机块 {len(boot_lines)} 行\n")
    return old_bytes, nb, len(ssot_lines), len(boot_lines)

def compile_claude():
    parts = []
    parts.append("# CLAUDE.md — 用户级协作画像（跨项目，所有会话生效）")
    parts.append(f"> ⚡ 本文件为 **SSOT 编译产物**（生成 {datetime.datetime.now():%Y-%m-%d %H:%M} · sp_compile {VERSION}）")
    parts.append("> 正本：`~/ssot/profile/collaboration.md` + `~/ssot/profile/user.md` —— **改动请改正本**，本文件由编译单向下发。")
    parts.append("> SSOT 读档入口：`~/ssot/START.md`（工作线全览）；贡献写 `~/ssot/inbox/`\n")
    parts.append(open(os.path.join(SSOT, 'profile', 'collaboration.md')).read().strip().replace('{{SSOT_CHUNKS}}', chunks_label()))
    parts.append("\n" + open(os.path.join(SSOT, 'profile', 'user.md')).read().strip())
    os.makedirs(COMPILE, exist_ok=True)
    dst = os.path.join(COMPILE, 'CLAUDE.candidate.md')
    with open(dst, 'w') as f:
        f.write('\n\n'.join(parts) + '\n')
    return dst

def deploy_mem():
    cand = os.path.join(COMPILE, 'MEMORY.candidate.md')
    if not os.path.isfile(cand):
        print('❌ 无候选——先跑 --mem'); return False
    txt = open(cand).read()
    n = len(txt.encode('utf-8'))
    if n > HARD_LIMIT:
        print(f'❌ 候选 {n:,} B 超硬限 {HARD_LIMIT:,}，拒绝部署'); return False
    bak = os.path.join(COMPILE, f"MEMORY.pre-compile-{datetime.datetime.now():%Y%m%d-%H%M}.md")
    if os.path.exists(MEM_PATH):
        shutil.copy2(MEM_PATH, bak)
        bak_note = f"前版备份 {os.path.basename(bak)}（git 亦留底）"
    else:
        bak_note = "原文件不存在（首次部署/入口曾退役），无需备份"
    os.makedirs(os.path.dirname(MEM_PATH), exist_ok=True)
    shutil.copy2(cand, MEM_PATH)
    print(f'✅ 已切换 MEMORY.md（{n:,} B）；{bak_note}')
    return True

def check_mem():
    """现役薄壳 vs 实时生成 对账（SSOT 段 + 开机块；供 steward 巡检；0=一致 1=漂移）"""
    if not os.path.exists(MEM_PATH):
        print('✅ MEMORY.md 不存在——跳过检查（入口未启用）')
        return 0
    txt = open(MEM_PATH).read()
    ms = re.search(r'<!-- ══ SSOT 段.*?-->\n(.*?)\n\n<!-- ══ 开机块', txt, re.S)
    mb = re.search(r'<!-- ══ 开机块.*?-->\n(.*)$', txt, re.S)
    if not ms or not mb:
        print('❌ 现役 MEMORY.md 无薄壳段标记（尚未切薄壳？）'); return 1
    cur_s = [l for l in ms.group(1).splitlines() if l.strip()]
    cur_b = [l for l in mb.group(1).splitlines() if l.strip()]
    gen_s, gen_b = gen_ssot_lines(), gen_boot_lines()
    problems = []
    if cur_s != gen_s: problems.append(('SSOT 段', cur_s, gen_s))
    if cur_b != gen_b: problems.append(('开机块', cur_b, gen_b))
    if not problems:
        print(f'✅ 薄壳与生成一致（SSOT {len(cur_s)} 行 + 开机块 {len(cur_b)} 行）'); return 0
    import difflib
    for name, cur, gen in problems:
        print(f'⚠️ {name}漂移：现役 {len(cur)} 行 / 生成 {len(gen)} 行——重跑 sp_compile --mem --deploy')
        for l in list(difflib.unified_diff(cur, gen, lineterm='', n=0))[:14]:
            print(l)
    return 1

if __name__ == '__main__':
    if '--mem' in sys.argv:
        ob, nb, s, bl = compile_mem()
        print(f"✅ MEMORY.candidate.md + report（{VERSION} 薄壳）")
        print(f"   旧入口 {ob:,} B → 候选 {nb:,} B（硬限 {HARD_LIMIT:,}，余 {HARD_LIMIT-nb:,} B）")
        print(f"   组成: SSOT 段 {s} 行 + 开机块 {bl} 行")
        if '--deploy' in sys.argv:
            deploy_mem()
    elif '--check' in sys.argv:
        sys.exit(check_mem())
    elif '--deploy' in sys.argv:
        # 2026-10-15 修（脚枪案）：裸 --deploy 曾直接切 compile/ 里的**过期候选**——
        # 现改为先重编译再切换（与 --mem --deploy 等价），杜绝用旧候选覆盖现行文件。
        compile_mem()
        deploy_mem()
    elif '--claude' in sys.argv:
        print(f"✅ {compile_claude()}")
    else:
        print(__doc__)
