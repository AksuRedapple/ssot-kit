#!/bin/bash
# opencode v2 适配验收(2026-11-06): session_v2/session_message 为主，legacy 只补未迁移
set -u
export KIT="$(cd "$(dirname "$0")/../.." && pwd)"; TOOLS="$KIT/tools"; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
chk(){ [ "$1" = "$2" ] && echo "  ok   $3" || { echo "  FAIL $3(期望 $2,得 $1)"; fail=1; }; }

echo "[1] 造 v2 + legacy 混合夹具"
python3 - "$T/db.sqlite" <<'PY'
import sqlite3, sys, json, time
con=sqlite3.connect(sys.argv[1])
con.executescript('''
CREATE TABLE session(id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, slug TEXT, directory TEXT,
  title TEXT, version TEXT, share_url TEXT, summary_additions INT, summary_deletions INT, summary_files INT,
  summary_diffs TEXT, revert TEXT, permission TEXT, time_created INT, time_updated INT, time_compacting INT,
  time_archived INT, workspace_id TEXT, path TEXT, agent TEXT, model TEXT, cost REAL,
  tokens_input INT, tokens_output INT, tokens_reasoning INT, tokens_cache_read INT, tokens_cache_write INT, metadata TEXT);
CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, time_created INT, time_updated INT, data TEXT);
CREATE TABLE part(id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, time_created INT, time_updated INT, data TEXT);
CREATE TABLE session_v2(id TEXT PRIMARY KEY, project_id TEXT, workspace_id TEXT, parent_id TEXT,
  fork_session_id TEXT, fork_boundary TEXT, slug TEXT, directory TEXT, path TEXT, title TEXT,
  version TEXT, share_url TEXT, summary_additions INT, summary_deletions INT, summary_files INT,
  summary_diffs TEXT, metadata TEXT, cost REAL, tokens_input INT, tokens_output INT,
  tokens_reasoning INT, tokens_cache_read INT, tokens_cache_write INT, revert TEXT, permission TEXT,
  agent TEXT, model TEXT, time_created INT, time_updated INT, time_compacting INT,
  time_archived INT, time_suspended INT, resume_attempts INT, time_idle INT, time_viewed INT,
  idle_outcome TEXT, time_busy INT);
CREATE TABLE session_message(id TEXT PRIMARY KEY, session_id TEXT, type TEXT, seq INT,
  time_created INT, time_updated INT, data TEXT);
''')
now=int(time.time()*1000)
def legacy(sid,title,parent=None):
    con.execute("insert into session values(?,?,?,?,?,?,?,?,0,0,0,NULL,NULL,NULL,?,?,0,NULL,NULL,NULL,'build','{}',0,0,0,0,0,0,NULL)",
                (sid,None,parent,'s','/proj',title,'1',None,now-5000,now))
def v2(sid,title,parent=None):
    con.execute("insert into session_v2 values(?,?,NULL,?,NULL,NULL,'s','/proj',NULL,?,'1',NULL,0,0,0,NULL,NULL,0,0,0,0,0,0,NULL,NULL,'build','{}',?,?,0,NULL,NULL,0,NULL,NULL,NULL,NULL)",
                (sid,None,parent,title,now-5000,now))
# legacy-only
legacy('ses_legacy1','legacy 会话')
con.execute("insert into message values('lm1','ses_legacy1',?,?,'{\"role\":\"user\"}')",(now-5000,now-5000))
con.execute("insert into part values('lp1','lm1','ses_legacy1',?,?,'{\"type\":\"text\",\"text\":\"legacy 正文\"}')",(now-5000,now-5000))
# same id in both: v2 must win
legacy('ses_both1','both 会话')
v2('ses_both1','both 会话')
con.execute("insert into message values('bm1','ses_both1',?,?,'{\"role\":\"user\"}')",(now-5000,now-5000))
con.execute("insert into part values('bp1','bm1','ses_both1',?,?,'{\"type\":\"text\",\"text\":\"legacy 旧文本\"}')",(now-5000,now-5000))
con.execute("insert into session_message values('vm1','ses_both1','user',1,?,?,'{\"text\":\"v2 新文本\"}')",(now-5000,now-5000))
# v2 root + child
v2('ses_v2root1','v2 根会话')
con.execute("insert into session_message values('rm1','ses_v2root1','user',1,?,?,'{\"text\":\"v2 用户问题\"}')",(now-5000,now-5000))
con.execute("insert into session_message values('rm2','ses_v2root1','assistant',2,?,?,'{\"content\":[{\"type\":\"text\",\"text\":\"v2 回答\"},{\"type\":\"tool\",\"name\":\"shell\",\"state\":{\"input\":{\"command\":\"echo hi\"}}}]}')",(now-4900,now-4900))
v2('ses_v2child1','v2 子会话','ses_v2root1')
con.execute("insert into session_message values('cm1','ses_v2child1','assistant',1,?,?,'{\"content\":[{\"type\":\"text\",\"text\":\"子会话回答\"}]}')",(now-4800,now-4800))
con.commit(); con.close()
PY

echo "[2] 转换 v2 全量"
out=$(python3 "$TOOLS/sp_opencode.py" --db "$T/db.sqlite" --root "$T/root" --all --force 2>&1)
chk "$(echo "$out" | grep -c '转换 4 个会话')" "1" "4 个会话"

echo "[3] v2 优先：both 会话只出现 v2 文本"
both=$(ls -d "$T/root/evidence/opencode/S1-sessions"/*both* | head -1)
chk "$(grep -c 'v2 新文本' "$both/transcript.jsonl")" "1" "v2 文本在"
chk "$(grep -c 'legacy 旧文本' "$both/transcript.jsonl")" "0" "legacy 旧文本被覆盖"
chk "$(python3 -c "import json;print(json.load(open('$both/meta.json'))['store'])")" "session_v2" "store=v2"

echo "[4] v2 正文/工具/子会话"
root=$(ls -d "$T/root/evidence/opencode/S1-sessions"/*v2-* | head -1)
chk "$(grep -c 'v2 用户问题' "$root/transcript.jsonl")" "1" "用户文本"
chk "$(grep -c 'v2 回答' "$root/transcript.jsonl")" "1" "助手文本"
chk "$(grep -c '\[tool\] shell: echo hi' "$root/transcript.jsonl")" "1" "工具占位"
chk "$(ls "$T/root/evidence/opencode/S1-subagents" | wc -l | tr -d ' ')" "1" "子会话进 subagents"

echo "[5] legacy-only 仍补位"
leg=$(ls -d "$T/root/evidence/opencode/S1-sessions"/*legacy* | head -1)
chk "$(grep -c 'legacy 正文' "$leg/transcript.jsonl")" "1" "legacy 正文在"
chk "$(python3 -c "import json;print(json.load(open('$leg/meta.json'))['store'])")" "session" "store=legacy"

echo "[6] coverage 分母 = v2 根 + legacy-only 根"
n=$(python3 - "$T/db.sqlite" <<'PY'
import os, sys, sqlite3
sys.path.insert(0, os.path.join(os.environ['KIT'], 'tools'))
import sp_coverage
con=sqlite3.connect(sys.argv[1]); print(sp_coverage.opencode_root_count(con)); con.close()
PY
)
chk "$n" "3" "3 个根会话(v2root/both/legacy)"

[ $fail -eq 0 ] && echo "全部通过" || echo "有失败"
exit $fail
