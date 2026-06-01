#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════╗
║      Sentinel-1 SAR 批量搜索 & 下载工具                  ║
║      海河"25·7"洪涝灾害遥感监测数据获取                  ║
║      数据源: Copernicus Data Space (ESA)                 ║
║      作者: 易智瑞杯参赛项目工具脚本                       ║
╚══════════════════════════════════════════════════════════╝

依赖安装:
    pip install requests tqdm

运行方式:
    python sentinel1_downloader.py

功能:
    1. GUI 图形界面操作
    2. OData API 搜索影像
    3. 批量下载 / 断点续传 / 自动重试
    4. Token 自动刷新
    5. 下载日志实时显示
"""

import os
import sys
import json
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime

try:
    import requests
    from tqdm import tqdm
except ImportError:
    print("正在安装依赖...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "tqdm"])
    import requests
    from tqdm import tqdm


# ─────────────────────────────────────────────
#  常量
# ─────────────────────────────────────────────
TOKEN_URL    = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SEARCH_URL   = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
DOWNLOAD_URL = "https://download.dataspace.copernicus.eu/odata/v1/Products({id})/$value"
CONFIG_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "s1_config.json")

AOI_PRESETS = {
    "密云水库区":       "POLYGON((116.8 40.1,117.5 40.1,117.5 40.8,116.8 40.8,116.8 40.1))",
    "怀柔-密云山洪区":  "POLYGON((116.4 40.2,117.0 40.2,117.0 40.7,116.4 40.7,116.4 40.2))",
    "承德兴隆县":       "POLYGON((117.3 40.3,117.9 40.3,117.9 40.8,117.3 40.8,117.3 40.3))",
    "海河北系全域":     "POLYGON((115.8 39.8,118.5 39.8,118.5 41.2,115.8 41.2,115.8 39.8))",
}

PRODUCT_TYPES = {
    "Level-1 GRD（推荐，强度图）": "IW_GRDH_1S",
    "Level-1 SLC（相干分析）":     "IW_SLC__1S",
}


# ─────────────────────────────────────────────
#  后端逻辑
# ─────────────────────────────────────────────
class CopernicusAPI:
    def __init__(self):
        self.token = None
        self.token_time = 0
        self._token_lock = threading.Lock()   # 防止多线程并发刷新 token

    def get_token(self, username, password):
        resp = requests.post(TOKEN_URL, data={
            "client_id": "cdse-public",
            "grant_type": "password",
            "username": username,
            "password": password,
        }, timeout=30)
        resp.raise_for_status()
        self.token = resp.json()["access_token"]
        self.token_time = time.time()
        return self.token

    def refresh_if_needed(self, username, password):
        """Token 有效期约10分钟，提前刷新。加锁确保多 worker 并发时只刷新一次。"""
        with self._token_lock:
            if time.time() - self.token_time > 540:
                self.get_token(username, password)
        return self.token

    def search(self, wkt, date_from, date_to, product_type, max_results=100,
               platforms=None, orbit_dir=None, polarisation=None,
               relative_orbit=None, online_only=False,
               acq_mode=None, absolute_orbit=None,
               name_filter=None):
        """
        参数说明
        --------
        orbit_dir       : "ASCENDING" | "DESCENDING" | None（服务端过滤）
        polarisation    : "VV&VH" | "VV" | "VH" | "HH&HV" | None（服务端过滤）
        relative_orbit  : int | None  相对轨道号（服务端过滤）
        online_only     : bool  True=仅在线产品（服务端过滤）
        platforms       : list[str]  如 ["S1A","S1B"]（客户端名称前缀过滤）
        """
        # ── 按产品名精确搜索（优先级最高，有值时跳过其他 filter）────────
        if name_filter:
            results = []
            for raw_name in name_filter:
                # 去掉 .SAFE 后缀（官网复制的名称可能带也可能不带）
                clean = raw_name.strip().removesuffix(".SAFE").strip()
                if not clean:
                    continue
                # OData 精确匹配：Name eq '...' 或 Name eq '....SAFE'
                # 服务端存储的名称带 .SAFE，所以查询时加上
                f_with    = f"Name eq '{clean}.SAFE'"
                f_without = f"Name eq '{clean}'"
                for name_f in (f_with, f_without):
                    url = (f"{SEARCH_URL}?$filter={requests.utils.quote(name_f, safe='')}"
                           f"&$expand=Attributes&$top=1")
                    resp = requests.get(
                        url,
                        headers={"Authorization": f"Bearer {self.token}"},
                        timeout=60
                    )
                    resp.raise_for_status()
                    hits = resp.json().get("value", [])
                    if hits:
                        results.extend(hits)
                        break   # 找到了就不用试另一种格式
            return results

        def _str_attr(name, value):
            return (f"Attributes/OData.CSC.StringAttribute/any("
                    f"att:att/Name eq '{name}' and "
                    f"att/OData.CSC.StringAttribute/Value eq '{value}')")

        def _int_attr(name, value):
            return (f"Attributes/OData.CSC.IntegerAttribute/any("
                    f"att:att/Name eq '{name}' and "
                    f"att/OData.CSC.IntegerAttribute/Value eq {value})")

        filters = [
            "Collection/Name eq 'SENTINEL-1'",
            _str_attr("productType", product_type),
            f"ContentDate/Start gt {date_from}T00:00:00.000Z",
            f"ContentDate/Start lt {date_to}T23:59:59.999Z",
            f"OData.CSC.Intersects(area=geography'SRID=4326;{wkt}')",
        ]

        # ── 服务端筛选：轨道方向 ──────────────────────────────────────
        if orbit_dir and orbit_dir in ("ASCENDING", "DESCENDING"):
            filters.append(_str_attr("orbitDirection", orbit_dir))

        # ── 服务端筛选：极化方式 ──────────────────────────────────────
        # OData 值示例: "VV&VH"  "VV"  "HH&HV"
        if polarisation:
            filters.append(_str_attr("polarisationChannels", polarisation))

        # ── 服务端筛选：相对轨道号 ────────────────────────────────────
        if relative_orbit is not None:
            try:
                filters.append(_int_attr("relativeOrbitNumber", int(relative_orbit)))
            except (ValueError, TypeError):
                pass

        # ── 服务端筛选：仅在线产品 ────────────────────────────────────
        if online_only:
            filters.append("Online eq true")

        # ── 服务端筛选：成像模式 ─────────────────────────────────────
        if acq_mode:
            filters.append(_str_attr("operationalMode", acq_mode))

        # ── 服务端筛选：绝对轨道号（支持多个，OR 关系）────────────────
        if absolute_orbit:
            abs_parts = [_int_attr("absoluteOrbitNumber", int(n))
                         for n in absolute_orbit if str(n).strip().isdigit()]
            if len(abs_parts) == 1:
                filters.append(abs_parts[0])
            elif len(abs_parts) > 1:
                filters.append("(" + " or ".join(abs_parts) + ")")

        url = (f"{SEARCH_URL}?$filter={requests.utils.quote(' and '.join(filters), safe='')}"
               f"&$expand=Attributes"
               f"&$top={max_results}&$orderby=ContentDate/Start desc")

        resp = requests.get(url, headers={"Authorization": f"Bearer {self.token}"}, timeout=60)
        resp.raise_for_status()
        products = resp.json().get("value", [])

        # ── 客户端过滤：卫星平台（OData 不支持 startswith 在此场景）────
        if platforms:
            products = [p for p in products
                        if any(p.get("Name", "").startswith(pl) for pl in platforms)]

        return products

    def download(self, product_id, product_name, save_dir,
                 username, password, log_cb=None, prog_cb=None,
                 speed_cb=None, stop_event=None, max_retry=3):
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, product_name + ".zip")

        for attempt in range(1, max_retry + 1):
            try:
                self.refresh_if_needed(username, password)
                existing = os.path.getsize(save_path) if os.path.exists(save_path) else 0
                headers = {"Authorization": f"Bearer {self.token}"}

                # ── 先用 HEAD 请求获取服务器文件大小，用于断点续传校验 ──
                head_resp = requests.head(
                    DOWNLOAD_URL.format(id=product_id),
                    headers=headers, timeout=30, allow_redirects=True
                )
                server_size = int(head_resp.headers.get("content-length", 0))

                if existing and server_size:
                    if existing == server_size:
                        if log_cb:
                            log_cb(f"  文件已完整（{existing/1024**2:.1f} MB），跳过", "ok")
                        return True, save_path
                    elif existing < server_size:
                        headers["Range"] = f"bytes={existing}-"
                        if log_cb:
                            log_cb(f"  断点续传，已有 {existing/1024**2:.1f} MB"
                                   f" / 共 {server_size/1024**2:.1f} MB", "info")
                    else:
                        # 本地比服务器大，文件可能损坏，重新下载
                        if log_cb:
                            log_cb("  本地文件异常，重新下载", "warn")
                        existing = 0
                        headers.pop("Range", None)

                url = DOWNLOAD_URL.format(id=product_id)
                resp = requests.get(url, headers=headers, stream=True, timeout=60)

                if resp.status_code == 416:
                    # 双重保险：416 时再次校验大小
                    actual_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
                    if server_size and actual_size != server_size:
                        if log_cb:
                            log_cb(f"  ⚠️ 416 但文件大小不一致"
                                   f"（本地 {actual_size}B vs 服务器 {server_size}B），重新下载", "warn")
                        existing = 0
                        headers.pop("Range", None)
                        resp = requests.get(url, headers=headers, stream=True, timeout=60)
                    else:
                        if log_cb: log_cb("  文件已完整，跳过", "ok")
                        return True, save_path

                resp.raise_for_status()
                total      = int(resp.headers.get("content-length", 0)) + existing
                mode       = "ab" if existing else "wb"
                downloaded = existing

                # ── 实时速度计算 ──
                speed_window_bytes = 0
                speed_window_start = time.time()

                with open(save_path, mode) as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        # ── 每个 chunk 检查停止信号，立即响应 ──
                        if stop_event and stop_event.is_set():
                            if log_cb: log_cb("  ⏹ 下载已中止（文件保留，支持续传）", "warn")
                            if speed_cb: speed_cb(0)
                            return False, None

                        if not chunk:
                            continue
                        f.write(chunk)
                        chunk_len           = len(chunk)
                        downloaded          += chunk_len
                        speed_window_bytes  += chunk_len

                        now     = time.time()
                        elapsed = now - speed_window_start
                        if elapsed >= 1.0:          # 每秒更新一次速度
                            speed_bps          = speed_window_bytes / elapsed
                            speed_window_bytes = 0
                            speed_window_start = now
                            if speed_cb:
                                speed_cb(speed_bps)

                        if total and prog_cb:
                            prog_cb(downloaded / total * 100)

                if log_cb: log_cb(f"  ✅ 完成: {save_path}", "ok")
                if speed_cb: speed_cb(0)            # 完成后清零速度显示
                return True, save_path

            except Exception as e:
                if log_cb: log_cb(f"  ⚠️ 第{attempt}次失败: {e}", "warn")
                if attempt < max_retry:
                    if log_cb: log_cb(f"     {10*attempt}秒后重试...", "info")
                    time.sleep(10 * attempt)
                    try:
                        self.get_token(username, password)
                    except Exception:
                        pass

        if log_cb: log_cb(f"  ❌ 最终失败，已跳过", "err")
        if speed_cb: speed_cb(0)
        return False, None


api = CopernicusAPI()


# ─────────────────────────────────────────────
#  GUI 主窗口
# ─────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Sentinel-1 批量下载工具  |  海河25·7洪涝监测")
        self.geometry("1050x760")
        self.minsize(900, 650)
        self.configure(bg="#0d1117")
        self.resizable(True, True)

        # 状态变量
        self.search_results = []   # 搜索结果
        self.queue          = []   # 下载队列  [{id, name, size, var_check}]
        self.downloading    = False

        self._setup_style()
        self._build_ui()
        self._load_config()

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

    # ── 顶栏 ──────────────────────────────────
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

        self._build_auth_tab()
        self._build_search_tab()
        self._build_dl_tab()

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        sb = tk.Frame(self, bg=C["BG3"], height=28)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        tk.Label(sb, textvariable=self.status_var, bg=C["BG3"], fg=C["DIS"],
                 font=("Consolas", 9), anchor="w").pack(side="left", padx=12, pady=4)

    # ── Tab 1: 账号 ────────────────────────────
    def _build_auth_tab(self):
        C = self.colors
        f = self.tab_auth
        pad = dict(padx=16, pady=6)

        # 账号框
        box = ttk.LabelFrame(f, text=" Copernicus 账号 ", padding=14)
        box.pack(fill="x", padx=18, pady=(18, 8))

        r = 0
        tk.Label(box, text="邮箱：").grid(row=r, column=0, sticky="e", **pad)
        self.ent_user = ttk.Entry(box, width=40)
        self.ent_user.grid(row=r, column=1, sticky="ew", **pad)

        r += 1
        tk.Label(box, text="密码：").grid(row=r, column=0, sticky="e", **pad)
        self.ent_pass = ttk.Entry(box, width=40, show="●")
        self.ent_pass.grid(row=r, column=1, sticky="ew", **pad)

        r += 1
        tk.Label(box, text="保存路径：").grid(row=r, column=0, sticky="e", **pad)
        pf = ttk.Frame(box)
        pf.grid(row=r, column=1, sticky="ew", **pad)
        self.ent_path = ttk.Entry(pf, width=32)
        self.ent_path.pack(side="left", fill="x", expand=True)
        ttk.Button(pf, text="浏览", command=self._browse_path).pack(side="left", padx=(6,0))

        box.columnconfigure(1, weight=1)

        # 按钮
        bf = ttk.Frame(f)
        bf.pack(fill="x", padx=18, pady=4)
        ttk.Button(bf, text="🔐  测试登录", style="Accent.TButton",
                   command=self._test_login).pack(side="left", padx=(0,8))
        ttk.Button(bf, text="💾  保存配置",
                   command=self._save_config).pack(side="left")

        # 提示
        hint = ttk.LabelFrame(f, text=" 使用说明 ", padding=14)
        hint.pack(fill="x", padx=18, pady=(14,0))
        hints = [
            "① 注册账号：dataspace.copernicus.eu  （免费注册）",
            "② 填写账号 → 测试登录 → 保存配置",
            "③ 切换「搜索影像」标签 → 设置条件 → 搜索",
            "④ 勾选影像 → 加入队列 → 切换「下载管理」→ 开始下载",
            "⑤ 脚本支持断点续传，中断后重新运行自动续传",
            "⑥ 建议使用全局VPN，提升访问 ESA 服务器速度",
        ]
        for h in hints:
            tk.Label(hint, text=h, fg=C["DIS"], font=("Consolas", 9),
                     anchor="w").pack(fill="x", pady=1)

        # 登录日志
        self.auth_log = scrolledtext.ScrolledText(
            f, height=7, bg=C["BG2"], fg=C["FG"],
            font=("Consolas", 9), insertbackground=C["FG"],
            relief="flat", state="disabled", wrap="word")
        self.auth_log.pack(fill="x", padx=18, pady=(12,0))
        self.auth_log.tag_config("ok",   foreground=C["GRN"])
        self.auth_log.tag_config("err",  foreground=C["RED"])
        self.auth_log.tag_config("warn", foreground=C["ORG"])
        self.auth_log.tag_config("info", foreground=C["ACC"])

    # ── Tab 2: 搜索 ────────────────────────────
    def _build_search_tab(self):
        C = self.colors
        f = self.tab_search

        # 左：条件面板（带滚动条）
        left_container = ttk.Frame(f, width=340)
        left_container.pack(side="left", fill="y", padx=(12,6), pady=12)
        left_container.pack_propagate(False)

        # 创建 Canvas 和 Scrollbar
        canvas = tk.Canvas(left_container, bg=C["BG"], highlightthickness=0, width=320)
        scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=canvas.yview)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)

        # 在 Canvas 中创建内容框架
        left = ttk.Frame(canvas, width=320)
        canvas_window = canvas.create_window((0, 0), window=left, anchor="nw", width=320)

        def on_canvas_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        left.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        # 鼠标滚轮滚动
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        # 时间
        tbox = ttk.LabelFrame(left, text=" 时间范围 ", padding=10)
        tbox.pack(fill="x", pady=(0,8))
        tf = ttk.Frame(tbox)
        tf.pack(fill="x")
        tk.Label(tf, text="从：", width=4).pack(side="left")
        self.ent_from = ttk.Entry(tf, width=13)
        self.ent_from.insert(0, "2025-07-20")
        self.ent_from.pack(side="left")
        tk.Label(tf, text=" 至：").pack(side="left")
        self.ent_to = ttk.Entry(tf, width=13)
        self.ent_to.insert(0, "2025-08-31")
        self.ent_to.pack(side="left")

        # AOI
        abox = ttk.LabelFrame(left, text=" 研究区 AOI ", padding=10)
        abox.pack(fill="x", pady=(0,8))
        self.aoi_var = tk.StringVar(value="海河北系全域")
        for name in AOI_PRESETS:
            rb = tk.Radiobutton(abox, text=name, variable=self.aoi_var, value=name,
                                bg=C["BG"], fg=C["FG"], selectcolor=C["BG2"],
                                activebackground=C["BG"], activeforeground=C["ACC"],
                                font=("Consolas", 9), command=self._aoi_changed)
            rb.pack(anchor="w")
        tk.Radiobutton(abox, text="自定义 WKT", variable=self.aoi_var, value="custom",
                       bg=C["BG"], fg=C["FG"], selectcolor=C["BG2"],
                       activebackground=C["BG"], activeforeground=C["ACC"],
                       font=("Consolas", 9), command=self._aoi_changed).pack(anchor="w")
        self.ent_wkt = tk.Text(abox, height=3, bg=C["BG2"], fg=C["FG"],
                               font=("Consolas", 8), insertbackground=C["FG"],
                               relief="flat", wrap="word")
        self.ent_wkt.pack(fill="x", pady=(4,0))
        self._aoi_changed()

        # 产品参数
        pbox = ttk.LabelFrame(left, text=" 产品参数 ", padding=10)
        pbox.pack(fill="x", pady=(0,8))

        tk.Label(pbox, text="产品类型：", font=("Consolas", 9)).pack(anchor="w")
        self.cmb_type = ttk.Combobox(pbox, values=list(PRODUCT_TYPES.keys()),
                                     state="readonly", font=("Consolas", 9))
        self.cmb_type.current(0)
        self.cmb_type.pack(fill="x", pady=(2,8))

        tk.Label(pbox, text="卫星平台：", font=("Consolas", 9)).pack(anchor="w")
        pf2 = ttk.Frame(pbox)
        pf2.pack(anchor="w", pady=(2,8))
        self.var_s1a = tk.BooleanVar(value=True)
        self.var_s1b = tk.BooleanVar(value=True)
        self.var_s1c = tk.BooleanVar(value=True)
        ttk.Checkbutton(pf2, text="S1A", variable=self.var_s1a).pack(side="left", padx=(0,8))
        ttk.Checkbutton(pf2, text="S1B", variable=self.var_s1b).pack(side="left", padx=(0,8))
        ttk.Checkbutton(pf2, text="S1C", variable=self.var_s1c).pack(side="left")

        # ── 新增：轨道方向（服务端过滤）────────────────────────────────
        tk.Label(pbox, text="轨道方向：", font=("Consolas", 9)).pack(anchor="w")
        self.cmb_orbit = ttk.Combobox(
            pbox,
            values=["不限", "升轨 ASCENDING", "降轨 DESCENDING"],
            state="readonly", font=("Consolas", 9))
        self.cmb_orbit.current(0)
        self.cmb_orbit.pack(fill="x", pady=(2,8))

        # ── 新增：极化方式（服务端过滤）────────────────────────────────
        tk.Label(pbox, text="极化方式：", font=("Consolas", 9)).pack(anchor="w")
        self.cmb_pol = ttk.Combobox(
            pbox,
            values=["不限", "VV&VH（双极化）", "VV（单极化）",
                    "VH（单极化）", "HH&HV（双极化）", "HH（单极化）"],
            state="readonly", font=("Consolas", 9))
        self.cmb_pol.current(0)
        self.cmb_pol.pack(fill="x", pady=(2,8))

        # ── 新增：相对轨道号（服务端过滤，留空=不限）──────────────────
        tk.Label(pbox, text="相对轨道号（留空=不限）：", font=("Consolas", 9)).pack(anchor="w")
        self.ent_orbit_num = ttk.Entry(pbox, width=10, font=("Consolas", 9))
        self.ent_orbit_num.pack(anchor="w", pady=(2,8))

        # ── 新增：成像模式（服务端过滤）────────────────────────────────
        tk.Label(pbox, text="成像模式：", font=("Consolas", 9)).pack(anchor="w")
        self.cmb_mode = ttk.Combobox(
            pbox,
            values=["不限", "IW（干涉宽幅，推荐）", "EW（超宽幅）", "SM（条带）", "WV（波浪）"],
            state="readonly", font=("Consolas", 9))
        self.cmb_mode.current(0)
        self.cmb_mode.pack(fill="x", pady=(2,8))

        # ── 新增：绝对轨道号（服务端过滤，逗号分隔多个，留空=不限）─────
        tk.Label(pbox, text="绝对轨道号（逗号分隔，留空=不限）：", font=("Consolas", 9)).pack(anchor="w")
        self.ent_abs_orbit = ttk.Entry(pbox, width=20, font=("Consolas", 9))
        self.ent_abs_orbit.pack(anchor="w", pady=(2,8))

        # ── 新增：仅在线产品（服务端过滤）──────────────────────────────
        self.var_online = tk.BooleanVar(value=True)
        ttk.Checkbutton(pbox, text="仅显示在线产品（跳过归档）",
                        variable=self.var_online).pack(anchor="w", pady=(0,8))

        tk.Label(pbox, text="最大返回数：", font=("Consolas", 9)).pack(anchor="w")
        self.cmb_max = ttk.Combobox(pbox, values=["20","50","100","200"],
                                    state="readonly", width=8, font=("Consolas", 9))
        self.cmb_max.set("50")
        self.cmb_max.pack(anchor="w", pady=(2,0))

        # 搜索按钮
        bf = ttk.Frame(left)
        bf.pack(fill="x", pady=8)
        ttk.Button(bf, text="🔍  执行搜索", style="Accent.TButton",
                   command=self._do_search).pack(fill="x")

        # 右：结果列表
        right = ttk.Frame(f)
        right.pack(side="left", fill="both", expand=True, padx=(0,12), pady=12)

        # ── 名称搜索栏（官网复制文件名直接搜索）────────────────────────
        nsf = ttk.LabelFrame(right, text=" 📋 按产品名搜索（官网复制粘贴）", padding=8)
        nsf.pack(fill="x", pady=(0,8))

        # 说明文字
        tk.Label(nsf,
                 text="支持多个名称（换行或逗号分隔），带不带 .SAFE 均可",
                 fg=C["DIS"], font=("Consolas", 8), bg=C["BG"]).pack(anchor="w")

        # 输入框 + 按钮 同行
        ns_row = ttk.Frame(nsf)
        ns_row.pack(fill="x", pady=(4, 0))

        self.ent_name_search = tk.Text(
            ns_row, height=3,
            bg=C["BG2"], fg=C["FG"],
            font=("Consolas", 9),
            insertbackground=C["FG"],
            relief="flat", wrap="word"
        )
        self.ent_name_search.pack(side="left", fill="x", expand=True)

        btn_col = ttk.Frame(ns_row)
        btn_col.pack(side="left", padx=(6, 0))
        ttk.Button(btn_col, text="🔍 搜索",
                   style="Accent.TButton",
                   command=self._do_name_search).pack(fill="x", pady=(0, 4))
        ttk.Button(btn_col, text="清空",
                   command=lambda: self.ent_name_search.delete("1.0", "end")).pack(fill="x")

        # 结果工具栏
        rtb = ttk.Frame(right)
        rtb.pack(fill="x", pady=(0,6))
        self.lbl_count = tk.Label(rtb, text="搜索结果：0 景", fg=C["ACC"],
                                  font=("Consolas", 10, "bold"), bg=C["BG"])
        self.lbl_count.pack(side="left")
        ttk.Button(rtb, text="全选", command=self._select_all).pack(side="right", padx=4)
        ttk.Button(rtb, text="全不选", command=self._deselect_all).pack(side="right", padx=4)
        ttk.Button(rtb, text="+ 加入下载队列", style="Green.TButton",
                   command=self._add_to_queue).pack(side="right", padx=(0,8))

        # 结果 Treeview（横向可滚动）
        cols = ("sel","name","date","platform","mode","pol","orbit_dir",
                "rel_orbit","abs_orbit","size","online")

        tree_frame = ttk.Frame(right)
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                 selectmode="extended")
        self.tree.heading("sel",       text="✓")
        self.tree.heading("name",      text="产品名称")
        self.tree.heading("date",      text="感测时间 (UTC)")
        self.tree.heading("platform",  text="平台")
        self.tree.heading("mode",      text="模式")
        self.tree.heading("pol",       text="极化")
        self.tree.heading("orbit_dir", text="轨道")
        self.tree.heading("rel_orbit", text="相对轨道号")
        self.tree.heading("abs_orbit", text="绝对轨道号")
        self.tree.heading("size",      text="大小")
        self.tree.heading("online",    text="状态")
        self.tree.column("sel",       width=30,  anchor="center", stretch=False)
        self.tree.column("name",      width=340, anchor="w",      stretch=False)
        self.tree.column("date",      width=145, anchor="center", stretch=False)
        self.tree.column("platform",  width=50,  anchor="center", stretch=False)
        self.tree.column("mode",      width=50,  anchor="center", stretch=False)
        self.tree.column("pol",       width=70,  anchor="center", stretch=False)
        self.tree.column("orbit_dir", width=55,  anchor="center", stretch=False)
        self.tree.column("rel_orbit", width=80,  anchor="center", stretch=False)
        self.tree.column("abs_orbit", width=80,  anchor="center", stretch=False)
        self.tree.column("size",      width=65,  anchor="center", stretch=False)
        self.tree.column("online",    width=65,  anchor="center", stretch=False)
        self.tree.tag_configure("even", background=C["BG2"])
        self.tree.tag_configure("odd",  background="#13181f")
        self.tree.tag_configure("sel",  background=C["SEL"])
        self.tree.bind("<Button-1>", self._tree_click)

        sb_y = ttk.Scrollbar(tree_frame, orient="vertical",   command=self.tree.yview)
        sb_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_x.pack(side="bottom", fill="x")
        sb_y.pack(side="right",  fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # 统计面板（表格下方一行）
        self.lbl_stats = tk.Label(right, text="", fg=C["DIS"],
                                  font=("Consolas", 9), bg=C["BG"], anchor="w")
        self.lbl_stats.pack(fill="x", pady=(4, 0))

        self._selected_iids = set()   # 已勾选行

    # ── Tab 3: 下载 ────────────────────────────
    def _build_dl_tab(self):
        C = self.colors
        f = self.tab_dl

        # 队列列表
        qf = ttk.LabelFrame(f, text=" 下载队列 ", padding=10)
        qf.pack(fill="both", expand=True, padx=12, pady=(12,6))

        # 队列工具栏
        qtb = ttk.Frame(qf)
        qtb.pack(fill="x", pady=(0,6))
        self.lbl_queue = tk.Label(qtb, text="队列：0 景  |  0.0 GB",
                                  fg=C["ACC"], font=("Consolas", 10, "bold"), bg=C["BG"])
        self.lbl_queue.pack(side="left")
        ttk.Button(qtb, text="清空队列", command=self._clear_queue).pack(side="right")
        ttk.Button(qtb, text="移除选中", command=self._remove_selected).pack(side="right", padx=4)

        # 队列 Treeview
        qcols = ("idx","name","size","status")
        self.qtree = ttk.Treeview(qf, columns=qcols, show="headings", selectmode="extended")
        self.qtree.heading("idx",    text="#")
        self.qtree.heading("name",   text="产品名称")
        self.qtree.heading("size",   text="大小")
        self.qtree.heading("status", text="状态")
        self.qtree.column("idx",    width=36,  anchor="center", stretch=False)
        self.qtree.column("name",   width=430, anchor="w")
        self.qtree.column("size",   width=70,  anchor="center")
        self.qtree.column("status", width=120, anchor="center")
        self.qtree.tag_configure("waiting",     foreground=C["DIS"])
        self.qtree.tag_configure("downloading", foreground=C["ACC"])
        self.qtree.tag_configure("done",        foreground=C["GRN"])
        self.qtree.tag_configure("error",       foreground=C["RED"])

        qsb = ttk.Scrollbar(qf, orient="vertical", command=self.qtree.yview)
        self.qtree.configure(yscrollcommand=qsb.set)
        self.qtree.pack(side="left", fill="both", expand=True)
        qsb.pack(side="right", fill="y")

        # 进度区
        pgf = ttk.Frame(f)
        pgf.pack(fill="x", padx=12, pady=(0,6))
        self.lbl_prog = tk.Label(pgf, text="当前进度：-", fg=C["DIS"],
                                 font=("Consolas", 9), bg=C["BG"])
        self.lbl_prog.pack(anchor="w")
        self.prog_bar = ttk.Progressbar(pgf, mode="determinate", length=100)
        self.prog_bar.pack(fill="x", pady=(3,0))

        # 控制按钮
        cbf = ttk.Frame(f)
        cbf.pack(fill="x", padx=12, pady=(0,6))
        self.btn_start = ttk.Button(cbf, text="▶  开始下载", style="Accent.TButton",
                                    command=self._start_download)
        self.btn_start.pack(side="left", padx=(0,8))
        self.btn_stop = ttk.Button(cbf, text="⏹  停止", command=self._stop_download,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=(0,16))

        # 并行数选择
        tk.Label(cbf, text="并行：", fg=C["DIS"], font=("Consolas", 9), bg=C["BG"]).pack(side="left")
        self.cmb_parallel = ttk.Combobox(cbf, values=["1","2","3","4","5"],
                                          state="readonly", width=3, font=("Consolas", 9))
        self.cmb_parallel.set("3")
        self.cmb_parallel.pack(side="left")
        tk.Label(cbf, text=" 景", fg=C["DIS"], font=("Consolas", 9), bg=C["BG"]).pack(side="left")

        self.lbl_speed = tk.Label(cbf, text="", fg=C["ORG"],
                                  font=("Consolas", 9), bg=C["BG"])
        self.lbl_speed.pack(side="right")

        # 下载日志
        lf = ttk.LabelFrame(f, text=" 下载日志 ", padding=8)
        lf.pack(fill="x", padx=12, pady=(0,12))
        self.dl_log = scrolledtext.ScrolledText(
            lf, height=10, bg=C["BG2"], fg=C["FG"],
            font=("Consolas", 9), insertbackground=C["FG"],
            relief="flat", state="disabled", wrap="word")
        self.dl_log.pack(fill="x")
        self.dl_log.tag_config("ok",   foreground=C["GRN"])
        self.dl_log.tag_config("err",  foreground=C["RED"])
        self.dl_log.tag_config("warn", foreground=C["ORG"])
        self.dl_log.tag_config("info", foreground=C["ACC"])
        self.dl_log.tag_config("head", foreground="#ffffff", font=("Consolas", 9, "bold"))

        self._stop_event = threading.Event()

    # ─────────────────────────────────────────
    #  事件处理
    # ─────────────────────────────────────────
    def _browse_path(self):
        d = filedialog.askdirectory()
        if d:
            self.ent_path.delete(0, "end")
            self.ent_path.insert(0, d)

    def _aoi_changed(self):
        val = self.aoi_var.get()
        self.ent_wkt.delete("1.0", "end")
        if val in AOI_PRESETS:
            self.ent_wkt.insert("1.0", AOI_PRESETS[val])

    def _tree_click(self, event):
        """点击第一列切换勾选"""
        col = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if col == "#1":
            if iid in self._selected_iids:
                self._selected_iids.discard(iid)
                self.tree.set(iid, "sel", "")
            else:
                self._selected_iids.add(iid)
                self.tree.set(iid, "sel", "✓")

    def _select_all(self):
        for iid in self.tree.get_children():
            self._selected_iids.add(iid)
            self.tree.set(iid, "sel", "✓")

    def _deselect_all(self):
        for iid in self.tree.get_children():
            self._selected_iids.discard(iid)
            self.tree.set(iid, "sel", "")

    # ─ 登录 ──────────────────────────────────
    def _test_login(self):
        u = self.ent_user.get().strip()
        p = self.ent_pass.get().strip()
        if not u or not p:
            messagebox.showwarning("提示", "请先填写账号和密码")
            return
        self._log(self.auth_log, "正在获取 Token...", "info")

        def _run():
            try:
                api.get_token(u, p)
                self.after(0, lambda: self._log(self.auth_log, "✅ 登录成功！Token 已获取", "ok"))
                self.after(0, lambda: self.lbl_token.config(
                    text="● 已登录", fg=self.colors["GRN"]))
                self.after(0, lambda: self.set_status("登录成功"))
            except Exception as e:
                self.after(0, lambda: self._log(self.auth_log, f"❌ 登录失败: {e}", "err"))
                self.after(0, lambda: self.lbl_token.config(
                    text="● 登录失败", fg=self.colors["RED"]))
                self.after(0, lambda: self.set_status("登录失败"))

        threading.Thread(target=_run, daemon=True).start()

    # ─ 搜索 ──────────────────────────────────
    def _do_search(self):
        if not api.token:
            messagebox.showwarning("提示", "请先在「账号配置」标签页登录")
            return
        wkt = self.ent_wkt.get("1.0", "end").strip()
        if not wkt:
            messagebox.showwarning("提示", "请选择或输入研究区 WKT")
            return

        date_from    = self.ent_from.get().strip()
        date_to      = self.ent_to.get().strip()
        product_type = PRODUCT_TYPES[self.cmb_type.get()]
        max_results  = int(self.cmb_max.get())

        # 平台（客户端过滤）
        platforms = []
        if self.var_s1a.get(): platforms.append("S1A")
        if self.var_s1b.get(): platforms.append("S1B")
        if self.var_s1c.get(): platforms.append("S1C")

        # 轨道方向（服务端）
        orbit_sel = self.cmb_orbit.get()
        orbit_dir = None
        if "ASCENDING"  in orbit_sel: orbit_dir = "ASCENDING"
        if "DESCENDING" in orbit_sel: orbit_dir = "DESCENDING"

        # 极化方式（服务端）
        pol_map = {
            "VV&VH（双极化）": "VV&VH",
            "VV（单极化）":    "VV",
            "VH（单极化）":    "VH",
            "HH&HV（双极化）": "HH&HV",
            "HH（单极化）":    "HH",
        }
        pol_sel     = self.cmb_pol.get()
        polarisation = pol_map.get(pol_sel, None)

        # 相对轨道号（服务端）
        rel_orbit_str = self.ent_orbit_num.get().strip()
        relative_orbit = int(rel_orbit_str) if rel_orbit_str.isdigit() else None

        # 仅在线（服务端）
        online_only = self.var_online.get()

        # 成像模式（服务端）
        mode_map = {
            "IW（干涉宽幅，推荐）": "IW",
            "EW（超宽幅）":        "EW",
            "SM（条带）":          "SM",
            "WV（波浪）":          "WV",
        }
        acq_mode = mode_map.get(self.cmb_mode.get(), None)

        # 绝对轨道号（服务端，逗号分隔解析为列表）
        abs_orbit_str = self.ent_abs_orbit.get().strip()
        absolute_orbit = [s.strip() for s in abs_orbit_str.split(",")
                          if s.strip().isdigit()] if abs_orbit_str else None

        self.lbl_count.config(text="搜索中...")
        self.set_status("正在搜索...")

        def _run():
            try:
                results = api.search(
                    wkt, date_from, date_to, product_type, max_results,
                    platforms=platforms,
                    orbit_dir=orbit_dir,
                    polarisation=polarisation,
                    relative_orbit=relative_orbit,
                    online_only=online_only,
                    acq_mode=acq_mode,
                    absolute_orbit=absolute_orbit,
                )
                self.search_results = results
                self.after(0, self._render_results)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("搜索失败", str(e)))
                self.after(0, lambda: self.set_status(f"搜索失败: {e}"))
                self.after(0, lambda: self.lbl_count.config(text="搜索失败"))

        threading.Thread(target=_run, daemon=True).start()

    def _do_name_search(self):
        """按产品名精确搜索，支持多个名称（换行或逗号分隔）"""
        if not api.token:
            messagebox.showwarning("提示", "请先在「账号配置」标签页登录")
            return

        raw_text = self.ent_name_search.get("1.0", "end").strip()
        if not raw_text:
            messagebox.showwarning("提示", "请输入产品名称")
            return

        # 解析：先按换行切，再按逗号切，去空、去重、保序
        seen = set()
        names = []
        for part in raw_text.replace(",", "\n").splitlines():
            n = part.strip().removesuffix(".SAFE").strip()
            if n and n not in seen:
                seen.add(n)
                names.append(n)

        if not names:
            messagebox.showwarning("提示", "未解析到有效产品名称")
            return

        self.lbl_count.config(text=f"正在搜索 {len(names)} 个产品名...")
        self.set_status(f"按名称搜索中，共 {len(names)} 个...")

        def _run():
            try:
                results = api.search(
                    wkt=None, date_from=None, date_to=None,
                    product_type=None,
                    name_filter=names,
                )
                not_found = len(names) - len(results)
                self.search_results = results
                self.after(0, self._render_results)
                if not_found > 0:
                    self.after(0, lambda: self.set_status(
                        f"搜索完成：找到 {len(results)} 景，"
                        f"未找到 {not_found} 个（名称有误或已下架）"
                    ))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("搜索失败", str(e)))
                self.after(0, lambda: self.set_status(f"名称搜索失败: {e}"))
                self.after(0, lambda: self.lbl_count.config(text="搜索失败"))

        threading.Thread(target=_run, daemon=True).start()

    def _render_results(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._selected_iids.clear()

        queue_ids = {q["id"] for q in self.queue}

        # ── 统计计数器 ──────────────────────────────────────────────────
        stat_plat  = {}   # {"S1A": n, ...}
        stat_orbit = {}   # {"ASC": n, "DESC": n}
        stat_pol   = {}   # {"VV&VH": n, ...}
        stat_mode  = {}   # {"IW": n, ...}

        for i, p in enumerate(self.search_results):
            name = p.get("Name", p.get("Id", "—"))
            date = p.get("ContentDate", {}).get("Start", "")[:16].replace("T", " ")

            # 平台
            if   name.startswith("S1A"): plat = "S1A"
            elif name.startswith("S1C"): plat = "S1C"
            else:                         plat = "S1B"

            # 从 Attributes 提取各字段
            attrs = {a["Name"]: a.get("Value", "—")
                     for a in p.get("Attributes", []) if "Name" in a}

            pol       = attrs.get("polarisationChannels", "—")
            orbit_dir = attrs.get("orbitDirection", "—")
            rel_orbit = str(attrs.get("relativeOrbitNumber", "—"))
            abs_orbit = str(attrs.get("absoluteOrbitNumber", "—"))
            mode      = attrs.get("operationalMode", "—")

            # 极化退回推断
            if pol == "—":
                pol = "VV&VH" if "DV" in name else ("HH&HV" if "DH" in name else "—")

            # 轨道方向简写
            orbit_short = {"ASCENDING": "ASC", "DESCENDING": "DESC"}.get(orbit_dir, orbit_dir)

            size   = f"{p.get('ContentLength', 1700*1024*1024)/1024**3:.1f}GB"
            online = "✓在线" if p.get("Online", True) else "归档"
            inq    = " ★" if p["Id"] in queue_ids else ""
            tag    = "even" if i % 2 == 0 else "odd"

            self.tree.insert("", "end", iid=str(i),
                             values=("", name, date+" UTC", plat, mode, pol,
                                     orbit_short, rel_orbit, abs_orbit,
                                     size, online+inq),
                             tags=(tag,))

            # 累计统计
            stat_plat[plat]            = stat_plat.get(plat, 0) + 1
            stat_orbit[orbit_short]    = stat_orbit.get(orbit_short, 0) + 1
            stat_pol[pol]              = stat_pol.get(pol, 0) + 1
            stat_mode[mode]            = stat_mode.get(mode, 0) + 1

        # ── 更新统计面板 ────────────────────────────────────────────────
        total = len(self.search_results)
        def _fmt(d):
            return "  ".join(f"{k}:{v}" for k, v in sorted(d.items()) if k != "—")

        stats_str = (
            f"共 {total} 景  |  "
            f"{_fmt(stat_plat)}  |  "
            f"{_fmt(stat_orbit)}  |  "
            f"{_fmt(stat_pol)}  |  "
            f"{_fmt(stat_mode)}"
        ) if total else "无结果"

        self.lbl_stats.config(text=stats_str)
        self.lbl_count.config(text=f"搜索结果：{total} 景")
        self.set_status(f"搜索完成，共 {total} 景")

    # ─ 加入队列 ───────────────────────────────
    def _add_to_queue(self):
        if not self._selected_iids:
            messagebox.showinfo("提示", "请先勾选要下载的影像（点击第一列 ✓）")
            return
        queue_ids = {q["id"] for q in self.queue}
        added = 0
        for iid in self._selected_iids:
            idx = int(iid)
            if idx >= len(self.search_results):
                continue
            p = self.search_results[idx]
            if p["Id"] in queue_ids:
                continue
            self.queue.append({
                "id":     p["Id"],
                "name":   p.get("Name", p["Id"]),
                "size":   f"{p.get('ContentLength', 1700*1024*1024)/1024**3:.1f} GB",
                "status": "waiting",
            })
            added += 1
        self._render_queue()
        self._render_results()
        messagebox.showinfo("✅", f"已添加 {added} 景到下载队列")

    # ─ 队列渲染 ───────────────────────────────
    def _render_queue(self):
        for iid in self.qtree.get_children():
            self.qtree.delete(iid)
        total_gb = 0
        for i, q in enumerate(self.queue):
            status_txt = {"waiting":"等待中","downloading":"下载中","done":"✅ 完成","error":"❌ 失败"}.get(q["status"], q["status"])
            self.qtree.insert("", "end", iid=str(i),
                              values=(i+1, q["name"], q["size"], status_txt),
                              tags=(q["status"],))
            try:
                total_gb += float(q["size"].replace(" GB",""))
            except Exception:
                pass
        self.lbl_queue.config(text=f"队列：{len(self.queue)} 景  |  {total_gb:.1f} GB")

    def _clear_queue(self):
        if self.downloading:
            messagebox.showwarning("提示", "下载中，请先停止")
            return
        if self.queue and messagebox.askyesno("确认", "确定清空下载队列？"):
            self.queue.clear()
            self._render_queue()

    def _remove_selected(self):
        sel = self.qtree.selection()
        if not sel:
            return
        idxs = sorted([int(s) for s in sel], reverse=True)
        for idx in idxs:
            if idx < len(self.queue):
                del self.queue[idx]
        self._render_queue()

    # ─ 下载 ──────────────────────────────────
    def _start_download(self):
        if not api.token:
            messagebox.showwarning("提示", "请先在「账号配置」标签页登录")
            return
        if not self.queue:
            messagebox.showinfo("提示", "下载队列为空")
            return
        save_dir = self.ent_path.get().strip()
        if not save_dir:
            messagebox.showwarning("提示", "请先在「账号配置」中设置保存路径")
            return
        if self.downloading:
            return

        self.downloading   = True
        self._stop_event   = threading.Event()
        self._stop_event.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.cmb_parallel.config(state="disabled")

        # 并行汇总速度：每个槽位维护自己的 bps，主线程汇总显示
        n_workers = int(self.cmb_parallel.get())
        self._slot_speeds = [0.0] * n_workers   # 各并行槽位的实时速度
        self._slot_lock   = threading.Lock()

        def _update_total_speed():
            with self._slot_lock:
                total_bps = sum(self._slot_speeds)
            if total_bps <= 0:
                self.lbl_speed.config(text="")
            elif total_bps >= 1024 * 1024:
                self.lbl_speed.config(text=f"⚡ {total_bps/1024/1024:.1f} MB/s")
            else:
                self.lbl_speed.config(text=f"⚡ {total_bps/1024:.0f} KB/s")

        def _make_speed_cb(slot_idx):
            def _speed(bps):
                with self._slot_lock:
                    self._slot_speeds[slot_idx] = max(bps, 0)
                self.after(0, _update_total_speed)
            return _speed

        def _run():
            import concurrent.futures
            u = self.ent_user.get().strip()
            p = self.ent_pass.get().strip()
            pending   = [q for q in self.queue if q["status"] != "done"]
            total     = len(pending)
            ok_cnt    = 0
            lock      = threading.Lock()

            self._dlog(f"═══ 开始下载 {total} 景（并行 {n_workers} 景）═══", "head")
            self._dlog(f"保存路径: {save_dir}", "info")

            # 所有 worker 共享同一个 api 实例（已内置线程锁），不再各自建实例
            # 避免各实例独立刷新 token 时发生竞争覆盖
            shared_api = CopernicusAPI()
            shared_api.token      = api.token
            shared_api.token_time = api.token_time

            def _download_one(args):
                slot_idx, q = args
                if self._stop_event.is_set():
                    return False

                name = q["name"]
                self._dlog(f"  ↓ [{name[:40]}] 开始", "head")

                q["status"] = "downloading"
                self.after(0, self._render_queue)

                def _prog(pct):
                    pass  # 单景进度不更新进度条，避免多线程冲突

                ok, _ = shared_api.download(
                    q["id"], name, save_dir, u, p,
                    log_cb=lambda m, t="info": self._dlog(f"  [{name[:20]}] {m}", t),
                    prog_cb=_prog,
                    speed_cb=_make_speed_cb(slot_idx % n_workers),
                    stop_event=self._stop_event,
                )
                with lock:
                    nonlocal ok_cnt
                    if ok:
                        ok_cnt += 1
                q["status"] = "done" if ok else "error"
                self.after(0, self._render_queue)
                # 更新总进度条（已完成景数 / 总景数）
                done = sum(1 for qq in pending if qq["status"] in ("done", "error"))
                self.after(0, lambda d=done: self.prog_bar.config(value=d / total * 100))
                self.after(0, lambda n=name, ok=ok:
                    self._dlog(f"  {'✅' if ok else '❌'} [{n[:40]}] {'完成' if ok else '失败'}", "ok" if ok else "err"))
                return ok

            with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as executor:
                list(executor.map(_download_one, enumerate(pending)))

            # 清零所有槽位速度
            with self._slot_lock:
                self._slot_speeds = [0.0] * n_workers
            self.after(0, _update_total_speed)

            self._dlog(f"\n═══ 完成！成功 {ok_cnt}/{total} 景 ═══", "head")

            def _on_done():
                self.prog_bar.config(value=0)
                self.lbl_prog.config(text=f"完成！成功 {ok_cnt}/{total} 景")
                self.btn_start.config(state="normal")
                self.btn_stop.config(state="disabled")
                self.cmb_parallel.config(state="readonly")
                self.downloading = False

            self.after(0, _on_done)

        threading.Thread(target=_run, daemon=True).start()

    def _stop_download(self):
        self._stop_event.set()
        self.set_status("正在停止...")
        self.btn_stop.config(state="disabled")   # 防止重复点击

    # ─ 工具 ──────────────────────────────────
    def _log(self, widget, msg, tag="info"):
        def _do():
            widget.config(state="normal")
            now = datetime.now().strftime("%H:%M:%S")
            widget.insert("end", f"[{now}] {msg}\n", tag)
            widget.see("end")
            widget.config(state="disabled")
        self.after(0, _do)

    def _dlog(self, msg, tag="info"):
        self._log(self.dl_log, msg, tag)

    def set_status(self, msg):
        self.after(0, lambda: self.status_var.set(msg))

    # ─ 配置存储 ───────────────────────────────
    def _save_config(self):
        cfg = {
            "username":  self.ent_user.get(),
            "save_path": self.ent_path.get(),
            "date_from": self.ent_from.get(),
            "date_to":   self.ent_to.get(),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self._log(self.auth_log, "✅ 配置已保存", "ok")
        except Exception as e:
            self._log(self.auth_log, f"❌ 保存失败: {e}", "err")

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.ent_user.insert(0, cfg.get("username", ""))
            self.ent_path.insert(0, cfg.get("save_path", ""))
            if cfg.get("date_from"):
                self.ent_from.delete(0, "end")
                self.ent_from.insert(0, cfg["date_from"])
            if cfg.get("date_to"):
                self.ent_to.delete(0, "end")
                self.ent_to.insert(0, cfg["date_to"])
        except Exception:
            pass


# ─────────────────────────────────────────────
#  入口
# ─────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()