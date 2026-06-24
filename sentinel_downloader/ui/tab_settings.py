#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置 Tab（V4.1）
────────────────────────────────────────────────────────
把原先散落 / 写死的可调参数（并行数、重试、超时、缓存 TTL、日志保留
天数等）收进一个集中入口。读写委托 core.config 的 get_settings /
save_settings，统一存在 data/config.json 的 "settings" 子字典；缺键自动
回退 core.config._DEFAULT_SETTINGS，老配置无缝兼容。

设置项的"生效时机"是惰性的——下次操作时由各消费方读取（并行数在
开始下载时读、TTL 在缓存写入时读），无需热重载。保存时顺手把并行数 /
NASA 间隔同步回对应下拉框，让当前界面也立即反映。
"""

import tkinter as tk
from tkinter import ttk, messagebox

from core.config import get_settings, save_settings, _DEFAULT_SETTINGS


def build_settings_tab(app):
    """在 app.tab_settings 上构建设置界面，绑定保存 / 恢复默认事件。"""
    f = app.tab_settings
    cur = get_settings()

    # 各设置项对应的输入变量，保存时统一读取
    app._set_vars = {
        "parallel":         tk.StringVar(value=str(cur["parallel"])),
        "max_retry":        tk.StringVar(value=str(cur["max_retry"])),
        "connect_timeout":  tk.StringVar(value=str(cur["connect_timeout"])),
        "read_timeout":     tk.StringVar(value=str(cur["read_timeout"])),
        "nasa_delay":       tk.StringVar(value=str(cur["nasa_delay"])),
        "cache_ttl_hours":  tk.StringVar(value=str(cur["cache_ttl_hours"])),
        "log_keep_days":    tk.StringVar(value=str(cur["log_keep_days"])),
        "verify_integrity": tk.BooleanVar(value=bool(cur["verify_integrity"])),
    }
    V = app._set_vars
    pad = dict(padx=14, pady=6)

    def _row(parent, r, label, widget, hint=""):
        ttk.Label(parent, text=label, font=(app.FONT_UI, 9)).grid(
            row=r, column=0, sticky="e", **pad)
        widget.grid(row=r, column=1, sticky="w", **pad)
        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
                row=r, column=2, sticky="w", padx=(0, 8))
        parent.columnconfigure(2, weight=1)

    # ── 下载设置 ──────────────────────────────────────────
    dbox = ttk.LabelFrame(f, text=" 下载设置 ", padding=12)
    dbox.pack(fill="x", padx=18, pady=(18, 8))
    _row(dbox, 0, "默认并行数：",
         ttk.Combobox(dbox, textvariable=V["parallel"], values=["1", "2", "3", "4", "5"],
                      state="readonly", width=6, font=(app.FONT_UI, 9)),
         "同时下载的景数（CDSE）")
    _row(dbox, 1, "单文件最大重试：",
         ttk.Spinbox(dbox, textvariable=V["max_retry"], from_=1, to=10,
                     width=6, font=(app.FONT_UI, 9)),
         "失败后退避续传的最大次数")
    _row(dbox, 2, "连接超时(秒)：",
         ttk.Spinbox(dbox, textvariable=V["connect_timeout"], from_=5, to=60,
                     width=6, font=(app.FONT_UI, 9)),
         "建立连接的最长等待")
    _row(dbox, 3, "读取超时(秒)：",
         ttk.Spinbox(dbox, textvariable=V["read_timeout"], from_=30, to=600,
                     width=6, font=(app.FONT_UI, 9)),
         "两次数据块之间的最长空闲")
    ttk.Checkbutton(dbox, text="下载完成后做 ZIP 结构校验（推荐）",
                    variable=V["verify_integrity"]).grid(
        row=4, column=0, columnspan=3, sticky="w", padx=14, pady=(2, 4))

    # ── NASA 设置 ─────────────────────────────────────────
    nbox = ttk.LabelFrame(f, text=" NASA 下载 ", padding=12)
    nbox.pack(fill="x", padx=18, pady=(0, 8))
    _row(nbox, 0, "文件间隔(秒)：",
         ttk.Combobox(nbox, textvariable=V["nasa_delay"], values=["0", "1", "2", "3", "5"],
                      state="readonly", width=6, font=(app.FONT_UI, 9)),
         "串行下载时文件之间的礼貌延迟")

    # ── 缓存与日志 ────────────────────────────────────────
    cbox = ttk.LabelFrame(f, text=" 缓存与日志 ", padding=12)
    cbox.pack(fill="x", padx=18, pady=(0, 8))
    _row(cbox, 0, "搜索缓存有效期(小时)：",
         ttk.Spinbox(cbox, textvariable=V["cache_ttl_hours"], from_=1, to=720,
                     width=6, font=(app.FONT_UI, 9)),
         "重复搜索命中缓存的时长")
    _row(cbox, 1, "日志保留天数：",
         ttk.Spinbox(cbox, textvariable=V["log_keep_days"], from_=0, to=365,
                     width=6, font=(app.FONT_UI, 9)),
         "启动时清理超期日志，0=不清理")

    # ── 按钮 ──────────────────────────────────────────────
    bf = ttk.Frame(f)
    bf.pack(fill="x", padx=18, pady=8)
    ttk.Button(bf, text="💾  保存设置", style="Accent.TButton",
               command=lambda: _save(app)).pack(side="left", padx=(0, 8))
    ttk.Button(bf, text="↺  恢复默认",
               command=lambda: _restore_defaults(app)).pack(side="left")

    ttk.Label(f, text="※ 设置下次操作时生效（并行数 / NASA 间隔保存后立即同步到对应下拉框）。",
             style="Hint.TLabel", anchor="w").pack(fill="x", padx=20, pady=(2, 0))


# ─────────────────────────────────────────────
#  事件回调
# ─────────────────────────────────────────────
def _collect(app):
    """从控件读取并校验设置，返回规范化后的 dict（失败抛 ValueError）。"""
    V = app._set_vars
    out = {}
    int_keys = ("parallel", "max_retry", "connect_timeout",
                "read_timeout", "nasa_delay", "cache_ttl_hours", "log_keep_days")
    for k in int_keys:
        raw = str(V[k].get()).strip()
        try:
            out[k] = int(float(raw))
        except (ValueError, TypeError):
            raise ValueError(f"「{k}」需要填整数（当前：{raw}）")
    out["verify_integrity"] = bool(V["verify_integrity"].get())
    # 简单下限保护，避免填 0 / 负数把功能卡死
    out["parallel"]        = max(1, min(out["parallel"], 5))
    out["max_retry"]       = max(1, out["max_retry"])
    out["connect_timeout"] = max(1, out["connect_timeout"])
    out["read_timeout"]    = max(5, out["read_timeout"])
    out["nasa_delay"]      = max(0, out["nasa_delay"])
    out["cache_ttl_hours"] = max(1, out["cache_ttl_hours"])
    out["log_keep_days"]   = max(0, out["log_keep_days"])
    return out


def _apply_live(app, s):
    """把保存后的设置同步到当前界面控件（并行数 / NASA 间隔下拉框）。"""
    if hasattr(app, "cmb_parallel") and not getattr(app, "downloading", False):
        app.cmb_parallel.set(str(s["parallel"]))
    if hasattr(app, "cmb_nasa_delay") and not getattr(app, "nasa_downloading", False):
        app.cmb_nasa_delay.set(str(s["nasa_delay"]))


def _save(app):
    try:
        s = _collect(app)
    except ValueError as e:
        messagebox.showwarning("设置无效", str(e))
        return
    save_settings(s)
    _apply_live(app, s)
    app.set_status("设置已保存")
    messagebox.showinfo("✅", "设置已保存，下次操作生效。")


def _restore_defaults(app):
    if not messagebox.askyesno("确认", "恢复所有设置为默认值？"):
        return
    V = app._set_vars
    for k, v in _DEFAULT_SETTINGS.items():
        if k == "verify_integrity":
            V[k].set(bool(v))
        else:
            V[k].set(str(v))
    save_settings(dict(_DEFAULT_SETTINGS))
    _apply_live(app, _DEFAULT_SETTINGS)
    app.set_status("已恢复默认设置")
