#!/usr/bin/env python3
"""兼容薄壳：环境指纹已迁到 ssotlib.fingerprint（保留旧导入名，勿再新增逻辑）。"""
from ssotlib.fingerprint import (MODEL, backend, env, hardware_fp,  # noqa: F401
                                 llama_version, model_fp)
