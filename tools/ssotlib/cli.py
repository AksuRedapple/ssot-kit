"""统一 CLI 骨架：argparse 基座、退出码三态、dry-run 开关（纯标准库）。

退出码契约（0.19.0 起逐步统一）：
  0  成功
  1  产品失败（有活没干成：校验不过、数据不合法、strict 未过）
  2  仪器失败（环境/依赖：索引缺失、备份失败、状态不变量被破坏）

`run()` 是给 `if __name__ == '__main__'` 用的统一入口：异常不打整段 traceback，
但要打在 stderr 上（禁止静默），`SSOT_DEBUG=1` 时保留原始 traceback 便于排障。
"""
import argparse
import os
import sys

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_INSTRUMENT = 2


class InstrumentError(RuntimeError):
    """仪器/环境失败 → 退出码 2（区别于「产品上没过」的 1）。"""


def exit_code(exc):
    """异常 → 退出码：仪器失败 2，其余 1。"""
    return EXIT_INSTRUMENT if isinstance(exc, InstrumentError) else EXIT_FAIL


def base_parser(description=None, epilog=None, prog=None, root=True):
    """统一 argparse 基座；`root=True` 时带 `--root`（默认 ~/ssot）。"""
    ap = argparse.ArgumentParser(description=description, epilog=epilog, prog=prog,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    if root:
        ap.add_argument('--root', default=os.path.expanduser('~/ssot'))
    return ap


def add_dry_run(ap, help_text='只打印计划，不写盘'):
    """加 `--dry-run` 开关（写操作默认行为由各工具决定，这里只提供统一旗标）。"""
    ap.add_argument('--dry-run', action='store_true', help=help_text)
    return ap


def run(fn, argv=None):
    """执行 fn(argv) 或 fn()，把异常映射成退出码；返回整数退出码。"""
    try:
        rc = fn(argv) if argv is not None else fn()
        return EXIT_OK if rc is None else int(rc)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print('⚠ 中断', file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001 —— 统一出口，必须显性打印
        if os.environ.get('SSOT_DEBUG') == '1':
            raise
        print(f'❌ {type(e).__name__}: {e}', file=sys.stderr)
        return exit_code(e)
