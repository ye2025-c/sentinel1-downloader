#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sentinel-1 SAR 批量搜索 & 下载工具 —— 程序入口
数据源: Copernicus Data Space (ESA)

运行：
    python main.py
"""

from ui.app import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
