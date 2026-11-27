#!/usr/bin/env python3
"""回归：coldstart-check 的 bash 3.2 变量坑与最小实例冒烟。"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
KIT = Path(os.environ.get("SSOT_KIT", str(Path.home() / "qoder_place" / "ssot-kit")))
SCRIPT = KIT / "scripts" / "coldstart-check.sh"
if not SCRIPT.exists():
    SCRIPT = ROOT / "scripts" / "coldstart-check.sh"


class ColdstartCheckTest(unittest.TestCase):
    def fixture(self, td):
        root = Path(td) / "ssot"
        (root / "profile").mkdir(parents=True)
        (root / "START.md").write_text("# START\n", encoding="utf-8")
        (root / "profile" / "harness-boot.md").write_text("# boot\n", encoding="utf-8")
        (root / "lines").mkdir()
        (root / "lines" / "a.md").write_text(
            "# 线：A\n> 状态: 活跃 — 最近: 2026-11-27\n", encoding="utf-8"
        )
        version = root / "S2-index" / "semantic" / "versions" / "fixture"
        version.mkdir(parents=True)
        (version / "BUILD.json").write_text(
            '{"chunks": 1, "built_at": "2026-11-27", "commit": "fixture"}\n',
            encoding="utf-8",
        )
        (root / "S2-index" / "semantic" / "active.json").write_text(
            '{"version": "fixture"}\n', encoding="utf-8"
        )
        home = Path(td) / "home"
        mem = home / ".qoder" / "memory" / "MEMORY.md"
        mem.parent.mkdir(parents=True)
        mem.write_text("# MEMORY\n", encoding="utf-8")
        return root, home

    def fake_python(self, td):
        wrapper = Path(td) / "fake-python"
        wrapper.write_text(
            "#!/bin/bash\n"
            "if [ \"${1:-}\" = \"-c\" ] && [[ \"${2:-}\" == *numpy* ]]; then\n"
            "  echo 'fixture-python numpy=fixture'\n"
            "  exit 0\n"
            "fi\n"
            f"exec {sys.executable!r} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        return wrapper

    def run_script(self, root, home, py):
        env = os.environ.copy()
        env.update({"SSOT_ROOT": str(root), "SSOT_PY": str(py), "HOME": str(home)})
        proc = subprocess.run(
            ["/bin/bash", str(SCRIPT)], env=env, capture_output=True, timeout=30
        )
        proc.stdout = proc.stdout.decode("utf-8", errors="replace")
        proc.stderr = proc.stderr.decode("utf-8", errors="replace")
        return proc

    def test_bash_syntax_and_no_cjk_variable_boundary(self):
        self.assertTrue(SCRIPT.exists(), f"missing {SCRIPT}")
        syntax = subprocess.run(
            ["/bin/bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        bad = re.findall(
            r"\$[A-Za-z_][A-Za-z0-9_]*(?=[^\x00-\x7f])", SCRIPT.read_text(encoding="utf-8")
        )
        self.assertEqual(bad, [], f"bare variable before non-ASCII: {bad}")

    def test_minimal_fixture_passes_without_unbound_variable(self):
        with tempfile.TemporaryDirectory() as td:
            root, home = self.fixture(td)
            py = self.fake_python(td)
            proc = self.run_script(root, home, py)
            out = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, out)
            self.assertIn("S2 active 索引存在", out)
            self.assertNotIn("unbound variable", out)

    def test_missing_interpreter_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            root, home = self.fixture(td)
            proc = self.run_script(root, home, Path(td) / "does-not-exist")
            out = proc.stdout + proc.stderr
            self.assertNotEqual(proc.returncode, 0, out)
            self.assertIn("解释器不存在", out)
            self.assertNotIn("unbound variable", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
