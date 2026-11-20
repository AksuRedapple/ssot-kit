#!/usr/bin/env python3
"""回归：autotune 只读探测、profile 原子写、backup/restore、dry 不写、坏端口 rc=2。"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_embed_autotune.py"
sys.path.insert(0, str(ROOT / "tools"))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/props":
            out = json.dumps({"total_slots": 2, "n_ctx": 4096, "model_alias": "fake"}).encode()
        elif self.path == "/health":
            out = b'{"status":"ok"}'
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        data = [{"embedding": [0.01] * 8} for _ in body.get("input", [])]
        out = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def run(env, *args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)


def check_policy(fails):
    """并发策略是纯函数，用确定性的 throughput 行数据测（不依赖计时噪声）。"""
    import sp_embed_autotune as M

    def rows(two):
        return [{"batch": 64, "workers": 1, "throughput": 100.0},
                {"batch": 64, "workers": 2, "throughput": two}]

    cases = [(104.0, 1), (105.0, 2), (106.0, 2), (100.0, 1)]
    for two, want in cases:
        got = M.choose_client({"rows": rows(two)})
        if not got or got.get("workers") != want:
            fails.append(f"choose_client(2w={two}) → {got}，期望 workers={want}")
    # 只有单并发候选时照旧
    got = M.choose_client({"rows": [{"batch": 64, "workers": 1, "throughput": 100.0}]})
    if not got or got.get("workers") != 1:
        fails.append(f"单行 choose_client → {got}")


def main():
    fails = []
    check_policy(fails)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            prof = t / "profile/embed-profile.json"
            model = t / "models/m.gguf"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"fake-model")
            corpus = t / "c.jsonl"
            corpus.write_text("\n".join(json.dumps(
                {"role": "user", "content": "字" * 160}, ensure_ascii=False) for _ in range(8)) + "\n",
                encoding="utf-8")
            env = dict(os.environ, SSOT_ROOT=str(t), EMBED_PROFILE=str(prof),
                       EMBED_MODEL=str(model), LLAMA_SERVER="llama-server")

            r = run(env, "--probe", "--json", "--port", str(port))
            if r.returncode != 0:
                fails.append(f"probe rc={r.returncode}: {r.stderr}")
            else:
                d = json.loads(r.stdout)["profile"]
                if d["schema"] != 1 or d["client"]["workers"] != 1:
                    fails.append(f"probe 字段不对: {d.get('client')}")
                if d["fallback"]["server"]["parallel"] != 2:
                    fails.append(f"fallback 未快照当前: {d['fallback']}")
            if prof.exists():
                fails.append("probe 不应写 profile")

            r = run(env, "--bench", "--quick", "--apply", "--json",
                    "--port", str(port), "--corpus", str(corpus))
            if r.returncode != 0:
                fails.append(f"apply rc={r.returncode}: {r.stderr}")
            else:
                d = json.loads(r.stdout)
                if not d.get("applied") or not prof.exists():
                    fails.append("apply 未写 profile")
                p = d["profile"]
                if p.get("source") != "bench" or p.get("measured", {}).get("mode") != "bench":
                    fails.append(f"profile 来源不对: {p.get('source')}")
                # 并发是否采纳由 choose_client 的策略决定，这里只验管道写对了；
                # 5% 阈值在 test_choose_client_policy 里用确定性数据精确测。
                if p["client"]["workers"] not in (1, 2):
                    fails.append(f"workers 非法: {p['client']}")

            first = prof.read_bytes()
            r = run(env, "--probe", "--json", "--port", str(port))
            if prof.read_bytes() != first:
                fails.append("无 --apply 的运行改了 profile")

            r = run(env, "--bench", "--quick", "--apply", "--json",
                    "--port", str(port), "--corpus", str(corpus))
            if not Path(str(prof) + ".bak").exists():
                fails.append("二次 apply 未生成 .bak")

            r = run(env, "--restore")
            if r.returncode != 0 or not prof.exists():
                fails.append(f"restore 失败: {r.returncode} {r.stderr}")

            r = run(env, "--bench", "--quick", "--port", "1", "--corpus", str(corpus))
            if r.returncode != 2:
                fails.append(f"坏端口应 rc=2，实际 {r.returncode}")
    finally:
        srv.shutdown()

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   probe 不写 profile")
    print("  ok   bench+apply 写 profile（source=bench）")
    print("  ok   二次 apply 有 .bak / restore 可用")
    print("  ok   坏端口 rc=2")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
