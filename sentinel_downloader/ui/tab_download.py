#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载管理 Tab
────────────────────────────────────────────────────────
构建下载队列、进度区、控制按钮与日志，并提供队列渲染、增删、
并行下载调度等回调。实际下载委托 core.downloader.download。
"""

import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

from core.api import CopernicusAPI
from core.downloader import download as do_download
from core.store import HistoryStore
from core.aoi_manager import AoiManager


def build_download_tab(app):
    """在 app.tab_dl 上构建下载管理界面，绑定所有事件。"""
    C = app.colors
    f = app.tab_dl

    # 队列列表
    qf = ttk.LabelFrame(f, text=" 下载队列 ", padding=10)
    qf.pack(fill="both", expand=True, padx=12, pady=(12, 6))

    # 队列工具栏
    qtb = ttk.Frame(qf)
    qtb.pack(fill="x", pady=(0, 6))
    app.lbl_queue = tk.Label(qtb, text="队列：0 景  |  0.0 GB",
                             fg=C["ACC"], font=(app.FONT_UI, 10, "bold"), bg=C["BG"])
    app.lbl_queue.pack(side="left")
    ttk.Button(qtb, text="清空队列", command=lambda: _clear_queue(app)).pack(side="right")
    ttk.Button(qtb, text="移除选中", command=lambda: _remove_selected(app)).pack(side="right", padx=4)

    # 队列 Treeview
    qcols = ("idx", "name", "size", "status")
    app.qtree = ttk.Treeview(qf, columns=qcols, show="headings", selectmode="extended")
    app.qtree.heading("idx",    text="#")
    app.qtree.heading("name",   text="产品名称")
    app.qtree.heading("size",   text="大小")
    app.qtree.heading("status", text="状态")
    app.qtree.column("idx",    width=36,  anchor="center", stretch=False)
    app.qtree.column("name",   width=430, anchor="w")
    app.qtree.column("size",   width=70,  anchor="center")
    app.qtree.column("status", width=120, anchor="center")
    app.qtree.tag_configure("waiting",     foreground=C["DIS"])
    app.qtree.tag_configure("downloading", foreground=C["ACC"])
    app.qtree.tag_configure("done",        foreground=C["GRN"])
    app.qtree.tag_configure("error",       foreground=C["RED"])

    qsb = ttk.Scrollbar(qf, orient="vertical", command=app.qtree.yview)
    app.qtree.configure(yscrollcommand=qsb.set)
    app.qtree.pack(side="left", fill="both", expand=True)
    qsb.pack(side="right", fill="y")

    # 进度区
    pgf = ttk.Frame(f)
    pgf.pack(fill="x", padx=12, pady=(0, 6))
    app.lbl_prog = tk.Label(pgf, text="当前进度：-", fg=C["DIS"],
                            font=(app.FONT_UI, 9), bg=C["BG"])
    app.lbl_prog.pack(anchor="w")
    app.prog_bar = ttk.Progressbar(pgf, mode="determinate", length=100)
    app.prog_bar.pack(fill="x", pady=(3, 0))

    # 控制按钮
    cbf = ttk.Frame(f)
    cbf.pack(fill="x", padx=12, pady=(0, 6))
    app.btn_start = ttk.Button(cbf, text="▶  开始下载", style="Accent.TButton",
                               command=lambda: _start_download(app))
    app.btn_start.pack(side="left", padx=(0, 8))
    app.btn_stop = ttk.Button(cbf, text="⏹  停止", command=lambda: _stop_download(app),
                              state="disabled")
    app.btn_stop.pack(side="left", padx=(0, 16))

    # 并行数选择
    tk.Label(cbf, text="并行：", fg=C["DIS"], font=(app.FONT_UI, 9), bg=C["BG"]).pack(side="left")
    app.cmb_parallel = ttk.Combobox(cbf, values=["1", "2", "3", "4", "5"],
                                    state="readonly", width=3, font=(app.FONT_UI, 9))
    app.cmb_parallel.set("3")
    app.cmb_parallel.pack(side="left")
    tk.Label(cbf, text=" 景", fg=C["DIS"], font=(app.FONT_UI, 9), bg=C["BG"]).pack(side="left")

    app.lbl_speed = tk.Label(cbf, text="", fg=C["ORG"],
                             font=(app.FONT_UI, 9), bg=C["BG"])
    app.lbl_speed.pack(side="right")

    # 下载日志
    lf = ttk.LabelFrame(f, text=" 下载日志 ", padding=8)
    lf.pack(fill="x", padx=12, pady=(0, 6))
    app.dl_log = scrolledtext.ScrolledText(
        lf, height=8, bg=C["BG2"], fg=C["FG"],
        font=("Consolas", 9), insertbackground=C["FG"],
        relief="flat", state="disabled", wrap="word")
    app.dl_log.pack(fill="x")
    app.dl_log.tag_config("ok",   foreground=C["GRN"])
    app.dl_log.tag_config("err",  foreground=C["RED"])
    app.dl_log.tag_config("warn", foreground=C["ORG"])
    app.dl_log.tag_config("info", foreground=C["ACC"])
    app.dl_log.tag_config("head", foreground=C["FG"], font=("Consolas", 9, "bold"))

    # 下载历史
    hf = ttk.LabelFrame(f, text=" 下载历史 ", padding=8)
    hf.pack(fill="x", padx=12, pady=(0, 12))

    htb = ttk.Frame(hf)
    htb.pack(fill="x", pady=(0, 6))
    app.lbl_hist = tk.Label(htb, text="历史记录：0 条",
                            fg=C["DIS"], font=(app.FONT_UI, 9), bg=C["BG"])
    app.lbl_hist.pack(side="left")
    ttk.Button(htb, text="清除历史",
               command=lambda: _clear_history(app)).pack(side="right")
    ttk.Button(htb, text="存为 AOI",
               command=lambda: _save_hist_as_aoi(app)).pack(side="right", padx=(0, 6))

    hcols = ("hname", "hsize", "hstatus", "htime")
    app.htree = ttk.Treeview(hf, columns=hcols, show="headings",
                             selectmode="browse", height=4)
    app.htree.heading("hname",   text="产品名称")
    app.htree.heading("hsize",   text="大小")
    app.htree.heading("hstatus", text="状态")
    app.htree.heading("htime",   text="完成时间")
    app.htree.column("hname",   width=430, anchor="w",      stretch=True)
    app.htree.column("hsize",   width=70,  anchor="center", stretch=False)
    app.htree.column("hstatus", width=90,  anchor="center", stretch=False)
    app.htree.column("htime",   width=150, anchor="center", stretch=False)
    app.htree.tag_configure("completed", foreground=C["GRN"])
    app.htree.tag_configure("failed",    foreground=C["RED"])
    app.htree.tag_configure("downloading", foreground=C["ACC"])

    hsb = ttk.Scrollbar(hf, orient="vertical", command=app.htree.yview)
    app.htree.configure(yscrollcommand=hsb.set)
    app.htree.pack(side="left", fill="x", expand=True)
    hsb.pack(side="right", fill="y")

    app._stop_event = threading.Event()
    render_history(app)


# ─────────────────────────────────────────────
#  队列渲染与增删
# ─────────────────────────────────────────────
def render_queue(app):
    for iid in app.qtree.get_children():
        app.qtree.delete(iid)
    total_gb = 0
    for i, q in enumerate(app.queue):
        status_txt = {"waiting": "等待中", "downloading": "下载中",
                      "done": "✅ 完成", "error": "❌ 失败"}.get(q["status"], q["status"])
        app.qtree.insert("", "end", iid=str(i),
                         values=(i + 1, q["name"], q["size"], status_txt),
                         tags=(q["status"],))
        try:
            total_gb += float(q["size"].replace(" GB", ""))
        except Exception:
            pass
    app.lbl_queue.config(text=f"队列：{len(app.queue)} 景  |  {total_gb:.1f} GB")


def _clear_queue(app):
    if app.downloading:
        messagebox.showwarning("提示", "下载中，请先停止")
        return
    if app.queue and messagebox.askyesno("确认", "确定清空下载队列？"):
        app.queue.clear()
        render_queue(app)


def _remove_selected(app):
    sel = app.qtree.selection()
    if not sel:
        return
    idxs = sorted([int(s) for s in sel], reverse=True)
    for idx in idxs:
        if idx < len(app.queue):
            del app.queue[idx]
    render_queue(app)


# ─────────────────────────────────────────────
#  下载调度
# ─────────────────────────────────────────────
def _start_download(app):
    if not app.api.token:
        messagebox.showwarning("提示", "请先在「账号配置」标签页登录")
        return
    if not app.queue:
        messagebox.showinfo("提示", "下载队列为空")
        return
    save_dir = app.ent_path.get().strip()
    if not save_dir:
        messagebox.showwarning("提示", "请先在「账号配置」中设置保存路径")
        return
    if app.downloading:
        return

    app.downloading   = True
    app._stop_event   = threading.Event()
    app._stop_event.clear()
    app.btn_start.config(state="disabled")
    app.btn_stop.config(state="normal")
    app.cmb_parallel.config(state="disabled")

    # 并行汇总速度：每个槽位维护自己的 bps，主线程汇总显示
    n_workers = int(app.cmb_parallel.get())
    app._slot_speeds = [0.0] * n_workers   # 各并行槽位的实时速度
    app._slot_lock   = threading.Lock()

    def _update_total_speed():
        with app._slot_lock:
            total_bps = sum(app._slot_speeds)
        if total_bps <= 0:
            app.lbl_speed.config(text="")
        elif total_bps >= 1024 * 1024:
            app.lbl_speed.config(text=f"⚡ {total_bps/1024/1024:.1f} MB/s")
        else:
            app.lbl_speed.config(text=f"⚡ {total_bps/1024:.0f} KB/s")

    def _make_speed_cb(slot_idx):
        def _speed(bps):
            with app._slot_lock:
                app._slot_speeds[slot_idx] = max(bps, 0)
            app.after(0, _update_total_speed)
        return _speed

    def _run():
        import concurrent.futures
        u = app.ent_user.get().strip()
        p = app.ent_pass.get().strip()
        pending = [q for q in app.queue if q["status"] != "done"]
        total   = len(pending)
        ok_cnt  = 0
        lock    = threading.Lock()

        app._dlog(f"═══ 开始下载 {total} 景（并行 {n_workers} 景）═══", "head")
        app._dlog(f"保存路径: {save_dir}", "info")

        # 初始化进度标签
        app.after(0, lambda: app.lbl_prog.config(
            text=f"准备下载，共 {total} 景...",
            fg=app.colors["DIS"]
        ))
        app.after(0, lambda: app.prog_bar.config(value=0))

        # 所有 worker 共享同一个 api 实例（已内置线程锁），不再各自建实例
        # 避免各实例独立刷新 token 时发生竞争覆盖
        shared_api = CopernicusAPI()
        shared_api.token      = app.api.token
        shared_api.token_time = app.api.token_time

        def _download_one(args):
            slot_idx, q = args
            if app._stop_event.is_set():
                return False

            name = q["name"]
            app._dlog(f"  ↓ [{name[:40]}] 开始", "head")

            HistoryStore.add(q["id"], name, q.get("size", ""), save_dir,
                             footprint=q.get("footprint", ""))
            q["status"] = "downloading"
            app.after(0, lambda: render_queue(app))

            def _prog(pct):
                # 只让 slot_idx == 0 的 worker 更新进度条，避免多线程互相覆盖
                if slot_idx % n_workers != 0:
                    return
                short = name[:30]
                label = (f"第 {slot_idx+1}/{total} 景（并行 {n_workers} 景）：{short}  {pct:.0f}%"
                         if n_workers > 1 else
                         f"第 {slot_idx+1}/{total} 景：{short}  {pct:.0f}%")
                app.after(0, lambda p=pct, lb=label: (
                    app.prog_bar.config(value=p),
                    app.lbl_prog.config(text=lb, fg=app.colors["ACC"])
                ))

            ok, _ = do_download(
                shared_api, q["id"], name, save_dir, u, p,
                log_cb=lambda m, t="info": app._dlog(f"  [{name[:20]}] {m}", t),
                prog_cb=_prog,
                speed_cb=_make_speed_cb(slot_idx % n_workers),
                stop_event=app._stop_event,
            )
            with lock:
                nonlocal ok_cnt
                if ok:
                    ok_cnt += 1
            q["status"] = "done" if ok else "error"
            HistoryStore.update_status(q["id"], "completed" if ok else "failed")
            app.after(0, lambda: render_queue(app))
            app.after(0, lambda: render_history(app))

            # 景完成：进度条推到100%，标签更新，短暂停留后清零等待下一景
            done = sum(1 for qq in pending if qq["status"] in ("done", "error"))
            status_icon = "✅" if ok else "❌"
            finish_label = f"{status_icon} 第 {done}/{total} 景完成：{name[:30]}"

            def _on_one_done(d=done, fl=finish_label):
                if slot_idx % n_workers == 0:
                    app.prog_bar.config(value=100)
                app.lbl_prog.config(text=fl,
                                    fg=app.colors["GRN"] if ok else app.colors["RED"])

            app.after(0, _on_one_done)
            app.after(0, lambda n=name, ok=ok:
                app._dlog(f"  {'✅' if ok else '❌'} [{n[:40]}] {'完成' if ok else '失败'}",
                          "ok" if ok else "err"))

            # 如果还有后续景，延迟300ms后将进度条清零，视觉上有"刷新感"
            if done < total:
                def _reset_bar():
                    app.prog_bar.config(value=0)
                    app.lbl_prog.config(text=f"等待下一景... ({done}/{total})",
                                        fg=app.colors["DIS"])
                app.after(300, _reset_bar)

            return ok

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as executor:
            list(executor.map(_download_one, enumerate(pending)))

        # 清零所有槽位速度
        with app._slot_lock:
            app._slot_speeds = [0.0] * n_workers
        app.after(0, _update_total_speed)

        app._dlog(f"\n═══ 完成！成功 {ok_cnt}/{total} 景 ═══", "head")

        def _on_done():
            app.prog_bar.config(value=0)
            app.lbl_prog.config(text=f"完成！成功 {ok_cnt}/{total} 景")
            app.btn_start.config(state="normal")
            app.btn_stop.config(state="disabled")
            app.cmb_parallel.config(state="readonly")
            app.downloading = False

        app.after(0, _on_done)

    threading.Thread(target=_run, daemon=True).start()


def _stop_download(app):
    app._stop_event.set()
    app.set_status("正在停止...")
    app.btn_stop.config(state="disabled")   # 防止重复点击


# ─────────────────────────────────────────────
#  下载历史
# ─────────────────────────────────────────────
def render_history(app):
    """刷新历史面板显示。"""
    for iid in app.htree.get_children():
        app.htree.delete(iid)
    records = HistoryStore.get_all()
    for i, r in enumerate(records):
        status_txt = {"completed": "✅ 完成", "failed": "❌ 失败",
                      "downloading": "⏳ 下载中"}.get(r.get("status", ""), r.get("status", ""))
        finished = r.get("finished_at") or r.get("started_at", "")
        if finished:
            finished = finished.replace("T", " ")
        app.htree.insert("", "end", iid=str(i),
                         values=(r.get("product_name", ""), r.get("size", ""),
                                 status_txt, finished),
                         tags=(r.get("status", ""),))
    app.lbl_hist.config(text=f"历史记录：{len(records)} 条")


def _clear_history(app):
    if messagebox.askyesno("确认", "确定清除所有下载历史？"):
        HistoryStore.clear()
        render_history(app)


def _save_hist_as_aoi(app):
    """将选中历史记录的 footprint 存入 AOI 库。"""
    from tkinter import simpledialog
    sel = app.htree.selection()
    if not sel:
        messagebox.showinfo("提示", "请先在历史列表中选中一条记录")
        return
    idx     = int(sel[0])
    records = HistoryStore.get_all()
    if idx >= len(records):
        return
    record   = records[idx]
    footprint = record.get("footprint", "")
    if not footprint:
        messagebox.showinfo("提示", "该记录没有 footprint 数据（需重新下载后才能获取）")
        return
    default = record.get("product_name", "")[:20]
    name = simpledialog.askstring("存为 AOI", "请输入 AOI 名称：",
                                  initialvalue=default)
    if not name or not name.strip():
        return
    AoiManager.add(name.strip(), footprint, source="history")
    if callable(getattr(app, "aoi_panel_refresh", None)):
        app.aoi_panel_refresh()
    messagebox.showinfo("✅", f"已保存到 AOI 库：{name.strip()}")
