#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账号配置 Tab
────────────────────────────────────────────────────────
构建「账号配置」界面，并提供登录测试、配置读写、路径浏览等回调。
配置读写委托 core.config，UI 层不直接操作文件。
"""

import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

from core.config import save_config, load_config


def build_auth_tab(app):
    """在 app.tab_auth 上构建账号配置界面，绑定所有事件。"""
    C = app.colors
    f = app.tab_auth
    pad = dict(padx=16, pady=6)

    # 账号框
    box = ttk.LabelFrame(f, text=" Copernicus 账号 ", padding=14)
    box.pack(fill="x", padx=18, pady=(18, 8))

    r = 0
    tk.Label(box, text="邮箱：").grid(row=r, column=0, sticky="e", **pad)
    app.ent_user = ttk.Entry(box, width=40)
    app.ent_user.grid(row=r, column=1, sticky="ew", **pad)

    r += 1
    tk.Label(box, text="密码：").grid(row=r, column=0, sticky="e", **pad)
    app.ent_pass = ttk.Entry(box, width=40, show="●")
    app.ent_pass.grid(row=r, column=1, sticky="ew", **pad)

    r += 1
    tk.Label(box, text="保存路径：").grid(row=r, column=0, sticky="e", **pad)
    pf = ttk.Frame(box)
    pf.grid(row=r, column=1, sticky="ew", **pad)
    app.ent_path = ttk.Entry(pf, width=32)
    app.ent_path.pack(side="left", fill="x", expand=True)
    ttk.Button(pf, text="浏览", command=lambda: _browse_path(app)).pack(side="left", padx=(6, 0))

    box.columnconfigure(1, weight=1)

    # 按钮
    bf = ttk.Frame(f)
    bf.pack(fill="x", padx=18, pady=4)
    ttk.Button(bf, text="🔐  测试登录", style="Accent.TButton",
               command=lambda: _test_login(app)).pack(side="left", padx=(0, 8))
    ttk.Button(bf, text="💾  保存配置",
               command=lambda: _save_config(app)).pack(side="left")

    # 提示
    hint = ttk.LabelFrame(f, text=" 使用说明 ", padding=14)
    hint.pack(fill="x", padx=18, pady=(14, 0))
    hints = [
        "① 注册账号：dataspace.copernicus.eu  （免费注册）",
        "② 填写账号 → 测试登录 → 保存配置",
        "③ 切换「搜索影像」标签 → 设置条件 → 搜索",
        "④ 勾选影像 → 加入队列 → 切换「下载管理」→ 开始下载",
        "⑤ 脚本支持断点续传，中断后重新运行自动续传",
        "⑥ 建议使用全局VPN，提升访问 ESA 服务器速度",
    ]
    for h in hints:
        tk.Label(hint, text=h, fg=C["DIS"], font=(app.FONT_UI, 9),
                 anchor="w").pack(fill="x", pady=1)

    # 登录日志
    app.auth_log = scrolledtext.ScrolledText(
        f, height=7, bg=C["BG2"], fg=C["FG"],
        font=("Consolas", 9), insertbackground=C["FG"],
        relief="flat", state="disabled", wrap="word")
    app.auth_log.pack(fill="x", padx=18, pady=(12, 0))
    app.auth_log.tag_config("ok",   foreground=C["GRN"])
    app.auth_log.tag_config("err",  foreground=C["RED"])
    app.auth_log.tag_config("warn", foreground=C["ORG"])
    app.auth_log.tag_config("info", foreground=C["ACC"])


# ─────────────────────────────────────────────
#  事件回调
# ─────────────────────────────────────────────
def _browse_path(app):
    d = filedialog.askdirectory()
    if d:
        app.ent_path.delete(0, "end")
        app.ent_path.insert(0, d)


def _test_login(app):
    u = app.ent_user.get().strip()
    p = app.ent_pass.get().strip()
    if not u or not p:
        messagebox.showwarning("提示", "请先填写账号和密码")
        return
    app._log(app.auth_log, "正在获取 Token...", "info")

    def _run():
        try:
            app.api.get_token(u, p)
            app.after(0, lambda: app._log(app.auth_log, "✅ 登录成功！Token 已获取", "ok"))
            app.after(0, lambda: app.lbl_token.config(
                text="● 已登录", fg=app.colors["GRN"]))
            app.after(0, lambda: app.set_status("登录成功"))
        except Exception as e:
            app.after(0, lambda: app._log(app.auth_log, f"❌ 登录失败: {e}", "err"))
            app.after(0, lambda: app.lbl_token.config(
                text="● 登录失败", fg=app.colors["RED"]))
            app.after(0, lambda: app.set_status("登录失败"))

    threading.Thread(target=_run, daemon=True).start()


def _save_config(app):
    cfg = {
        "username":  app.ent_user.get(),
        "save_path": app.ent_path.get(),
        "date_from": app.ent_from.get(),
        "date_to":   app.ent_to.get(),
    }
    try:
        save_config(cfg)
        app._log(app.auth_log, "✅ 配置已保存", "ok")
    except Exception as e:
        app._log(app.auth_log, f"❌ 保存失败: {e}", "err")


def load_config_into_ui(app):
    """读取配置文件并填充各 Entry 控件（在所有 Tab 构建完成后调用）。"""
    cfg = load_config()
    if not cfg:
        return
    app.ent_user.insert(0, cfg.get("username", ""))
    app.ent_path.insert(0, cfg.get("save_path", ""))
    if cfg.get("date_from"):
        app.ent_from.delete(0, "end")
        app.ent_from.insert(0, cfg["date_from"])
    if cfg.get("date_to"):
        app.ent_to.delete(0, "end")
        app.ent_to.insert(0, cfg["date_to"])
