#!/usr/bin/env python3
"""sp_index_merge · 合并分片索引(与 sp_index.py --shard=i/n 配套)

场景:单进程建库受"逐组串行"限制,GPU 空转。把语料按 i/n 分片,多进程并发写各自的库,
最后合并成一个与单进程全量**等价**的库(块数/路径分布/维度一致)。

用法:
  python3 sp_index_merge.py --out /path/final.db /path/shard0.db /path/shard1.db [--more ...]
  python3 sp_index_merge.py --verify /path/final.db /path/reference.db   # 指纹对比

等价判据:总块数相等 + 逐路径块数全等 + 维度一致(见 A420)。
"""
import argparse, json, os, shutil, sqlite3, sys


def merge(out, parts):
    if os.path.exists(out):
        os.remove(out)
    shutil.copyfile(parts[0], out)          # 继承 schema 与首个分片数据
    con = sqlite3.connect(out)
    cols = {r[1] for r in con.execute('pragma table_info(chunks)').fetchall()}
    for c in ('assertion_id', 'status', 'superseded_by'):
        if c not in cols:
            con.execute(f'alter table chunks add column {c} text')
    con.commit()
    for p in parts[1:]:
        con.execute('ATTACH DATABASE ? AS s', (p,))
        scols = {r[1] for r in con.execute('pragma s.table_info(chunks)').fetchall()}
        extra = (',assertion_id,status,superseded_by'
                 if {'assertion_id', 'status', 'superseded_by'} <= scols else ',NULL,NULL,NULL')
        con.execute(f'''INSERT INTO chunks(path,line,text,role,ts,vec,assertion_id,status,superseded_by)
                       SELECT path,line,text,role,ts,vec{extra} FROM s.chunks''')
        con.execute('INSERT OR REPLACE INTO src_state(path,digest) SELECT path,digest FROM s.src_state')
        con.commit()                     # 必须先提交,否则 DETACH 报 database is locked
        con.execute('DETACH DATABASE s')
    # FTS 是 external-content + 触发器,合并后重建一遍最稳
    try:
        con.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    except sqlite3.OperationalError:
        pass
    con.commit()
    n = con.execute('select count(*) from chunks').fetchone()[0]
    con.close()
    print(f'合并完成:{out}  {n} 块(来自 {len(parts)} 个分片)')
    return n


def verify(db, ref):
    def load(p):
        c = sqlite3.connect(p)
        tot = c.execute('select count(*) from chunks').fetchone()[0]
        per = dict(c.execute('select path,count(*) from chunks group by path').fetchall())
        dims = [r[0] for r in c.execute('select distinct length(vec)/4 from chunks').fetchall()]
        c.close()
        return tot, per, dims

    a = load(db); b = load(ref)
    ok = a[0] == b[0] and a[1] == b[1] and a[2] == b[2]
    print(f'{os.path.basename(db)}: {a[0]} 块 · 路径 {len(a[1])} · 维度 {a[2]}')
    print(f'{os.path.basename(ref)}: {b[0]} 块 · 路径 {len(b[1])} · 维度 {b[2]}')
    print('指纹:', '✅ 完全等价' if ok else '❌ 不等价')
    if not ok:
        diff = [(k, a[1].get(k), b[1].get(k)) for k in set(a[1]) | set(b[1]) if a[1].get(k) != b[1].get(k)]
        for d in diff[:5]:
            print('  差异', d)
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(epilog='示例:\n  sp_index_merge.py --out /tmp/final.db /tmp/shard0.db /tmp/shard1.db\n  sp_index_merge.py --verify /tmp/final.db ~/ssot/S2-index/semantic/index.db',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out')
    ap.add_argument('--verify', nargs=2, metavar=('DB', 'REF'))
    ap.add_argument('parts', nargs='*')
    a = ap.parse_args()
    if a.verify:
        sys.exit(verify(a.verify[0], a.verify[1]))
    if not a.out or len(a.parts) < 2:
        ap.print_help(); sys.exit(1)
    merge(a.out, a.parts)


if __name__ == '__main__':
    main()
