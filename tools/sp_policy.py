#!/usr/bin/env python3
"""兼容薄壳：索引策略已迁到 ssotlib.policy（保留旧导入名，勿再新增逻辑）。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ssotlib.policy import (CLASSES, DEFAULT_INCLUDE, DEFAULT_SKIP, POLICY_REL,  # noqa: F401
                            RETIRED_REL, class_of, harness_of, included, load_policy,
                            load_retired, sid_of, suggest_class, summary)
