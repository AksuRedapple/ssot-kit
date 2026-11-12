#!/usr/bin/env python3
"""sp_migrate · 实例数据契约迁移(只做加法;失败不允许半迁移)

用法:
  python3 tools/sp_migrate.py --status
  python3 tools/sp_migrate.py --to 2 --dry-run
  python3 tools/sp_migrate.py --to 2 --apply
  python3 tools/sp_migrate.py --to 2 --resume

规则:
- 每步有 check()(已达标则跳过)、apply()(失败即停,已完成步骤保留)
- apply 前自动 tar 备份 profile/ + S1 meta + 账本
- 迁移期间写锁 profile/.migrating;其他工具应拒绝写入
- 索引类派生物(BUILD.json 的 schema 字段可以补,但向量库不迁移)只重建
"""
import argparse, glob, json, os, shutil, sys, tarfile, time

try:
    from sp_contract import TOOL_CONTRACT
except Exception:
    TOOL_CONTRACT = 2

SSOT = os.path.expanduser(os.environ.get('SSOT_ROOT', '~/ssot'))
STATE = os.path.join(SSOT, 'profile', '.migration.json')
LOCK = os.path.join(SSOT, 'profile', '.migrating')
CONTRACT = os.path.join(SSOT, 'profile', 'contract.json')
BACKUPS = os.path.join(SSOT, 'backups')


def contract_num():
    try:
        return int(json.load(open(CONTRACT, encoding='utf-8')).get('contract', 0))
    except Exception:
        return 0


def load_state():
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except Exception:
        return {'applied': [], 'failed': None}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    json.dump(st, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def backup():
    os.makedirs(BACKUPS, exist_ok=True)
    p = os.path.join(BACKUPS, 'pre-migrate-%s.tar.gz' % time.strftime('%Y%m%d-%H%M%S'))
    files = [CONTRACT]
    files += glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions', '*', 'meta.json'))
    files += [os.path.join(SSOT, 'inbox', 'candidates', 'candidates.jsonl')]
    files += [os.path.join(SSOT, 'S2-index', 'semantic', 'BUILD.json')]
    with tarfile.open(p, 'w:gz') as tf:
        for f in files:
            if os.path.exists(f):
                tf.add(f, arcname=os.path.relpath(f, SSOT))
    return p


# ---------------- 步骤 ----------------
def _s1_metas():
    return glob.glob(os.path.join(SSOT, 'evidence', '*', 'S1-sessions', '*', 'meta.json'))


def _ledger():
    return os.path.join(SSOT, 'inbox', 'candidates', 'candidates.jsonl')


def _build():
    return os.path.join(SSOT, 'S2-index', 'semantic', 'BUILD.json')


def m0002_check():
    ok = True
    for f in _s1_metas():
        try:
            if json.load(open(f, encoding='utf-8')).get('schema') != 2:
                ok = False; break
        except Exception:
            ok = False; break
    led = _ledger()
    if ok and os.path.exists(led):
        for ln in open(led, encoding='utf-8', errors='replace'):
            if not ln.strip():
                continue
            try:
                if json.loads(ln).get('schema') != 2:
                    ok = False; break
            except Exception:
                ok = False; break
    b = _build()
    if ok and os.path.exists(b):
        try:
            if json.load(open(b, encoding='utf-8')).get('schema') != 2:
                ok = False
        except Exception:
            ok = False
    return ok


def m0002_apply(dry=False):
    """事务式:先全部算好→暂存→统一落盘;任一步失败则回滚已落盘文件(不留半迁移)"""
    plan = []   # (path, new_text)
    n_meta = n_led = n_build = 0
    for f in _s1_metas():
        d = json.load(open(f, encoding='utf-8'))
        if d.get('schema') == 2:
            continue
        d['schema'] = 2
        plan.append((f, json.dumps(d, ensure_ascii=False, indent=1)))
        n_meta += 1

    led = _ledger()
    if os.path.exists(led):
        rows = []
        for ln in open(led, encoding='utf-8', errors='replace'):
            if not ln.strip():
                continue
            d = json.loads(ln)
            if d.get('schema') != 2:
                d['schema'] = 2
                n_led += 1
            rows.append(json.dumps(d, ensure_ascii=False))
        if n_led:
            plan.append((led, '\n'.join(rows) + '\n'))

    b = _build()
    if os.path.exists(b):
        d = json.load(open(b, encoding='utf-8'))
        if d.get('schema') != 2:
            d['schema'] = 2
            plan.append((b, json.dumps(d, ensure_ascii=False, indent=1)))
            n_build = 1

    if dry or not plan:
        return f'meta {n_meta} · ledger {n_led} · build {n_build}'

    # 暂存到 tmp,再统一 os.replace;失败则用 .orig 回滚
    staged, origs = [], []
    try:
        for path, txt in plan:
            tmp = path + '.migtmp'
            open(tmp, 'w', encoding='utf-8').write(txt)
            staged.append((tmp, path))

        for idx, (tmp, path) in enumerate(staged, 1):
            if os.environ.get('ZB_MIGRATE_FAIL') == '1' and idx > 1:
                raise RuntimeError('注入失败(测试):第 2 个文件落盘前')
            bak = path + '.orig'
            shutil.copy2(path, bak); origs.append((path, bak))
            os.replace(tmp, path)
    except Exception:
        for path, bak in origs[::-1]:
            try:
                os.replace(bak, path)
            except OSError:
                pass
        for tmp, _p in staged:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        for _p, bak in origs:
            try:
                os.unlink(bak)
            except OSError:
                pass
        raise
    for _p, bak in origs:
        try:
            os.unlink(bak)
        except OSError:
            pass
    return f'meta {n_meta} · ledger {n_led} · build {n_build}'


STEPS = [
    {'id': '0002', 'frm': 1, 'to': 2, 'desc': '给 S1 meta / 账本 / BUILD.json 补 schema:2',
     'check': m0002_check, 'apply': m0002_apply},
]


def _to_target(s):
    """--to 接受整数或 current(=本版工具支持的契约号)。"""
    if s == 'current':
        return TOOL_CONTRACT
    try:
        return int(s)
    except ValueError:
        raise argparse.ArgumentTypeError('--to 需要整数或 current')


def main():
    ap = argparse.ArgumentParser(epilog='【契约】意图：把实例数据契约推进到目标版本；只做加法，失败不留半迁移\n退出码：0=成功/已最新；1=失败（已完成步骤保留）；2=有迁移锁\n失败后：看 --status；恢复用 backups/pre-migrate-*.tar.gz\n\n示例:\n  sp_migrate.py --status\n  sp_migrate.py --to 2 --dry-run\n  sp_migrate.py --to 2 --apply\n  sp_migrate.py --to current --apply   # 升到本版工具支持的契约号',
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--to', type=_to_target)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--resume', action='store_true')
    a = ap.parse_args()

    st = load_state()
    cur = contract_num()

    if a.status or not (a.to or a.resume):
        print(f'实例契约版本 {cur} · 已执行步骤 {st.get("applied") or "无"}')
        for s in STEPS:
            done = s['id'] in st['applied']
            print(f'  {s["id"]} v{s["frm"]}→v{s["to"]} {s["desc"]} ' + ('✅' if done else ('待执行' if s['frm'] >= cur else '?')))
        return 0

    target = a.to or cur
    todo = [s for s in STEPS if s['to'] <= target and s['id'] not in st['applied'] and not s['check']()]
    if not todo:
        print('已是最新,无需迁移'); return 0

    if a.dry_run:
        print(f'[dry-run] 将执行 {len(todo)} 步(不写盘):')
        for s in todo:
            print(f'  {s["id"]} {s["desc"]}')
            print('    →', s['apply'](dry=True))
        return 0

    if os.path.exists(LOCK):
        print('❌ 已有迁移在进行(profile/.migrating 存在),先确认或删除该锁'); return 2
    open(LOCK, 'w').write(str(os.getpid()))
    try:
        bk = backup(); print(f'备份 → {os.path.relpath(bk, SSOT)}')
        for s in todo:
            print(f'▶ {s["id"]} {s["desc"]}')
            msg = s['apply'](dry=False)
            st['applied'] = st.get('applied', []) + [s['id']]
            st['failed'] = None
            save_state(st)
            print('  ✅', msg)
        # 契约号推进
        if target > cur:
            d = json.load(open(CONTRACT, encoding='utf-8'))
            d['contract'] = target
            json.dump(d, open(CONTRACT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('✅ 迁移完成')
        return 0
    except Exception as e:  # noqa: BLE001
        st['failed'] = str(e)[:200]
        save_state(st)
        print(f'❌ 迁移失败(已完成步骤保留): {e}')
        return 1
    finally:
        try:
            os.unlink(LOCK)
        except OSError:
            pass


if __name__ == '__main__':
    sys.exit(main() or 0)
