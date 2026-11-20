#!/usr/bin/env python3
"""sp_embed_bench · 嵌入吞吐基准（只读，不写索引、不重启服务）

用途：在**不碰 active 索引**的前提下，测 batch × workers 的真实吞吐；
结论供 sp_embed_autotune 写 profile，或直接用于 issue 复现。

用法:
  python3 tools/sp_embed_bench.py --port 8399 --quick
  python3 tools/sp_embed_bench.py --port 8398 --batch 32,64,128 --workers 1,2,4 --reps 2 --json
  python3 tools/sp_embed_bench.py --corpus /tmp/sample.jsonl --json

注意：
  - 不会启动/停止 llama-server；测隔离配置请自己先在 8398 起临时服务；
  - 只打印结构性统计，不输出语料正文；默认跳过含完整密钥形态的行。
"""
import argparse
import glob
import json
import os
import random
import re
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssotlib import fingerprint as sp_fingerprint  # noqa: E402

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
SECRET_RX = re.compile(
    r'(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}'
    r'|AKIA[0-9A-Z]{16}|hf_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')
DOC_PREFIX = 'title: none | text: '


def one_line(s):
    return ' '.join(str(s).split())


def texts_of(d):
    if not isinstance(d, dict):
        return []
    msg = d.get('message') if isinstance(d.get('message'), dict) else d
    c = msg.get('content') if isinstance(msg, dict) else None
    out = []
    if isinstance(c, str):
        out.append(c)
    elif isinstance(c, list):
        for x in c:
            if isinstance(x, dict) and isinstance(x.get('text'), str):
                out.append(x['text'])
    for k in ('text', 'content'):
        v = d.get(k)
        if isinstance(v, str) and v not in out:
            out.append(v)
    return out


def load_corpus(path, limit):
    out = []
    try:
        for line in open(path, encoding='utf-8', errors='replace'):
            try:
                d = json.loads(line)
            except Exception:
                continue
            for t in texts_of(d):
                t = one_line(t)
                if 80 <= len(t) <= 2000 and not SECRET_RX.search(t):
                    out.append(t)
                    if len(out) >= limit:
                        return out
    except OSError as e:
        raise SystemExit(f'读不到语料: {e}')
    return out


def sample_from_s1(limit, seed=0):
    files = sorted(glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions', '*', 'transcript.jsonl')))
    if not files:
        raise SystemExit('没有 S1 语料；先用 --corpus 指定 JSONL，或先跑 sp_convert')
    rnd = random.Random(seed)
    if len(files) > 60:
        files = rnd.sample(files, 60)
    out = []
    per = max(4, limit // max(1, len(files)) + 1)
    for p in files:
        got = 0
        try:
            for line in open(p, encoding='utf-8', errors='replace'):
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                for t in texts_of(d):
                    t = one_line(t)
                    if 80 <= len(t) <= 2000 and not SECRET_RX.search(t):
                        out.append(t)
                        got += 1
                        if got >= per:
                            break
                if got >= per:
                    break
        except OSError:
            continue
        if len(out) >= limit:
            break
    if not out:
        raise SystemExit('抽样为空；检查 evidence 或换 --corpus')
    rnd.shuffle(out)
    return out[:limit]


def embed(port, texts, timeout=300):
    req = urllib.request.Request(
        f'http://127.0.0.1:{port}/v1/embeddings',
        data=json.dumps({'input': texts}).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    data = d.get('data') or []
    if len(data) != len(texts):
        raise RuntimeError(f'返回条数 {len(data)} != 请求 {len(texts)}')
    return len(data[0].get('embedding') or [])


def run_once(texts, batch, workers, port):
    chunks = [texts[i:i + batch] for i in range(0, len(texts), batch)]
    t0 = time.time()
    dim = 0
    if workers <= 1:
        for c in chunks:
            dim = embed(port, c) or dim
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            pending = []
            for c in chunks:
                pending.append(ex.submit(embed, port, c))
                if len(pending) >= workers * 2:
                    dim = pending.pop(0).result() or dim
            for f in pending:
                dim = f.result() or dim
    return time.time() - t0, dim


def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(
        epilog='示例:\n  sp_embed_bench.py --quick\n  sp_embed_bench.py --port 8398 --batch 32,128 --workers 1,2 --json',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=8399)
    ap.add_argument('--corpus', help='JSONL 语料（默认从 S1 transcript 抽样）')
    ap.add_argument('--batch', default=None, help='逗号分隔，默认 32,64,128,256')
    ap.add_argument('--workers', default=None, help='逗号分隔，默认 1,2,4,8')
    ap.add_argument('--reps', type=int, default=2)
    ap.add_argument('--max-chunks', type=int, default=256)
    ap.add_argument('--quick', action='store_true', help='128 块 / batch 32,128 / workers 1,2 / 1 次')
    ap.add_argument('--early-stop', type=float, default=0.05,
                    help='workers 递增时，低于上一档该比例即停（默认 5%%）')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--json-out')
    a = ap.parse_args()

    if a.quick:
        batch_s = a.batch or '32,128'
        worker_s = a.workers or '1,2'
        a.reps = 1
        a.max_chunks = min(a.max_chunks, 128)
    else:
        batch_s = a.batch or '32,64,128,256'
        worker_s = a.workers or '1,2,4,8'
    batches = [int(x) for x in batch_s.split(',') if x.strip()]
    workers = [int(x) for x in worker_s.split(',') if x.strip()]

    if not health(a.port):
        print(f'❌ 端口 {a.port} 没有健康的 llama-server（先起服务，或换 --port）', file=sys.stderr)
        return 2

    texts = load_corpus(a.corpus, a.max_chunks) if a.corpus else sample_from_s1(a.max_chunks)
    if not texts:
        print('❌ 语料为空', file=sys.stderr)
        return 2

    rows = []
    for b in batches:
        prev = None
        for w in workers:
            times, dim, err = [], 0, ''
            for _ in range(max(1, a.reps)):
                try:
                    sec, dim = run_once(texts, b, w, a.port)
                    times.append(sec)
                except Exception as e:
                    err = f'{type(e).__name__}: {e}'
                    break
            if err:
                rows.append({'batch': b, 'workers': w, 'n': len(texts), 'error': err})
                continue
            med = statistics.median(times)
            tps = len(texts) / med if med > 0 else 0
            rows.append({'batch': b, 'workers': w, 'n': len(texts), 'seconds': round(med, 3),
                         'throughput': round(tps, 1), 'dim': dim})
            if prev is not None and a.early_stop > 0 and tps < prev * (1 - a.early_stop):
                break
            prev = tps

    ok = [r for r in rows if 'throughput' in r]
    best = max(ok, key=lambda r: (r['throughput'], -r['workers'])) if ok else None
    out = {'port': a.port, 'chunks': len(texts), 'reps': max(1, a.reps),
           'corpus': a.corpus or 'S1-sample', 'rows': rows, 'best': best,
           'env': sp_fingerprint.env(),
           'at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    if a.json_out:
        with open(a.json_out, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"port={a.port} chunks={len(texts)} reps={max(1, a.reps)}")
        for r in rows:
            if 'error' in r:
                print(f"  batch={r['batch']:<4} workers={r['workers']:<2} ERROR {r['error']}")
            else:
                print(f"  batch={r['batch']:<4} workers={r['workers']:<2} "
                      f"{r['seconds']:>6.2f}s  {r['throughput']:>7.1f} 条/秒  dim={r['dim']}")
        if best:
            print(f"最佳: batch={best['batch']} workers={best['workers']} ({best['throughput']} 条/秒)")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
