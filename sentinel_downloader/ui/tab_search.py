#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索影像 Tab
────────────────────────────────────────────────────────
构建检索条件面板与结果列表，并提供条件搜索、按名称搜索、结果渲染、
勾选管理、加入下载队列等回调。
"""

import csv
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox, filedialog

from core.config import AOI_PRESETS, PRODUCT_TYPES
from ui.tab_download import render_queue


def build_search_tab(app):
    """在 app.tab_search 上构建搜索界面，绑定所有事件。"""
    C = app.colors
    f = app.tab_search

    # 左：条件面板（带滚动条）
    left_container = ttk.Frame(f, width=340)
    left_container.pack(side="left", fill="y", padx=(12, 6), pady=12)
    left_container.pack_propagate(False)

    # 创建 Canvas 和 Scrollbar
    canvas = tk.Canvas(left_container, bg=C["BG"], highlightthickness=0, width=320)
    scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=canvas.yview)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    canvas.configure(yscrollcommand=scrollbar.set)

    # 在 Canvas 中创建内容框架
    left = ttk.Frame(canvas, width=320)
    canvas.create_window((0, 0), window=left, anchor="nw", width=320)

    def on_canvas_configure(event):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def on_frame_configure(event):
        canvas.configure(scrollregion=canvas.bbox("all"))

    left.bind("<Configure>", on_frame_configure)
    canvas.bind("<Configure>", on_canvas_configure)

    # 鼠标滚轮滚动
    def on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    canvas.bind_all("<MouseWheel>", on_mousewheel)

    # 时间
    tbox = ttk.LabelFrame(left, text=" 时间范围 ", padding=10)
    tbox.pack(fill="x", pady=(0, 8))
    tf = ttk.Frame(tbox)
    tf.pack(fill="x")
    tk.Label(tf, text="从：", width=4).pack(side="left")
    app.ent_from = ttk.Entry(tf, width=13)
    app.ent_from.insert(0, "2025-07-20")
    app.ent_from.pack(side="left")
    tk.Label(tf, text=" 至：").pack(side="left")
    app.ent_to = ttk.Entry(tf, width=13)
    app.ent_to.insert(0, "2025-08-31")
    app.ent_to.pack(side="left")

    # AOI
    abox = ttk.LabelFrame(left, text=" 研究区 AOI ", padding=10)
    abox.pack(fill="x", pady=(0, 8))
    app.aoi_var = tk.StringVar(value="海河北系全域")
    for name in AOI_PRESETS:
        rb = tk.Radiobutton(abox, text=name, variable=app.aoi_var, value=name,
                            bg=C["BG"], fg=C["FG"], selectcolor=C["BG2"],
                            activebackground=C["BG"], activeforeground=C["ACC"],
                            font=("Consolas", 9), command=lambda: _aoi_changed(app))
        rb.pack(anchor="w")
    tk.Radiobutton(abox, text="自定义 WKT", variable=app.aoi_var, value="custom",
                   bg=C["BG"], fg=C["FG"], selectcolor=C["BG2"],
                   activebackground=C["BG"], activeforeground=C["ACC"],
                   font=("Consolas", 9), command=lambda: _aoi_changed(app)).pack(anchor="w")
    app.ent_wkt = tk.Text(abox, height=3, bg=C["BG2"], fg=C["FG"],
                          font=("Consolas", 8), insertbackground=C["FG"],
                          relief="flat", wrap="word")
    app.ent_wkt.pack(fill="x", pady=(4, 0))
    _aoi_changed(app)

    # 产品参数
    pbox = ttk.LabelFrame(left, text=" 产品参数 ", padding=10)
    pbox.pack(fill="x", pady=(0, 8))

    tk.Label(pbox, text="产品类型：", font=("Consolas", 9)).pack(anchor="w")
    app.cmb_type = ttk.Combobox(pbox, values=list(PRODUCT_TYPES.keys()),
                                state="readonly", font=("Consolas", 9))
    app.cmb_type.current(0)
    app.cmb_type.pack(fill="x", pady=(2, 8))

    tk.Label(pbox, text="卫星平台：", font=("Consolas", 9)).pack(anchor="w")
    pf2 = ttk.Frame(pbox)
    pf2.pack(anchor="w", pady=(2, 8))
    app.var_s1a = tk.BooleanVar(value=True)
    app.var_s1b = tk.BooleanVar(value=True)
    app.var_s1c = tk.BooleanVar(value=True)
    ttk.Checkbutton(pf2, text="S1A", variable=app.var_s1a).pack(side="left", padx=(0, 8))
    ttk.Checkbutton(pf2, text="S1B", variable=app.var_s1b).pack(side="left", padx=(0, 8))
    ttk.Checkbutton(pf2, text="S1C", variable=app.var_s1c).pack(side="left")

    # ── 轨道方向（服务端过滤）────────────────────────────────
    tk.Label(pbox, text="轨道方向：", font=("Consolas", 9)).pack(anchor="w")
    app.cmb_orbit = ttk.Combobox(
        pbox,
        values=["不限", "升轨 ASCENDING", "降轨 DESCENDING"],
        state="readonly", font=("Consolas", 9))
    app.cmb_orbit.current(0)
    app.cmb_orbit.pack(fill="x", pady=(2, 8))

    # ── 极化方式（服务端过滤）────────────────────────────────
    tk.Label(pbox, text="极化方式：", font=("Consolas", 9)).pack(anchor="w")
    app.cmb_pol = ttk.Combobox(
        pbox,
        values=["不限", "VV&VH（双极化）", "VV（单极化）",
                "VH（单极化）", "HH&HV（双极化）", "HH（单极化）"],
        state="readonly", font=("Consolas", 9))
    app.cmb_pol.current(0)
    app.cmb_pol.pack(fill="x", pady=(2, 8))

    # ── 相对轨道号（服务端过滤，留空=不限）──────────────────
    tk.Label(pbox, text="相对轨道号（留空=不限）：", font=("Consolas", 9)).pack(anchor="w")
    app.ent_orbit_num = ttk.Entry(pbox, width=10, font=("Consolas", 9))
    app.ent_orbit_num.pack(anchor="w", pady=(2, 8))

    # ── 成像模式（服务端过滤）────────────────────────────────
    tk.Label(pbox, text="成像模式：", font=("Consolas", 9)).pack(anchor="w")
    app.cmb_mode = ttk.Combobox(
        pbox,
        values=["不限", "IW（干涉宽幅，推荐）", "EW（超宽幅）", "SM（条带）", "WV（波浪）"],
        state="readonly", font=("Consolas", 9))
    app.cmb_mode.current(0)
    app.cmb_mode.pack(fill="x", pady=(2, 8))

    # ── 绝对轨道号（服务端过滤，逗号分隔多个，留空=不限）─────
    tk.Label(pbox, text="绝对轨道号（逗号分隔，留空=不限）：", font=("Consolas", 9)).pack(anchor="w")
    app.ent_abs_orbit = ttk.Entry(pbox, width=20, font=("Consolas", 9))
    app.ent_abs_orbit.pack(anchor="w", pady=(2, 8))

    # ── 仅在线产品（服务端过滤）──────────────────────────────
    app.var_online = tk.BooleanVar(value=True)
    ttk.Checkbutton(pbox, text="仅显示在线产品（跳过归档）",
                    variable=app.var_online).pack(anchor="w", pady=(0, 8))

    tk.Label(pbox, text="最大返回数：", font=("Consolas", 9)).pack(anchor="w")
    app.cmb_max = ttk.Combobox(pbox, values=["20", "50", "100", "200"],
                               state="readonly", width=8, font=("Consolas", 9))
    app.cmb_max.set("50")
    app.cmb_max.pack(anchor="w", pady=(2, 0))

    # 搜索按钮
    bf = ttk.Frame(left)
    bf.pack(fill="x", pady=8)
    ttk.Button(bf, text="🔍  执行搜索", style="Accent.TButton",
               command=lambda: _do_search(app)).pack(fill="x")

    # 右：结果列表
    right = ttk.Frame(f)
    right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)

    # ── 名称搜索栏（官网复制文件名直接搜索）────────────────────────
    nsf = ttk.LabelFrame(right, text=" 📋 按产品名搜索（官网复制粘贴）", padding=8)
    nsf.pack(fill="x", pady=(0, 8))

    tk.Label(nsf,
             text="支持多个名称（换行或逗号分隔），带不带 .SAFE 均可",
             fg=C["DIS"], font=("Consolas", 8), bg=C["BG"]).pack(anchor="w")

    ns_row = ttk.Frame(nsf)
    ns_row.pack(fill="x", pady=(4, 0))

    app.ent_name_search = tk.Text(
        ns_row, height=3,
        bg=C["BG2"], fg=C["FG"],
        font=("Consolas", 9),
        insertbackground=C["FG"],
        relief="flat", wrap="word"
    )
    app.ent_name_search.pack(side="left", fill="x", expand=True)

    btn_col = ttk.Frame(ns_row)
    btn_col.pack(side="left", padx=(6, 0))
    ttk.Button(btn_col, text="🔍 搜索",
               style="Accent.TButton",
               command=lambda: _do_name_search(app)).pack(fill="x", pady=(0, 4))
    ttk.Button(btn_col, text="清空",
               command=lambda: app.ent_name_search.delete("1.0", "end")).pack(fill="x")

    # 结果工具栏
    rtb = ttk.Frame(right)
    rtb.pack(fill="x", pady=(0, 6))
    app.lbl_count = tk.Label(rtb, text="搜索结果：0 景", fg=C["ACC"],
                             font=("Consolas", 10, "bold"), bg=C["BG"])
    app.lbl_count.pack(side="left")
    ttk.Button(rtb, text="全选", command=lambda: _select_all(app)).pack(side="right", padx=4)
    ttk.Button(rtb, text="全不选", command=lambda: _deselect_all(app)).pack(side="right", padx=4)
    ttk.Button(rtb, text="📄 导出 CSV",
               command=lambda: _export_csv(app)).pack(side="right", padx=4)
    ttk.Button(rtb, text="+ 加入下载队列", style="Green.TButton",
               command=lambda: _add_to_queue(app)).pack(side="right", padx=(0, 8))

    # 客户端高级筛选：对已检索结果实时子串过滤，不重新请求服务器
    ftb = ttk.Frame(right)
    ftb.pack(fill="x", pady=(0, 6))
    tk.Label(ftb, text="🔎 筛选：", fg=C["DIS"], font=("Consolas", 9),
             bg=C["BG"]).pack(side="left")
    app.filter_var = tk.StringVar()
    ttk.Entry(ftb, textvariable=app.filter_var, font=("Consolas", 9)
              ).pack(side="left", fill="x", expand=True)
    tk.Label(ftb, text=" 名称/平台/模式/极化/轨道", fg=C["DIS"],
             font=("Consolas", 8), bg=C["BG"]).pack(side="left", padx=(6, 0))
    ttk.Button(ftb, text="清除",
               command=lambda: app.filter_var.set("")).pack(side="right", padx=4)
    # 输入即过滤（结果已在内存，纯客户端，无网络请求）
    app.filter_var.trace_add("write", lambda *a: render_results(app))

    # 结果 Treeview（横向可滚动）
    cols = ("sel", "name", "date", "platform", "mode", "pol", "orbit_dir",
            "rel_orbit", "abs_orbit", "size", "online")

    tree_frame = ttk.Frame(right)
    tree_frame.pack(fill="both", expand=True)

    app.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                            selectmode="extended")
    app.tree.heading("sel",       text="✓")
    app.tree.heading("name",      text="产品名称")
    app.tree.heading("date",      text="感测时间 (UTC)")
    app.tree.heading("platform",  text="平台")
    app.tree.heading("mode",      text="模式")
    app.tree.heading("pol",       text="极化")
    app.tree.heading("orbit_dir", text="轨道")
    app.tree.heading("rel_orbit", text="相对轨道号")
    app.tree.heading("abs_orbit", text="绝对轨道号")
    app.tree.heading("size",      text="大小")
    app.tree.heading("online",    text="状态")
    app.tree.column("sel",       width=30,  anchor="center", stretch=False)
    app.tree.column("name",      width=340, anchor="w",      stretch=False)
    app.tree.column("date",      width=145, anchor="center", stretch=False)
    app.tree.column("platform",  width=50,  anchor="center", stretch=False)
    app.tree.column("mode",      width=50,  anchor="center", stretch=False)
    app.tree.column("pol",       width=70,  anchor="center", stretch=False)
    app.tree.column("orbit_dir", width=55,  anchor="center", stretch=False)
    app.tree.column("rel_orbit", width=80,  anchor="center", stretch=False)
    app.tree.column("abs_orbit", width=80,  anchor="center", stretch=False)
    app.tree.column("size",      width=65,  anchor="center", stretch=False)
    app.tree.column("online",    width=65,  anchor="center", stretch=False)
    app.tree.tag_configure("even", background=C["BG2"])
    app.tree.tag_configure("odd",  background="#13181f")
    app.tree.tag_configure("sel",  background=C["SEL"])
    app.tree.bind("<Button-1>", lambda e: _tree_click(app, e))

    sb_y = ttk.Scrollbar(tree_frame, orient="vertical",   command=app.tree.yview)
    sb_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=app.tree.xview)
    app.tree.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
    sb_x.pack(side="bottom", fill="x")
    sb_y.pack(side="right",  fill="y")
    app.tree.pack(side="left", fill="both", expand=True)

    # 统计面板（表格下方一行）
    app.lbl_stats = tk.Label(right, text="", fg=C["DIS"],
                             font=("Consolas", 9), bg=C["BG"], anchor="w")
    app.lbl_stats.pack(fill="x", pady=(4, 0))

    app._selected_iids = set()   # 已勾选行


# ─────────────────────────────────────────────
#  事件回调
# ─────────────────────────────────────────────
def _aoi_changed(app):
    val = app.aoi_var.get()
    app.ent_wkt.delete("1.0", "end")
    if val in AOI_PRESETS:
        app.ent_wkt.insert("1.0", AOI_PRESETS[val])


def _tree_click(app, event):
    """点击第一列切换勾选"""
    col = app.tree.identify_column(event.x)
    iid = app.tree.identify_row(event.y)
    if not iid:
        return
    if col == "#1":
        if iid in app._selected_iids:
            app._selected_iids.discard(iid)
            app.tree.set(iid, "sel", "")
        else:
            app._selected_iids.add(iid)
            app.tree.set(iid, "sel", "✓")


def _select_all(app):
    for iid in app.tree.get_children():
        app._selected_iids.add(iid)
        app.tree.set(iid, "sel", "✓")


def _deselect_all(app):
    for iid in app.tree.get_children():
        app._selected_iids.discard(iid)
        app.tree.set(iid, "sel", "")


def _do_search(app):
    if not app.api.token:
        messagebox.showwarning("提示", "请先在「账号配置」标签页登录")
        return
    wkt = app.ent_wkt.get("1.0", "end").strip()
    if not wkt:
        messagebox.showwarning("提示", "请选择或输入研究区 WKT")
        return

    date_from    = app.ent_from.get().strip()
    date_to      = app.ent_to.get().strip()
    product_type = PRODUCT_TYPES[app.cmb_type.get()]
    max_results  = int(app.cmb_max.get())

    # 平台（客户端过滤）
    platforms = []
    if app.var_s1a.get(): platforms.append("S1A")
    if app.var_s1b.get(): platforms.append("S1B")
    if app.var_s1c.get(): platforms.append("S1C")

    # 轨道方向（服务端）
    orbit_sel = app.cmb_orbit.get()
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
    pol_sel      = app.cmb_pol.get()
    polarisation = pol_map.get(pol_sel, None)

    # 相对轨道号（服务端）
    rel_orbit_str = app.ent_orbit_num.get().strip()
    relative_orbit = int(rel_orbit_str) if rel_orbit_str.isdigit() else None

    # 仅在线（服务端）
    online_only = app.var_online.get()

    # 成像模式（服务端）
    mode_map = {
        "IW（干涉宽幅，推荐）": "IW",
        "EW（超宽幅）":        "EW",
        "SM（条带）":          "SM",
        "WV（波浪）":          "WV",
    }
    acq_mode = mode_map.get(app.cmb_mode.get(), None)

    # 绝对轨道号（服务端，逗号分隔解析为列表）
    abs_orbit_str = app.ent_abs_orbit.get().strip()
    absolute_orbit = [s.strip() for s in abs_orbit_str.split(",")
                      if s.strip().isdigit()] if abs_orbit_str else None

    app.lbl_count.config(text="搜索中...")
    app.set_status("正在搜索...")

    def _run():
        try:
            results = app.api.search(
                wkt, date_from, date_to, product_type, max_results,
                platforms=platforms,
                orbit_dir=orbit_dir,
                polarisation=polarisation,
                relative_orbit=relative_orbit,
                online_only=online_only,
                acq_mode=acq_mode,
                absolute_orbit=absolute_orbit,
            )
            app.search_results = results
            app.after(0, lambda: render_results(app))
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("搜索失败", str(e)))
            app.after(0, lambda: app.set_status(f"搜索失败: {e}"))
            app.after(0, lambda: app.lbl_count.config(text="搜索失败"))

    threading.Thread(target=_run, daemon=True).start()


def _do_name_search(app):
    """按产品名精确搜索，支持多个名称（换行或逗号分隔）"""
    if not app.api.token:
        messagebox.showwarning("提示", "请先在「账号配置」标签页登录")
        return

    raw_text = app.ent_name_search.get("1.0", "end").strip()
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

    app.lbl_count.config(text=f"正在搜索 {len(names)} 个产品名...")
    app.set_status(f"按名称搜索中，共 {len(names)} 个...")

    def _run():
        try:
            results = app.api.search(
                wkt=None, date_from=None, date_to=None,
                product_type=None,
                name_filter=names,
            )
            not_found = len(names) - len(results)
            app.search_results = results
            app.after(0, lambda: render_results(app))
            if not_found > 0:
                app.after(0, lambda: app.set_status(
                    f"搜索完成：找到 {len(results)} 景，"
                    f"未找到 {not_found} 个（名称有误或已下架）"
                ))
        except Exception as e:
            app.after(0, lambda: messagebox.showerror("搜索失败", str(e)))
            app.after(0, lambda: app.set_status(f"名称搜索失败: {e}"))
            app.after(0, lambda: app.lbl_count.config(text="搜索失败"))

    threading.Thread(target=_run, daemon=True).start()


def _product_haystack(p):
    """把 Product 的可检索字段拼成一个小写串，供客户端筛选做子串匹配。"""
    return " ".join([
        p.name, p.platform, p.mode, p.polarization,
        p.orbit_direction, p.relative_orbit, p.absolute_orbit,
        p.acquisition_time,
    ]).lower()


def _filtered_products(app):
    """按筛选框关键字过滤 app.search_results，返回当前应展示的 Product 列表。"""
    kw = app.filter_var.get().strip().lower() if hasattr(app, "filter_var") else ""
    if not kw:
        return list(app.search_results)
    return [p for p in app.search_results if kw in _product_haystack(p)]


def render_results(app):
    for iid in app.tree.get_children():
        app.tree.delete(iid)
    app._selected_iids.clear()

    # 客户端筛选后的展示集；勾选 / 加队列 / CSV 均以此为准
    displayed = _filtered_products(app)
    app._displayed = displayed

    queue_ids = {q["id"] for q in app.queue}

    # ── 统计计数器（针对当前展示集）────────────────────────────────
    stat_plat  = {}   # {"S1A": n, ...}
    stat_orbit = {}   # {"ASC": n, "DESC": n}
    stat_pol   = {}   # {"VV&VH": n, ...}
    stat_mode  = {}   # {"IW": n, ...}

    for i, p in enumerate(displayed):
        inq = " ★" if p.product_id in queue_ids else ""
        tag = "even" if i % 2 == 0 else "odd"

        app.tree.insert("", "end", iid=str(i),
                        values=("", p.name, p.acquisition_time + " UTC",
                                p.platform, p.mode, p.polarization,
                                p.orbit_direction, p.relative_orbit, p.absolute_orbit,
                                f"{p.size_gb:.1f}GB", p.online_str + inq),
                        tags=(tag,))

        # 累计统计
        stat_plat[p.platform]        = stat_plat.get(p.platform, 0) + 1
        stat_orbit[p.orbit_direction]= stat_orbit.get(p.orbit_direction, 0) + 1
        stat_pol[p.polarization]     = stat_pol.get(p.polarization, 0) + 1
        stat_mode[p.mode]            = stat_mode.get(p.mode, 0) + 1

    # ── 更新统计面板 ────────────────────────────────────────────────
    total_all   = len(app.search_results)
    total_shown = len(displayed)

    def _fmt(d):
        return "  ".join(f"{k}:{v}" for k, v in sorted(d.items()) if k != "—")

    stats_str = (
        f"共 {total_shown} 景  |  "
        f"{_fmt(stat_plat)}  |  "
        f"{_fmt(stat_orbit)}  |  "
        f"{_fmt(stat_pol)}  |  "
        f"{_fmt(stat_mode)}"
    ) if total_shown else "无结果"

    app.lbl_stats.config(text=stats_str)
    if total_shown != total_all:
        app.lbl_count.config(text=f"搜索结果：{total_shown}/{total_all} 景（已筛选）")
    else:
        app.lbl_count.config(text=f"搜索结果：{total_all} 景")
    app.set_status(f"搜索完成，共 {total_all} 景"
                   + (f"，筛选后 {total_shown} 景" if total_shown != total_all else ""))


def _add_to_queue(app):
    if not app._selected_iids:
        messagebox.showinfo("提示", "请先勾选要下载的影像（点击第一列 ✓）")
        return
    displayed = getattr(app, "_displayed", app.search_results)
    queue_ids = {q["id"] for q in app.queue}
    added = 0
    for iid in app._selected_iids:
        idx = int(iid)
        if idx >= len(displayed):
            continue
        p = displayed[idx]
        if p.product_id in queue_ids:
            continue
        app.queue.append({
            "id":     p.product_id,
            "name":   p.name,
            "size":   p.size_str,
            "status": "waiting",
        })
        added += 1
    render_queue(app)
    render_results(app)
    messagebox.showinfo("✅", f"已添加 {added} 景到下载队列")


def _export_csv(app):
    """把当前展示（筛选后）的搜索结果导出为 CSV。

    用 utf-8-sig（带 BOM），Excel 双击打开中文不乱码。
    """
    displayed = getattr(app, "_displayed", None)
    if displayed is None:
        displayed = app.search_results
    if not displayed:
        messagebox.showinfo("提示", "没有可导出的结果，请先搜索")
        return

    default_name = f"sentinel_search_{datetime.now():%Y%m%d_%H%M%S}.csv"
    path = filedialog.asksaveasfilename(
        title="导出搜索结果为 CSV",
        defaultextension=".csv",
        initialfile=default_name,
        filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
    )
    if not path:
        return

    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["产品名称", "感测时间(UTC)", "平台", "成像模式", "极化",
                        "轨道方向", "相对轨道号", "绝对轨道号", "大小(GB)", "状态", "产品ID"])
            for p in displayed:
                w.writerow([p.name, p.acquisition_time, p.platform, p.mode,
                            p.polarization, p.orbit_direction, p.relative_orbit,
                            p.absolute_orbit, f"{p.size_gb:.2f}", p.online_str,
                            p.product_id])
        app.set_status(f"已导出 {len(displayed)} 景到 {path}")
        messagebox.showinfo("✅ 导出成功", f"已导出 {len(displayed)} 景到：\n{path}")
    except Exception as e:
        messagebox.showerror("导出失败", str(e))
