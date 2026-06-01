#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI 主窗口
────────────────────────────────────────────────────────
负责窗口框架、整体样式、Notebook 三个 Tab 的装配，以及跨 Tab 共享的
日志/状态工具方法。各 Tab 的具体控件与事件由 ui/tab_*.py 构建。

共享状态全部挂在 App 实例上（app.api / app.queue / app.colors ...），
各 Tab 的 build_* 函数通过 app 参数访问，不再使用全局变量。
"""

import threading
import tkinter as tk
from tkinter import ttk
from datetime import datetime

from core.api import CopernicusAPI
from core.config import log_line
from ui.tab_auth import build_auth_tab, load_config_into_ui
from ui.tab_search import build_search_tab
from ui.tab_download import build_download_tab


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sentinel-1 批量下载工具  |  海河25·7洪涝监测")
        self.geometry("1050x760")
        self.minsize(900, 650)
        self.configure(bg="#0d1117")
        self.resizable(True, True)

        # ── 共享状态（各 Tab 通过 app.xxx 访问）──────────────────────
        self.api            = CopernicusAPI()
        self.search_results = []        # 搜索结果
        self.queue          = []        # 下载队列  [{id, name, size, status}]
        self.downloading    = False
        self.colors         = {}        # 由 _setup_style 填充
        self._selected_iids = set()     # 搜索结果中已勾选行
        self._stop_event    = threading.Event()

        self._setup_style()
        self._build_ui()
        load_config_into_ui(self)       # 填充各 Entry 控件

    # ── 样式 ──────────────────────────────────
    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        BG   = "#0d1117"
        BG2  = "#161b22"
        BG3  = "#1f2937"
        FG   = "#e6edf3"
        ACC  = "#00d4ff"
        GRN  = "#3fb950"
        BDR  = "#30363d"
        SEL  = "#1f3547"
        DIS  = "#484f58"

        style.configure(".",           background=BG,  foreground=FG,  font=("Consolas", 10))
        style.configure("TFrame",      background=BG)
        style.configure("TLabel",      background=BG,  foreground=FG,  font=("Consolas", 10))
        style.configure("TLabelframe", background=BG,  foreground=ACC, font=("Consolas", 10, "bold"))
        style.configure("TLabelframe.Label", background=BG, foreground=ACC, font=("Consolas", 10, "bold"))
        style.configure("TEntry",      fieldbackground=BG2, foreground=FG,  insertcolor=FG,
                         font=("Consolas", 10), borderwidth=1, relief="flat")
        style.configure("TCombobox",   fieldbackground=BG2, foreground=FG,
                         selectbackground=SEL, font=("Consolas", 10))
        style.map("TCombobox",         fieldbackground=[("readonly", BG2)])
        style.configure("TButton",     background=BG3, foreground=FG, borderwidth=0,
                         padding=(10, 6), font=("Consolas", 10, "bold"), relief="flat")
        style.map("TButton",
                  background=[("active", "#2d3748"), ("disabled", BG2)],
                  foreground=[("disabled", DIS)])
        style.configure("Accent.TButton", background=ACC,  foreground="#000000",
                         font=("Consolas", 10, "bold"))
        style.map("Accent.TButton",    background=[("active", "#00b8d9")])
        style.configure("Green.TButton",  background=GRN,  foreground="#000000",
                         font=("Consolas", 10, "bold"))
        style.map("Green.TButton",     background=[("active", "#2ea043")])
        style.configure("TCheckbutton", background=BG, foreground=FG,
                         font=("Consolas", 10))
        style.map("TCheckbutton",      background=[("active", BG)])
        style.configure("TNotebook",   background=BG,  borderwidth=0)
        style.configure("TNotebook.Tab", background=BG2, foreground=DIS,
                         padding=(14, 7), font=("Consolas", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", BG), ("active", BG3)],
                  foreground=[("selected", ACC), ("active", FG)])
        style.configure("Treeview",    background=BG2, foreground=FG,
                         fieldbackground=BG2, rowheight=26,
                         font=("Consolas", 9), borderwidth=0)
        style.configure("Treeview.Heading", background=BG3, foreground=ACC,
                         font=("Consolas", 9, "bold"), relief="flat")
        style.map("Treeview",          background=[("selected", SEL)])
        style.configure("TScrollbar",  background=BG3, troughcolor=BG2,
                         arrowcolor=DIS, borderwidth=0)
        style.configure("TProgressbar", troughcolor=BG3, background=ACC, borderwidth=0)
        style.configure("Green.Horizontal.TProgressbar",
                         troughcolor=BG3, background=GRN, borderwidth=0)

        self.colors = dict(BG=BG, BG2=BG2, BG3=BG3, FG=FG, ACC=ACC,
                           GRN=GRN, BDR=BDR, SEL=SEL, DIS=DIS,
                           RED="#f85149", ORG="#d29922")

    # ── 整体框架 ──────────────────────────────
    def _build_ui(self):
        C = self.colors
        # 顶栏
        top = tk.Frame(self, bg=C["BG3"], height=52)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="🛰  Sentinel-1 批量下载工具",
                 bg=C["BG3"], fg=C["ACC"],
                 font=("Consolas", 14, "bold")).pack(side="left", padx=18, pady=12)
        self.lbl_token = tk.Label(top, text="● 未登录", bg=C["BG3"], fg=C["DIS"],
                                  font=("Consolas", 10))
        self.lbl_token.pack(side="right", padx=18)

        # Notebook
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=0, pady=0)

        self.tab_auth   = ttk.Frame(nb)
        self.tab_search = ttk.Frame(nb)
        self.tab_dl     = ttk.Frame(nb)

        nb.add(self.tab_auth,   text="  🔐 账号配置  ")
        nb.add(self.tab_search, text="  🔍 搜索影像  ")
        nb.add(self.tab_dl,     text="  ⬇  下载管理  ")

        build_auth_tab(self)
        build_search_tab(self)
        build_download_tab(self)

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        sb = tk.Frame(self, bg=C["BG3"], height=28)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        tk.Label(sb, textvariable=self.status_var, bg=C["BG3"], fg=C["DIS"],
                 font=("Consolas", 9), anchor="w").pack(side="left", padx=12, pady=4)

    # ── 跨 Tab 共享工具 ───────────────────────
    def _log(self, widget, msg, tag="info"):
        def _do():
            widget.config(state="normal")
            now = datetime.now().strftime("%H:%M:%S")
            widget.insert("end", f"[{now}] {msg}\n", tag)
            widget.see("end")
            widget.config(state="disabled")
        self.after(0, _do)

    def _dlog(self, msg, tag="info"):
        log_line(msg)                       # 持久化到 data/logs/download_*.log
        self._log(self.dl_log, msg, tag)

    def set_status(self, msg):
        self.after(0, lambda: self.status_var.set(msg))
