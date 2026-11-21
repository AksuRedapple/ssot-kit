#!/usr/bin/env python3
"""undefined_names_test · 全仓「引用了但没定义」静态闸（纯标准库 symtable）。

为什么要有它（2026-11-21 事故）：sp_convert 的分层重构删掉了模块级常量块
（VAULT / SRCS / S0 / S1 / CONVERTER）与 contract_schema() / lstr()，却留下
20+ 处引用。65 个库函数测试全绿，但 `main()` 一跑就 NameError，steward 的
三条转换任务静默失败 29 小时（A561）。

pyflakes 能抓这类 F821，但 kit 的 CI 只装标准库。symtable 是标准库，且它已经
把作用域解析好了：一个 symbol 在函数里 `is_global()` 且 `is_referenced()`，
就说明它要去模块层找；模块层没有绑定、也不是 builtin，就是未定义。

判据：任何 shipped 工具或 ssotlib 模块出现「未定义名字」→ 退出码 1。
反例：`from x import *` 的文件跳过（无法静态解析），但要打印出来计数。
"""
import builtins
import pathlib
import symtable
import sys

MAGIC = {'__file__', '__name__', '__doc__', '__package__', '__spec__',
         '__loader__', '__builtins__', '__cached__', '__annotations__'}


def walk(table):
    yield table
    for child in table.get_children():
        yield from walk(child)


def module_names(table):
    names = set()
    for sym in table.get_symbols():
        if (sym.is_assigned() or sym.is_imported() or sym.is_namespace()
                or sym.is_parameter()):
            names.add(sym.get_name())
    return names


def undefined_in(path):
    """→ (undefined: set[str], star_import: bool, error: str|None)"""
    try:
        src = pathlib.Path(path).read_text(encoding='utf-8')
    except OSError as e:
        return set(), False, str(e)
    try:
        top = symtable.symtable(src, str(path), 'exec')
    except SyntaxError as e:
        return set(), False, f'SyntaxError: {e}'

    star = any(s.get_name() == '*' and s.is_imported() for s in top.get_symbols())
    if star:
        return set(), True, None

    known = module_names(top) | set(dir(builtins)) | MAGIC
    bad = set()
    for table in walk(top):
        for sym in table.get_symbols():
            if not sym.is_referenced():
                continue
            if table is top:
                if not (sym.is_assigned() or sym.is_imported() or sym.is_namespace()):
                    if sym.get_name() not in known:
                        bad.add(sym.get_name())
            elif sym.is_global() and sym.get_name() not in known:
                bad.add(sym.get_name())
    return bad, False, None


def main():
    root = pathlib.Path(__file__).resolve().parent.parent
    targets = sorted(root.glob('*.py')) + sorted((root / 'ssotlib').rglob('*.py'))
    bad_files, skipped, fails = 0, 0, 0
    for p in targets:
        if p.name.startswith('_'):
            continue
        bad, star, err = undefined_in(p)
        if err:
            print(f'❌ {p.relative_to(root)}: {err}')
            fails += 1
            continue
        if star:
            skipped += 1
            continue
        if bad:
            bad_files += 1
            print(f'❌ {p.relative_to(root)}: 未定义 {sorted(bad)}')
    print(f'扫描 {len(targets)} 个文件 · 未定义 {bad_files} · 跳过(star import) {skipped} · 语法错误 {fails}')
    return 1 if (bad_files or fails) else 0


if __name__ == '__main__':
    sys.exit(main())
