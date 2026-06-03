#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NASA 下载 Tab
────────────────────────────────────────────────────────
NASA Earthdata 没有检索接口，工作流是「官网导出 .txt URL 列表 → 批量下载」。
本 Tab 提供：导入 URL 列表 → 解析展示 → 串行批量下载（断点续传 / 重试 /
原子落盘）。认证使用「账号配置」里填写的 Earthdata 账号密码。

下载内核为独立的 core/earthdata.py，与 CDSE 的 core/downloader.py 解耦。
串行 + 文件间礼貌延迟，沿用历史脚本的稳妥节奏（NASA 服务器对并发不友好）。
"""

import os
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from core.config import (
    log_line, save_config, get_setting, get_nasa_proc, save_nasa_proc,
)
from core.earthdata import (
    EarthdataSession, parse_url_list, filename_from_url,
    preauth, download_one,
)
from core.aoi_manager import AoiManager
from core.nc_processor import (
    ProcessConfig, crop_file, is_available as nc_available, output_path_for,
)


def build_nasa_tab(app):
    """在 app.tab_nasa 上构建 NASA Earthdata 批量下载界面，绑定所有事件。"""
    C = app.colors
    f = app.tab_nasa

    # ── 内部状态 ──────────────────────────────────────────
    app.nasa_items       = []                  # [{url, name, status}]
    app.nasa_downloading = False
    app._nasa_stop       = threading.Event()

    # ── 顶部：URL 列表 / 保存目录 / 间隔 ───────────────────
    cfgbox = ttk.LabelFrame(f, text=" 下载配置 ", padding=12)
    cfgbox.pack(fill="x", padx=12, pady=(12, 6))

    # URL 列表文件
    row1 = ttk.Frame(cfgbox)
    row1.pack(fill="x", pady=(0, 6))
    tk.Label(row1, text="URL 列表(.txt)：", fg=C["FG"],
             font=(app.FONT_UI, 9), bg=C["BG"]).pack(side="left")
    app.ent_nasa_txt = ttk.Entry(row1)
    app.ent_nasa_txt.pack(side="left", fill="x", expand=True, padx=(6, 6))
    ttk.Button(row1, text="浏览", width=6,
               command=lambda: _browse_txt(app)).pack(side="left", padx=(0, 4))
    ttk.Button(row1, text="解析", width=6,
               command=lambda: _parse_txt(app)).pack(side="left")

    # 保存目录
    row2 = ttk.Frame(cfgbox)
    row2.pack(fill="x", pady=(0, 6))
    tk.Label(row2, text="保存目录：    ", fg=C["FG"],
             font=(app.FONT_UI, 9), bg=C["BG"]).pack(side="left")
    app.ent_nasa_path = ttk.Entry(row2)
    app.ent_nasa_path.pack(side="left", fill="x", expand=True, padx=(6, 6))
    ttk.Button(row2, text="浏览", width=6,
               command=lambda: _browse_dir(app)).pack(side="left")

    # 礼貌间隔
    row3 = ttk.Frame(cfgbox)
    row3.pack(fill="x")
    tk.Label(row3, text="文件间隔：", fg=C["DIS"],
             font=(app.FONT_UI, 9), bg=C["BG"]).pack(side="left")
    app.cmb_nasa_delay = ttk.Combobox(row3, values=["0", "1", "2", "3", "5"],
                                      state="readonly", width=3,
                                      font=(app.FONT_UI, 9))
    app.cmb_nasa_delay.set(str(get_setting("nasa_delay")))
    app.cmb_nasa_delay.pack(side="left")
    tk.Label(row3, text=" 秒（避免请求过密）", fg=C["DIS"],
             font=(app.FONT_UI, 9), bg=C["BG"]).pack(side="left")

    # ── 下载后裁剪（按研究区瘦身）─────────────────────────
    # 注意：减小的是「本地占用」，不是网络下载流量——直连文件按 HTTP 整文件
    # 下载，没法服务端按 bbox 子集。这里是下完整文件后本地裁掉研究区以外。
    _build_crop_panel(app, f, C)

    # ── 文件列表 ──────────────────────────────────────────
    lf = ttk.LabelFrame(f, text=" 文件列表 ", padding=10)
    lf.pack(fill="both", expand=True, padx=12, pady=(0, 6))

    ltb = ttk.Frame(lf)
    ltb.pack(fill="x", pady=(0, 6))
    app.lbl_nasa_count = tk.Label(ltb, text="待下载：0 个",
                                  fg=C["ACC"], font=(app.FONT_UI, 10, "bold"), bg=C["BG"])
    app.lbl_nasa_count.pack(side="left")
    ttk.Button(ltb, text="清空", command=lambda: _clear_list(app)).pack(side="right")
    ttk.Button(ltb, text="删除所选", command=lambda: _delete_selected(app)).pack(
        side="right", padx=(0, 6))

    ncols = ("idx", "name", "status")
    app.ntree = ttk.Treeview(lf, columns=ncols, show="headings", selectmode="extended")
    app.ntree.heading("idx",    text="#")
    app.ntree.heading("name",   text="文件名")
    app.ntree.heading("status", text="状态")
    app.ntree.column("idx",    width=44,  anchor="center", stretch=False)
    app.ntree.column("name",   width=520, anchor="w")
    app.ntree.column("status", width=110, anchor="center", stretch=False)
    app.ntree.tag_configure("waiting",     foreground=C["DIS"])
    app.ntree.tag_configure("downloading", foreground=C["ACC"])
    app.ntree.tag_configure("done",        foreground=C["GRN"])
    app.ntree.tag_configure("error",       foreground=C["RED"])

    nsb = ttk.Scrollbar(lf, orient="vertical", command=app.ntree.yview)
    app.ntree.configure(yscrollcommand=nsb.set)
    app.ntree.pack(side="left", fill="both", expand=True)
    nsb.pack(side="right", fill="y")
    # 选中后按 Delete 键也可移除
    app.ntree.bind("<Delete>", lambda e: _delete_selected(app))

    # ── 进度区 ────────────────────────────────────────────
    pgf = ttk.Frame(f)
    pgf.pack(fill="x", padx=12, pady=(0, 6))
    app.lbl_nasa_prog = tk.Label(pgf, text="当前进度：-", fg=C["DIS"],
                                 font=(app.FONT_UI, 9), bg=C["BG"])
    app.lbl_nasa_prog.pack(anchor="w")
    app.nasa_prog = ttk.Progressbar(pgf, mode="determinate", length=100)
    app.nasa_prog.pack(fill="x", pady=(3, 0))

    # ── 控制按钮 ──────────────────────────────────────────
    cbf = ttk.Frame(f)
    cbf.pack(fill="x", padx=12, pady=(0, 6))
    app.btn_nasa_start = ttk.Button(cbf, text="▶  开始下载", style="Accent.TButton",
                                    command=lambda: _start(app))
    app.btn_nasa_start.pack(side="left", padx=(0, 8))
    app.btn_nasa_stop = ttk.Button(cbf, text="⏹  停止", state="disabled",
                                   command=lambda: _stop(app))
    app.btn_nasa_stop.pack(side="left")
    app.lbl_nasa_speed = tk.Label(cbf, text="", fg=C["ORG"],
                                  font=(app.FONT_UI, 9), bg=C["BG"])
    app.lbl_nasa_speed.pack(side="right")

    # ── 下载日志 ──────────────────────────────────────────
    logf = ttk.LabelFrame(f, text=" 下载日志 ", padding=8)
    logf.pack(fill="x", padx=12, pady=(0, 12))
    app.nasa_log = scrolledtext.ScrolledText(
        logf, height=8, bg=C["BG2"], fg=C["FG"],
        font=("Consolas", 9), insertbackground=C["FG"],
        relief="flat", state="disabled", wrap="word")
    app.nasa_log.pack(fill="x")
    app.nasa_log.tag_config("ok",   foreground=C["GRN"])
    app.nasa_log.tag_config("err",  foreground=C["RED"])
    app.nasa_log.tag_config("warn", foreground=C["ORG"])
    app.nasa_log.tag_config("info", foreground=C["ACC"])
    app.nasa_log.tag_config("head", foreground=C["FG"], font=("Consolas", 9, "bold"))


# ─────────────────────────────────────────────
#  下载后裁剪面板（按研究区经纬度瘦身）
# ─────────────────────────────────────────────
def _build_crop_panel(app, f, C):
    """构建「下载后裁剪」面板，状态存入 app.var_crop_* 并从 config 回填。"""
    proc = get_nasa_proc()
    bb = proc["bbox"]
    app.var_crop_enabled = tk.BooleanVar(value=proc["enabled"])
    app.var_crop_del     = tk.BooleanVar(value=proc["delete_original"])
    app.var_crop_s = tk.StringVar(value=f"{bb['lat_min']:g}")   # 南纬 lat_min
    app.var_crop_n = tk.StringVar(value=f"{bb['lat_max']:g}")   # 北纬 lat_max
    app.var_crop_w = tk.StringVar(value=f"{bb['lon_min']:g}")   # 西经 lon_min
    app.var_crop_e = tk.StringVar(value=f"{bb['lon_max']:g}")   # 东经 lon_max

    box = ttk.LabelFrame(f, text=" 下载后裁剪（按研究区瘦身，减小本地占用） ", padding=12)
    box.pack(fill="x", padx=12, pady=(0, 6))

    # 第一行：启用开关
    r0 = ttk.Frame(box)
    r0.pack(fill="x", pady=(0, 6))
    ttk.Checkbutton(r0, text="启用：下载后裁掉研究区以外数据（netCDF swath，如 OMPS/S5P）",
                    variable=app.var_crop_enabled).pack(side="left")

    # 第二行：研究区 bbox 四个输入 + 从 AOI 预设填入
    r1 = ttk.Frame(box)
    r1.pack(fill="x", pady=(0, 6))

    def _coord(parent, label, var):
        tk.Label(parent, text=label, fg=C["FG"], font=(app.FONT_UI, 9),
                 bg=C["BG"]).pack(side="left")
        ttk.Entry(parent, textvariable=var, width=7).pack(side="left", padx=(2, 10))

    _coord(r1, "南纬", app.var_crop_s)
    _coord(r1, "北纬", app.var_crop_n)
    _coord(r1, "西经", app.var_crop_w)
    _coord(r1, "东经", app.var_crop_e)

    tk.Label(r1, text="从AOI填入：", fg=C["DIS"], font=(app.FONT_UI, 9),
             bg=C["BG"]).pack(side="left", padx=(8, 0))
    names = [it["name"] for it in AoiManager.get_display_list()]
    app.cmb_crop_aoi = ttk.Combobox(r1, values=names, state="readonly",
                                    width=14, font=(app.FONT_UI, 9))
    app.cmb_crop_aoi.pack(side="left")
    app.cmb_crop_aoi.bind("<<ComboboxSelected>>", lambda e: _fill_bbox_from_aoi(app))

    # 第三行：删除原始 + 依赖缺失提示
    r2 = ttk.Frame(box)
    r2.pack(fill="x")
    ttk.Checkbutton(r2, text="裁剪成功后删除原始大文件（仅保留瘦身版）",
                    variable=app.var_crop_del).pack(side="left")
    if not nc_available():
        tk.Label(r2, text="  ⚠ 未安装 netCDF4/h5py，裁剪将自动跳过（不影响下载）",
                 fg=C["ORG"], font=(app.FONT_UI, 8), bg=C["BG"]).pack(side="left")


def _fill_bbox_from_aoi(app):
    """从选中的 AOI 预设/库项的 WKT 计算外接矩形，填入四个 bbox 输入框。"""
    name = app.cmb_crop_aoi.get()
    item = next((it for it in AoiManager.get_display_list() if it["name"] == name), None)
    if not item:
        return
    bbox = AoiManager.wkt_to_bbox(item.get("wkt", ""))   # [min_lon,min_lat,max_lon,max_lat]
    if not bbox:
        return
    app.var_crop_w.set(f"{bbox[0]:g}")
    app.var_crop_s.set(f"{bbox[1]:g}")
    app.var_crop_e.set(f"{bbox[2]:g}")
    app.var_crop_n.set(f"{bbox[3]:g}")


def _collect_crop_cfg(app):
    """读裁剪面板，返回 (ProcessConfig, bbox_valid)。bbox 非法时 enabled 置否。"""
    enabled = bool(app.var_crop_enabled.get())
    try:
        bbox = {
            "lat_min": float(app.var_crop_s.get()), "lat_max": float(app.var_crop_n.get()),
            "lon_min": float(app.var_crop_w.get()), "lon_max": float(app.var_crop_e.get()),
        }
        # 容错：用户把 min/max 填反了自动纠正
        if bbox["lat_min"] > bbox["lat_max"]:
            bbox["lat_min"], bbox["lat_max"] = bbox["lat_max"], bbox["lat_min"]
        if bbox["lon_min"] > bbox["lon_max"]:
            bbox["lon_min"], bbox["lon_max"] = bbox["lon_max"], bbox["lon_min"]
        bbox_valid = True
    except (ValueError, TypeError):
        bbox, bbox_valid = {}, False
    cfg = ProcessConfig(enabled=enabled and bbox_valid, bbox=bbox,
                        delete_original=bool(app.var_crop_del.get()))
    return cfg, bbox_valid


# ─────────────────────────────────────────────
#  日志辅助
# ─────────────────────────────────────────────
def _nlog(app, msg, tag="info"):
    """写入 NASA 下载日志（并持久化到 data/logs/）。"""
    log_line(msg)
    app._log(app.nasa_log, msg, tag)


# ─────────────────────────────────────────────
#  列表导入 / 渲染 / 清空
# ─────────────────────────────────────────────
def _browse_txt(app):
    path = filedialog.askopenfilename(
        title="选择 NASA 导出的 URL 列表",
        filetypes=[("文本列表", "*.txt"), ("所有文件", "*.*")])
    if path:
        app.ent_nasa_txt.delete(0, "end")
        app.ent_nasa_txt.insert(0, path)
        _parse_txt(app)


def _browse_dir(app):
    d = filedialog.askdirectory(title="选择保存目录")
    if d:
        app.ent_nasa_path.delete(0, "end")
        app.ent_nasa_path.insert(0, d)


def _parse_txt(app):
    """解析 URL 列表文件，填充文件列表。"""
    path = app.ent_nasa_txt.get().strip()
    if not path:
        messagebox.showinfo("提示", "请先选择 URL 列表文件(.txt)")
        return
    if not os.path.exists(path):
        messagebox.showerror("错误", f"找不到文件：\n{path}")
        return
    try:
        urls = parse_url_list(path)
    except Exception as e:
        messagebox.showerror("解析失败", str(e))
        return
    if not urls:
        messagebox.showinfo("提示", "列表为空（没有有效 URL）")
        return

    app.nasa_items = [{"url": u, "name": filename_from_url(u), "status": "waiting"}
                      for u in urls]
    render_list(app)
    _nlog(app, f"已解析 {len(urls)} 个 URL：{os.path.basename(path)}", "head")


def render_list(app):
    """刷新文件列表 Treeview。"""
    for iid in app.ntree.get_children():
        app.ntree.delete(iid)
    waiting = 0
    for i, it in enumerate(app.nasa_items):
        status_txt = {"waiting": "等待中", "downloading": "下载中",
                      "done": "✅ 完成", "error": "❌ 失败"}.get(it["status"], it["status"])
        app.ntree.insert("", "end", iid=str(i),
                         values=(i + 1, it["name"], status_txt),
                         tags=(it["status"],))
        if it["status"] != "done":
            waiting += 1
    done = sum(1 for it in app.nasa_items if it["status"] == "done")
    app.lbl_nasa_count.config(
        text=f"共 {len(app.nasa_items)} 个  |  待下载 {waiting}  |  已完成 {done}")


def _clear_list(app):
    if app.nasa_downloading:
        messagebox.showwarning("提示", "下载中，请先停止")
        return
    if app.nasa_items and messagebox.askyesno("确认", "确定清空文件列表？"):
        app.nasa_items = []
        render_list(app)


def _delete_selected(app):
    """从列表移除选中的项（支持多选 / Delete 键）。下载中需先停止。"""
    if app.nasa_downloading:
        messagebox.showwarning("提示", "下载中，请先停止再删除")
        return
    sel = app.ntree.selection()
    if not sel:
        messagebox.showinfo("提示", "请先在列表中选择要删除的项（可按住 Ctrl/Shift 多选）")
        return
    # 渲染时 iid 即 nasa_items 的下标；按下标剔除后重渲染
    drop = {int(iid) for iid in sel}
    app.nasa_items = [it for i, it in enumerate(app.nasa_items) if i not in drop]
    render_list(app)
    _nlog(app, f"已从列表移除 {len(drop)} 项", "info")


# ─────────────────────────────────────────────
#  下载调度（串行 + 礼貌间隔）
# ─────────────────────────────────────────────
def _start(app):
    eduser = app.ent_eduser.get().strip()
    edpass = app.ent_edpass.get().strip()
    if not eduser or not edpass:
        messagebox.showwarning("提示", "请先在「账号配置」填写 NASA Earthdata 账号和密码")
        return
    if not app.nasa_items:
        messagebox.showinfo("提示", "文件列表为空，请先导入并解析 URL 列表")
        return
    save_dir = app.ent_nasa_path.get().strip()
    if not save_dir:
        messagebox.showwarning("提示", "请先设置保存目录")
        return
    if app.nasa_downloading:
        return

    # 收集「下载后裁剪」配置并校验
    proc_cfg, bbox_valid = _collect_crop_cfg(app)
    if app.var_crop_enabled.get() and not bbox_valid:
        messagebox.showwarning("提示", "已启用下载后裁剪，但研究区经纬度填写无效，请检查四个数值")
        return
    # 记住裁剪配置（启用 / bbox / 删原始），下次自动带出
    try:
        save_nasa_proc({
            "enabled":         bool(app.var_crop_enabled.get()),
            "delete_original": bool(app.var_crop_del.get()),
            **({"bbox": proc_cfg.bbox} if bbox_valid else {}),
        })
    except Exception:
        pass

    # 记住本次保存目录，下次自动带出
    try:
        from core.config import load_config
        cfg = load_config()
        cfg["nasa_save_path"] = save_dir
        save_config(cfg)
    except Exception:
        pass

    app.nasa_downloading = True
    app._nasa_stop = threading.Event()
    app.btn_nasa_start.config(state="disabled")
    app.btn_nasa_stop.config(state="normal")
    app.cmb_nasa_delay.config(state="disabled")

    delay = int(app.cmb_nasa_delay.get())

    def _speed_cb(bps):
        def _do():
            if bps <= 0:
                app.lbl_nasa_speed.config(text="")
            elif bps >= 1024 * 1024:
                app.lbl_nasa_speed.config(text=f"⚡ {bps/1024/1024:.1f} MB/s")
            else:
                app.lbl_nasa_speed.config(text=f"⚡ {bps/1024:.0f} KB/s")
        app.after(0, _do)

    def _run():
        pending = [it for it in app.nasa_items if it["status"] != "done"]
        total   = len(pending)
        ok_cnt  = 0

        _nlog(app, f"═══ 开始下载 {total} 个文件（串行，间隔 {delay}s）═══", "head")
        _nlog(app, f"保存目录: {save_dir}", "info")
        if proc_cfg.enabled:
            b = proc_cfg.bbox
            if not nc_available():
                _nlog(app, "⚠️ 已启用下载后裁剪，但未安装 netCDF4 → 本次跳过裁剪（仅下载）", "warn")
            else:
                _nlog(app, f"✂️ 下载后裁剪已启用：研究区 纬[{b['lat_min']:g},{b['lat_max']:g}] "
                           f"经[{b['lon_min']:g},{b['lon_max']:g}]"
                           f"{'，裁剪后删原始' if proc_cfg.delete_original else ''}", "info")
        app.after(0, lambda: app.lbl_nasa_prog.config(
            text=f"准备下载，共 {total} 个...", fg=app.colors["DIS"]))
        app.after(0, lambda: app.nasa_prog.config(value=0))

        # 预认证：先访问 Earthdata Login 拿初始 Cookies
        session = EarthdataSession(eduser, edpass)
        _nlog(app, "正在连接 Earthdata Login...", "info")
        ok_auth, _ = preauth(session, verify_ssl=False,
                             log_cb=lambda m, t="info": _nlog(app, m, t))
        if not ok_auth:
            _finish(app, 0, total, aborted=True)
            return

        for i, it in enumerate(pending, 1):
            if app._nasa_stop.is_set():
                break

            # 启用裁剪时：瘦身版已在磁盘上 → 该 URL 已处理完，直接跳过。
            # 解决"删原始后原始名不在、重新导入 txt 会重复下载整文件"的问题。
            if proc_cfg.enabled and nc_available():
                out_p = output_path_for(os.path.join(save_dir, it["name"]), proc_cfg)
                if os.path.exists(out_p):
                    it["status"] = "done"
                    ok_cnt += 1
                    _nlog(app, f"  ⏭ [{i}/{total}] 瘦身版已存在，跳过：{it['name']}", "ok")
                    app.after(0, lambda: render_list(app))
                    continue

            it["status"] = "downloading"
            app.after(0, lambda: render_list(app))
            _nlog(app, f"  ↓ [{i}/{total}] {it['name']}", "head")

            def _prog(pct, idx=i, nm=it["name"]):
                label = f"第 {idx}/{total} 个：{nm[:36]}  {pct:.0f}%"
                app.after(0, lambda p=pct, lb=label: (
                    app.nasa_prog.config(value=p),
                    app.lbl_nasa_prog.config(text=lb, fg=app.colors["ACC"])))

            success, save_path = download_one(
                session, it["url"], save_dir,
                log_cb=lambda m, t="info": _nlog(app, m, t),
                prog_cb=_prog,
                speed_cb=_speed_cb,
                stop_event=app._nasa_stop,
            )
            it["status"] = "done" if success else "error"
            if success:
                ok_cnt += 1
                # 下载后裁剪（瘦身）——独立于下载内核，异常不影响下载结果
                if proc_cfg.enabled and save_path and nc_available():
                    try:
                        crop_file(save_path, proc_cfg,
                                  log_cb=lambda m, t="info": _nlog(app, m, t))
                    except Exception as e:
                        _nlog(app, f"  ⚠️ 裁剪异常（已跳过，原始保留）：{e}", "warn")
            app.after(0, lambda: render_list(app))

            done = sum(1 for x in pending if x["status"] in ("done", "error"))
            icon = "✅" if success else "❌"
            app.after(0, lambda d=done, ic=icon, nm=it["name"], s=success:
                      app.lbl_nasa_prog.config(
                          text=f"{ic} 第 {d}/{total} 个：{nm[:30]}",
                          fg=app.colors["GRN"] if s else app.colors["RED"]))

            if app._nasa_stop.is_set():
                break
            if i < total and delay > 0:
                time.sleep(delay)   # 文件之间的礼貌性延迟

        aborted = app._nasa_stop.is_set()
        _finish(app, ok_cnt, total, aborted=aborted)

    threading.Thread(target=_run, daemon=True).start()


def _finish(app, ok_cnt, total, aborted=False):
    """收尾：恢复按钮状态、汇总日志。"""
    tag = "warn" if aborted else "head"
    head = "⏹ 已停止" if aborted else "完成"
    _nlog(app, f"\n═══ {head}！成功 {ok_cnt}/{total} 个 ═══", tag)

    def _on_done():
        app.nasa_prog.config(value=0)
        app.lbl_nasa_prog.config(
            text=f"{head}！成功 {ok_cnt}/{total} 个",
            fg=app.colors["DIS"])
        app.lbl_nasa_speed.config(text="")
        app.btn_nasa_start.config(state="normal")
        app.btn_nasa_stop.config(state="disabled")
        app.cmb_nasa_delay.config(state="readonly")
        app.nasa_downloading = False

    app.after(0, _on_done)


def _stop(app):
    app._nasa_stop.set()
    app.set_status("正在停止 NASA 下载...")
    app.btn_nasa_stop.config(state="disabled")   # 防止重复点击
