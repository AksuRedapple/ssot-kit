#!/usr/bin/env python3
"""sp_embed_autotune · 嵌入配置建议（保守版：不重启服务、不写索引）

边界（2026-11-18 评审后）：
  - 只读探测 + 只读基准；绝不重启 8399、绝不写 active 索引；
  - 默认 workers=1（并发在 48GB 单机实测为负收益，见 03 号补充）；
  - `--apply` 只写 profile/embed-profile.json；`serve_embed.sh` 下次启动时读取。

用法:
  python3 tools/sp_embed_autotune.py --probe            # 打印建议（默认）
  python3 tools/sp_embed_autotune.py --bench --quick    # 只读基准（当前端口）
  python3 tools/sp_embed_autotune.py --bench --apply    # 基准 + 写 profile
  python3 tools/sp_embed_autotune.py --restore          # 回滚 profile

隔离基准：先在 8398 起临时 llama-server，再 `--port 8398 --bench`。
"""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
PROFILE = os.path.expanduser(os.environ.get(
    'EMBED_PROFILE', os.path.join(ROOT, 'profile', 'embed-profile.json')))
MODEL = os.path.expanduser(os.environ.get(
    'EMBED_MODEL', os.path.join(ROOT, 'models', 'embeddinggemma-2-BF16.gguf')))
BENCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sp_embed_bench.py')


def sh(*args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ''


def hardware():
    total = 0
    if sys.platform == 'darwin':
        try:
            total = int(sh('sysctl', '-n', 'hw.memsize'))
        except Exception:
            total = 0
    elif os.path.exists('/proc/meminfo'):
        for line in open('/proc/meminfo', encoding='utf-8', errors='replace'):
            if line.startswith('MemTotal:'):
                total = int(line.split()[1]) * 1024
                break
    return {'machine': platform.machine(), 'platform': sys.platform,
            'cpu': os.cpu_count() or 1, 'mem_bytes': total,
            'mem_gb': round(total / (1 << 30)) if total else 0}


def model_fp(path=None):
    path = path or MODEL
    if not os.path.isfile(path):
        return 'missing:%s' % os.path.basename(path)
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
    except OSError:
        return 'unreadable'
    return h.hexdigest()[:12]


def props(port):
    try:
        import urllib.request
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/props', timeout=3) as r:
            d = json.loads(r.read())
    except Exception:
        return {}
    gen = d.get('default_generation_settings') or {}
    params = gen.get('params') or {}
    n_ctx = gen.get('n_ctx') or params.get('n_ctx') or d.get('n_ctx')
    return {'total_slots': d.get('total_slots'), 'n_ctx': n_ctx,
            'model_alias': d.get('model_alias') or d.get('model_path')}


def running_config(port):
    """从 ps 里找匹配端口的 llama-server，解析 -c/-b/-ub/--parallel。"""
    out = sh('ps', '-axo', 'pid=,command=')
    best = None
    for line in out.splitlines():
        if 'llama-server' not in line:
            continue
        if f'--port {port}' not in line and f'--port={port}' not in line:
            continue
        best = line
        break
    if not best:
        return {}
    pid = best.strip().split(None, 1)[0] if best.strip() else ''
    def num(flags):
        for f in flags:
            m = re.search(r'(?:^|\s)' + re.escape(f) + r'[=\s]+(-?\d+)', best)
            if m:
                return int(m.group(1))
        return None
    return {'pid': pid, 'cmd': best.strip(), 'c': num(['-c', '--ctx-size']),
            'b': num(['-b', '--batch-size']), 'ub': num(['-ub', '--ubatch-size']),
            'parallel': num(['--parallel', '-np'])}


def detected_model(rc):
    m = re.search(r'--model[=\s]+(\S+)', rc.get('cmd') or '')
    if not m:
        return MODEL
    p = m.group(1)
    if os.path.isabs(p):
        return p
    cwd = ''
    pid = rc.get('pid')
    if pid:
        out = sh('lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn')
        for line in out.splitlines():
            if line.startswith('n'):
                cwd = line[1:]
                break
    return os.path.join(cwd, p) if cwd else p


def _version(exe):
    try:
        r = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=10)
        return (r.stdout + r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else ''
    except Exception:
        return ''


def llama_version(rc=None):
    out = _version(os.environ.get('LLAMA_SERVER', 'llama-server'))
    if not out and rc:
        exe = (rc.get('cmd') or '').split()[1] if len((rc.get('cmd') or '').split()) > 1 else ''
        if exe:
            out = _version(exe)
    return out or 'unknown'


def load_profile():
    try:
        with open(PROFILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def clamp_server(s):
    c = int(s.get('c') or 8192)
    b = int(s.get('b') or 2048)
    ub = int(s.get('ub') or 2048)
    p = int(s.get('parallel') or 4)
    p = max(1, min(p, 64))
    b = max(64, min(b, 16384))
    ub = max(64, min(ub, b))
    c = max(int(c), p * 512)
    return {'c': c, 'b': b, 'ub': ub, 'parallel': p}


def probe(port):
    hw = hardware()
    pr = props(port)
    rc = running_config(port)
    cur = clamp_server({'c': rc.get('c') or pr.get('n_ctx') or 4096,
                        'b': rc.get('b') or 2048,
                        'ub': rc.get('ub') or 2048,
                        'parallel': rc.get('parallel') or pr.get('total_slots') or 1})
    # 保守建议：构建 workers=1；batch 只在 16GB+ 机器上给 128，否则 64；
    # 服务端保持当前配置（不在本工具里重启）。
    batch = 128 if hw['mem_gb'] >= 16 else 64
    mp = detected_model(rc) if rc else MODEL
    return {
        'hardware': hw, 'model_fp': model_fp(mp), 'model_path': mp,
        'llama_version': llama_version(rc),
        'props': pr, 'running': rc,
        'server': cur,
        'client': {'batch': batch, 'workers': 1},
        'fallback': {'server': cur, 'client': {'batch': 32, 'workers': 1}},
        'notes': [
            'workers=1 是当前实测基线；并发在 48GB 单机为负收益，8GB 更不应默认开。',
            '服务端参数保持当前运行值；改 server 配置需重启服务，本工具不自动重启。',
        ],
    }


def run_bench(port, quick, corpus=None):
    cmd = [sys.executable, BENCH, '--port', str(port), '--json']
    if quick:
        cmd.append('--quick')
    if corpus:
        cmd += ['--corpus', corpus]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or 'bench failed').strip()[:500])
    return json.loads(r.stdout)


def choose_client(bench):
    """并发只有在 >5% 收益时才采纳；否则回 workers=1（03 号负结果）。"""
    rows = [r for r in (bench.get('rows') or []) if r.get('throughput')]
    if not rows:
        return None
    best = max(rows, key=lambda r: (r['throughput'], -r['workers']))
    one = [r for r in rows if r['workers'] == 1]
    if best['workers'] > 1 and one:
        b1 = max(one, key=lambda r: r['throughput'])
        if best['throughput'] < b1['throughput'] * 1.05:
            return b1
    return best


def write_profile(data):
    os.makedirs(os.path.dirname(PROFILE), exist_ok=True)
    backup = None
    if os.path.exists(PROFILE):
        backup = PROFILE + '.bak'
        shutil.copy2(PROFILE, backup)
    tmp = PROFILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, PROFILE)
    return backup


def restore():
    bak = PROFILE + '.bak'
    if not os.path.exists(bak):
        print(f'没有备份: {bak}', file=sys.stderr)
        return 2
    shutil.copy2(bak, PROFILE)
    print(f'已回滚: {PROFILE} ← {bak}')
    return 0


def print_human(p, bench=None):
    hw = p['hardware']
    print(f"host: {hw['machine']} / {hw['platform']} / {hw['cpu']}c / {hw['mem_gb']}GB")
    print(f"model: {p.get('model_path', '-')} · fp {p['model_fp']} · llama: {p['llama_version']}")
    if p['running']:
        print(f"running: c={p['running'].get('c')} b={p['running'].get('b')} "
              f"ub={p['running'].get('ub')} parallel={p['running'].get('parallel')}")
    print(f"建议 server: {p['server']}")
    print(f"建议 client: {p['client']}  (workers=1 为基线)")
    if bench:
        b = bench.get('best') or {}
        print(f"基准最佳: batch={b.get('batch')} workers={b.get('workers')} "
              f"{b.get('throughput')} 条/秒")
    for n in p.get('notes', []):
        print(f"  - {n}")


def main():
    ap = argparse.ArgumentParser(
        epilog='示例:\n  sp_embed_autotune.py --probe\n  sp_embed_autotune.py --bench --quick --apply',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--probe', action='store_true', help='只读探测 + 建议（默认）')
    ap.add_argument('--bench', action='store_true', help='跑只读基准（当前端口）')
    ap.add_argument('--apply', action='store_true', help='写 profile（否则只打印）')
    ap.add_argument('--restore', action='store_true', help='回滚 profile 到 .bak')
    ap.add_argument('--quick', action='store_true', help='快速基准（128 块）')
    ap.add_argument('--port', type=int, default=8399)
    ap.add_argument('--corpus', help='基准语料 JSONL（默认从 S1 抽样）')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    if a.restore:
        return restore()

    p = probe(a.port)
    bench = None
    if a.bench:
        try:
            bench = run_bench(a.port, a.quick, a.corpus)
        except Exception as e:
            print(f'❌ 基准失败: {e}', file=sys.stderr)
            return 2
        chosen = choose_client(bench)
        if chosen:
            p['client'] = {'batch': chosen['batch'], 'workers': chosen['workers']}
            p['measured'] = {'throughput_chunks_per_s': chosen['throughput'],
                             'at': bench['at'], 'bench_seconds': None, 'mode': 'bench'}
        else:
            p['measured'] = {'throughput_chunks_per_s': None, 'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                             'mode': 'bench-failed'}
    else:
        p['measured'] = {'throughput_chunks_per_s': None, 'at': None, 'mode': 'heuristic'}

    p.update({'schema': 1,
              'hardware_fp': f"{p['hardware']['machine']}-{p['hardware']['mem_gb']}g-"
                             f"{p['hardware']['platform']}-{p['hardware']['cpu']}c",
              'source': 'bench' if bench else 'probe'})

    if a.apply:
        backup = write_profile(p)
        if not a.json:
            print(f"✅ 已写 {PROFILE}" + (f"（备份 {backup}）" if backup else '（首次写入，无备份）'))
            print('   下次重启生效: bash ~/ssot/tools/serve_embed.sh')
            print('   launchd: launchctl kickstart -k gui/$(id -u)/com.ssot.embed')
    if a.json:
        print(json.dumps({'profile': p, 'bench': bench, 'profile_path': PROFILE,
                          'applied': bool(a.apply)}, ensure_ascii=False, indent=2))
    elif not a.apply:
        print_human(p, bench)
        print(f"\nprofile: {PROFILE}（未写；加 --apply）")
    return 0


if __name__ == '__main__':
    sys.exit(main())
