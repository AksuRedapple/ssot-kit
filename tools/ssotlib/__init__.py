"""ssotlib · SSOT 工具的共享层（纯标准库，可被 kit 直接安装）。

依赖方向：tools/*.py → ssotlib；ssotlib 不 import 任何工具。
放在 tools/ 下是为了让 `python3 tools/xxx.py` 直接 import（运行目录即 sys.path[0]），
不需要每个入口重复注入路径——那本身就是要消掉的重复。
"""

__version__ = '0.19.0'
