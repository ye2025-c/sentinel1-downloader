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

import ttkbootstrap as ttkb

from core.api import CopernicusAPI
from core.s2_api import SentinelS2API
from core.config import log_line
from core.store import SearchCache
from ui.tab_auth import build_auth_tab, load_config_into_ui
from ui.tab_search import build_search_tab
from ui.tab_download import build_download_tab

# 主题：ttkbootstrap 自带的深色主题，换一个单词即可切换风格
#   深色可选：superhero / darkly / cyborg / solar / vapor
#   浅色可选：cosmo / flatly / litera / yeti / minty ...
THEME = "superhero"


def _darken(hexcolor, f=0.82):
    """把十六进制颜色按比例压暗，用于按钮 hover 态（保持色相）。"""
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))


class App(ttkb.Window):
    def __init__(self):
        super().__init__(
            title="Sentinel 批量下载工具  |  海河25·7洪涝监测",
            themename=THEME,
            size=(1130, 780),
        )
        self.minsize(980, 660)
        self.resizable(True, True)

        # ── 共享状态（各 Tab 通过 app.xxx 访问）──────────────────────
        self.api            = CopernicusAPI()
        self.api_s2         = SentinelS2API()
        self.search_results = []        # 搜索结果
        self.queue          = []        # 下载队列  [{id, name, size, status}]
        self.downloading    = False
        self.colors         = {}        # 由 _setup_style 填充
        self._selected_iids = set()     # 搜索结果中已勾选行
        self._stop_event    = threading.Event()

        self._setup_style()
        self._build_ui()
        load_config_into_ui(self)       # 填充各 Entry 控件
        SearchCache.clear_expired()     # 清理过期搜索缓存

    # ── 样式 ──────────────────────────────────
    def _setup_style(self):
        # ttkbootstrap 已套用整套主题（按钮 / 输入框 / 表格 / 标签页等 ttk
        # 控件自动变好看）。这里只做三件事：
        #   ① 把主题色映射到同名变量，供下方 option 数据库与 self.colors 复用；
        #   ② 界面字体换中文友好的雅黑，数据表 / 日志保留等宽；
        #   ③ 次级按钮转中性灰，并定义蓝 / 绿强调按钮与进度条配色。
        style = self.style
        c = style.colors

        UI   = "Microsoft YaHei UI"   # 界面文字（中文友好、非等宽）
        MONO = "Consolas"             # 日志 / 数据表（等宽对齐）
        self.FONT_UI   = UI
        self.FONT_MONO = MONO

        BG   = c.bg          # 主背景
        BG2  = c.inputbg     # 输入框 / 日志 / 表格行
        BG3  = c.dark        # 顶栏 / 状态栏（深一档）
        BG4  = c.secondary   # 次级按钮 / 悬停
        ALT  = c.bg          # 表格隔行色（与 inputbg 形成细微差）
        FG   = c.fg
        ACC  = c.primary     # 强调蓝
        GRN  = c.success
        RED  = c.danger
        ORG  = c.warning
        BDR  = c.border
        SEL  = c.selectbg    # 选中行
        DIS  = c.light       # 次要 / 提示文字

        # ① 字体：界面雅黑，数据表 / 日志等宽
        style.configure(".",                 font=(UI, 10))
        style.configure("TLabel",            font=(UI, 10))
        style.configure("TButton",           font=(UI, 10))
        style.configure("TCheckbutton",      font=(UI, 10))
        style.configure("TRadiobutton",      font=(UI, 10))
        style.configure("TEntry",            font=(UI, 10))
        style.configure("TCombobox",         font=(UI, 10))
        style.configure("TNotebook.Tab",     font=(UI, 10), padding=(16, 8))
        style.configure("TLabelframe.Label", font=(UI, 10, "bold"), foreground=ACC)
        style.configure("Treeview",          font=(MONO, 9), rowheight=27)
        style.configure("Treeview.Heading",  font=(UI, 9, "bold"))

        # ② 次级按钮中性灰（ttkbootstrap 默认按钮为实心蓝，留给主操作用）
        style.configure("TButton", background=BG4, bordercolor=BG4)
        style.map("TButton",
                  background=[("active", _darken(BG4)), ("disabled", BG2)],
                  foreground=[("disabled", DIS)])

        # ③ 蓝 / 绿强调按钮（沿用 tab 中的 style 名）
        style.configure("Accent.TButton", font=(UI, 10, "bold"),
                        background=ACC, bordercolor=ACC, foreground=c.selectfg)
        style.map("Accent.TButton",
                  background=[("active", _darken(ACC)), ("disabled", BG2)],
                  foreground=[("disabled", DIS)])
        style.configure("Green.TButton", font=(UI, 10, "bold"),
                        background=GRN, bordercolor=GRN, foreground=c.selectfg)
        style.map("Green.TButton",
                  background=[("active", _darken(GRN)), ("disabled", BG2)],
                  foreground=[("disabled", DIS)])

        # 进度条加粗 + 绿色变体
        style.configure("TProgressbar", thickness=14)
        style.configure("Green.Horizontal.TProgressbar", background=GRN, thickness=14)

        # tk（非 ttk）控件无法走 style：用 option 数据库给未显式着色的
        # Label / Radiobutton 设默认深色底，并把下拉框弹窗也调成深色。
        self.option_add("*Label.background", BG)
        self.option_add("*Label.foreground", FG)
        self.option_add("*Radiobutton.background", BG)
        self.option_add("*Radiobutton.foreground", FG)
        self.option_add("*Radiobutton.selectColor", BG2)
        self.option_add("*Radiobutton.activeBackground", BG)
        self.option_add("*Radiobutton.activeForeground", ACC)
        self.option_add("*TCombobox*Listbox.background", BG2)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", SEL)
        self.option_add("*TCombobox*Listbox.selectForeground", FG)
        self.option_add("*TCombobox*Listbox.font", "{Microsoft YaHei UI} 9")

        self.colors = dict(BG=BG, BG2=BG2, BG3=BG3, BG4=BG4, ALT=ALT, FG=FG, ACC=ACC,
                           GRN=GRN, BDR=BDR, SEL=SEL, DIS=DIS,
                           RED=RED, ORG=ORG)

    # ── 整体框架 ──────────────────────────────
    def _build_ui(self):
        C = self.colors
        UI = self.FONT_UI
        # 顶栏
        top = tk.Frame(self, bg=C["BG3"], height=52)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="🛰  Sentinel-1 批量下载工具",
                 bg=C["BG3"], fg=C["ACC"],
                 font=(UI, 14, "bold")).pack(side="left", padx=18, pady=12)
        self.lbl_token = tk.Label(top, text="● 未登录", bg=C["BG3"], fg=C["DIS"],
                                  font=(UI, 10))
        self.lbl_token.pack(side="right", padx=18)
        tk.Frame(self, bg=C["BDR"], height=1).pack(fill="x")   # 顶栏分隔线

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
        # 分隔线在状态栏之上（后于状态栏 pack 到底部，故位于其上方）
        tk.Frame(self, bg=C["BDR"], height=1).pack(fill="x", side="bottom")
        tk.Label(sb, textvariable=self.status_var, bg=C["BG3"], fg=C["DIS"],
                 font=(UI, 9), anchor="w").pack(side="left", padx=12, pady=4)

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
