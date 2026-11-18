#!/usr/bin/env python3
"""回归：sp_embed_bench 只读、batch/workers 矩阵可用、不打印正文、跳过密钥行。"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "sp_embed_bench.py"
DIM = 8


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        data = [{"embedding": [0.01] * DIM} for _ in body.get("input", [])]
        out = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def main():
    fails = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            corpus = t / "c.jsonl"
            lines = []
            for i in range(8):
                lines.append(json.dumps({"role": "user", "content": ("样本%02d " % i) + "字" * 120},
                                        ensure_ascii=False))
            lines.append(json.dumps({"role": "user", "content": "sk-" + "a" * 32},
                                    ensure_ascii=False))
            corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")
            r = subprocess.run([sys.executable, str(TOOL), "--port", str(port),
                                "--corpus", str(corpus), "--batch", "2,4",
                                "--workers", "1,2", "--reps", "1", "--json"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                fails.append(f"rc={r.returncode}: {r.stderr}")
            else:
                d = json.loads(r.stdout)
                if d["chunks"] != 8:
                    fails.append(f"密钥行未跳过: chunks={d['chunks']}")
                if len(d["rows"]) != 4:
                    fails.append(f"矩阵行数不对: {len(d['rows'])}")
                if not all(x.get("throughput", 0) > 0 for x in d["rows"]):
                    fails.append(f"吞吐异常: {d['rows']}")
                if any(x.get("dim") != DIM for x in d["rows"]):
                    fails.append(f"维度不对: {d['rows']}")
                if "字字字" in r.stdout:
                    fails.append("输出泄漏了语料正文")
    finally:
        srv.shutdown()

    # 没有服务 → rc=2
    r = subprocess.run([sys.executable, str(TOOL), "--port", "1", "--corpus", "/dev/null", "--quick"],
                       capture_output=True, text=True)
    if r.returncode != 2:
        fails.append(f"无服务应 rc=2，实际 {r.returncode}")

    if fails:
        for f in fails:
            print("  FAIL", f)
        print("有失败")
        return 1
    print("  ok   batch×workers 矩阵")
    print("  ok   跳过密钥行、不泄漏正文")
    print("  ok   无服务 rc=2")
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
