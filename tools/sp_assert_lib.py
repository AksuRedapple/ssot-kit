#!/usr/bin/env python3
"""兼容薄壳：断言解析已迁到 ssotlib.asserts（保留旧导入名，勿再新增逻辑）。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ssotlib.asserts import (CITE_RX, HEAD_RX, NUM_RX, STATUS_MAP, STATUS_RX,  # noqa: F401
                             SUP_RX, TAG_RX, base_status, ids, lint, numbers, parse,
                             parse_text, reserved_ids)
