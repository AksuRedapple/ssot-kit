#!/usr/bin/env python3
"""sp_candidates: conflict retrieval is incremental and does not go O(n²)."""

from __future__ import annotations

import importlib.util
import pathlib
import tempfile
from types import SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sp_candidates", ROOT / "sp_candidates.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


def main() -> int:
    idx = {}
    for i in range(4000):
        cid = f"cand_old_{i}"
        claim = f"topic{i:04d} fact{i:04d}"
        idx[cid] = {
            "id": cid,
            "claim": claim,
            "state": "candidate",
            "polarity": 1,
        }
    positive_id = "cand_positive"
    negative_id = "cand_negative"
    idx[positive_id] = {
        "id": positive_id,
        "claim": "alpha beta gamma delta 必须",
        "state": "candidate",
        "polarity": 1,
        "conflicts_with": [],
    }
    idx[negative_id] = {
        "id": negative_id,
        "claim": "alpha beta gamma delta 不许",
        "state": "candidate",
        "polarity": -1,
        "conflicts_with": [],
    }

    checked, touched = mod.mark_conflicts(idx, {negative_id}, 0.6)
    assert touched == 1
    assert idx[negative_id]["state"] == "conflict"
    assert idx[positive_id]["state"] == "conflict"
    assert idx[negative_id]["conflicts_with"] == [positive_id]
    assert idx[positive_id]["conflicts_with"] == [negative_id]
    assert checked < 20, f"should retrieve only near neighbours, checked={checked}"

    # Idempotent: a second scan must not append duplicate links.
    mod.mark_conflicts(idx, {negative_id}, 0.6)
    assert idx[negative_id]["conflicts_with"] == [positive_id]
    assert idx[positive_id]["conflicts_with"] == [negative_id]

    # Session filtering is explicit rather than a full-library prerequisite.
    with tempfile.TemporaryDirectory() as tmp:
        evidence = pathlib.Path(tmp) / "evidence" / "cc" / "S1-sessions"
        for name in ("2026-11-12-ses_wanted-x", "2026-11-12-ses_other-y"):
            d = evidence / name
            d.mkdir(parents=True)
            (d / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
        old_ssot = mod.SSOT
        try:
            mod.SSOT = tmp
            hits = mod.sessions("cc", needles=["ses_wanted"])
        finally:
            mod.SSOT = old_ssot
        assert len(hits) == 1 and "ses_wanted" in hits[0]

    # A normal run must stamp the v2 schema on newly-created candidates.
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        session = root / "evidence" / "cc" / "S1-sessions" / "2026-11-12-ses_schema"
        session.mkdir(parents=True)
        (session / "transcript.jsonl").write_text(
            '{"role":"assistant","kind":"text","content":"实测根因：必须禁止误判，'
            '缓存命中后仍要验证结果，结论必须带证据。"}\n',
            encoding="utf-8",
        )
        old = (mod.SSOT, mod.OUTDIR, mod.OUT, mod.REVIEW)
        try:
            mod.SSOT = str(root)
            mod.OUTDIR = str(root / "inbox" / "candidates")
            mod.OUT = str(root / "inbox" / "candidates" / "candidates.jsonl")
            mod.REVIEW = str(root / "inbox" / "candidates" / "review.md")
            mod.run(SimpleNamespace(
                src="cc", since=None, session=None, min_score=3,
                conflict_overlap=0.6, conflict_mode="incremental",
            ))
            rows = [
                __import__("json").loads(line)
                for line in pathlib.Path(mod.OUT).read_text(encoding="utf-8").splitlines()
            ]
        finally:
            mod.SSOT, mod.OUTDIR, mod.OUT, mod.REVIEW = old
        assert rows and all(row.get("schema") == 2 for row in rows)

    print(f"PASS incremental conflict checked={checked}; 4000 unrelated candidates skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
