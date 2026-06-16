#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sentinel S1/S2 批量搜索 & 下载工具 —— 程序入口
数据源: Copernicus Data Space (ESA) / NASA Earthdata

运行：
    python main.py
"""

import os
import sys
import traceback
from datetime import datetime
from tkinter import messagebox

from core.config import LOG_DIR, _ensure_data_dirs
from ui.app import App


def _write_crash_log(exc_type, exc, tb) -> str:
    """Write uncaught exceptions to data/logs so windowed exe failures are visible."""
    _ensure_data_dirs()
    path = os.path.join(LOG_DIR, f"crash_{datetime.now():%Y%m%d}.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] Unhandled exception\n")
        f.writelines(traceback.format_exception(exc_type, exc, tb))
    return path


def _handle_exception(exc_type, exc, tb):
    try:
        path = _write_crash_log(exc_type, exc, tb)
        messagebox.showerror(
            "程序异常",
            "程序遇到未处理错误，详情已写入日志：\n" + path,
        )
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc, tb)

if __name__ == "__main__":
    sys.excepthook = _handle_exception
    app = App()
    app.report_callback_exception = _handle_exception
    app.mainloop()
