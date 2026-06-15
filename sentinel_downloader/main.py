#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sentinel S1/S2 批量搜索 & 下载工具 —— 程序入口
数据源: Copernicus Data Space (ESA) / NASA Earthdata

运行：
    python main.py
"""

from ui.app import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
