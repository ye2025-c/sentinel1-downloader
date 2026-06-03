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
from core.earthdata import verify_credentials


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

    # NASA Earthdata 账号框（供「NASA 下载」标签页使用）
    edbox = ttk.LabelFrame(f, text=" NASA Earthdata 账号 ", padding=14)
    edbox.pack(fill="x", padx=18, pady=(0, 8))

    er = 0
    tk.Label(edbox, text="用户名：").grid(row=er, column=0, sticky="e", **pad)
    app.ent_eduser = ttk.Entry(edbox, width=40)
    app.ent_eduser.grid(row=er, column=1, sticky="ew", **pad)

    er += 1
    tk.Label(edbox, text="密码：").grid(row=er, column=0, sticky="e", **pad)
    app.ent_edpass = ttk.Entry(edbox, width=40, show="●")
    app.ent_edpass.grid(row=er, column=1, sticky="ew", **pad)

    er += 1
    tk.Label(edbox,
             text="注册：urs.earthdata.nasa.gov（免费）；凭据在首次下载时校验，"
                  "若返回 HTML 登录页即为账号密码错误。",
             fg=C["DIS"], font=(app.FONT_UI, 8), wraplength=520,
             anchor="w", justify="left").grid(row=er, column=0, columnspan=2,
                                              sticky="ew", padx=16, pady=(0, 2))
    edbox.columnconfigure(1, weight=1)

    # 按钮
    bf = ttk.Frame(f)
    bf.pack(fill="x", padx=18, pady=4)
    ttk.Button(bf, text="🔐  测试登录", style="Accent.TButton",
               command=lambda: _test_login(app)).pack(side="left", padx=(0, 8))
    ttk.Button(bf, text="💾  保存配置",
               command=lambda: _save_config(app)).pack(side="left")

    # 提示：两个数据源工作流不同，分组说明，避免混淆
    hint = ttk.LabelFrame(f, text=" 使用说明 ", padding=14)
    hint.pack(fill="x", padx=18, pady=(14, 0))
    groups = [
        ("【Sentinel · Copernicus】界面内检索 + 下载", [
            "① 注册账号：dataspace.copernicus.eu（免费，S1/S2 同一账号）",
            "② 填写 Copernicus 账号 → 测试登录 → 保存配置",
            "③「搜索影像」标签 → 设置时间 / AOI / 参数 → 搜索",
            "④ 勾选影像 → 加入队列 →「下载管理」→ 开始下载",
        ]),
        ("【NASA Earthdata】官网检索，软件只负责批量下载", [
            "① 注册账号：urs.earthdata.nasa.gov（免费）",
            "② 填写 Earthdata 账号 → 测试登录",
            "③ 在 NASA 官网（如 Earthdata Search）勾选数据 → 导出 .txt 下载链接列表",
            "④「NASA 下载」标签 → 导入并解析 .txt → 设置保存目录 → 开始下载",
        ]),
    ]
    for title, steps in groups:
        tk.Label(hint, text=title, fg=C["ACC"], font=(app.FONT_UI, 9, "bold"),
                 anchor="w").pack(fill="x", pady=(4, 1))
        for s in steps:
            tk.Label(hint, text="    " + s, fg=C["DIS"], font=(app.FONT_UI, 9),
                     anchor="w").pack(fill="x", pady=1)
    tk.Label(hint,
             text="※ 两者均支持断点续传，中断后重开自动续传；建议全局 VPN 提升访问速度。",
             fg=C["DIS"], font=(app.FONT_UI, 8), wraplength=560,
             anchor="w", justify="left").pack(fill="x", pady=(6, 0))

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
    """测试登录：填了哪个验证哪个，两个都填则都验证。

    - Copernicus：调 get_token 获取 Token（顶栏状态随之更新）。
    - NASA Earthdata：HTTP Basic 校验（不依赖 Copernicus，可单独验证）。
    """
    cu = app.ent_user.get().strip()
    cp = app.ent_pass.get().strip()
    eu = app.ent_eduser.get().strip()
    ep = app.ent_edpass.get().strip()

    has_cdse = bool(cu and cp)
    has_nasa = bool(eu and ep)
    if not has_cdse and not has_nasa:
        messagebox.showwarning("提示", "请至少填写一个账号（Copernicus 或 NASA Earthdata）")
        return

    def L(msg, tag="info"):
        app.after(0, lambda: app._log(app.auth_log, msg, tag))

    def _run():
        # ── Copernicus（CDSE）：获取 Token ──
        if has_cdse:
            L("正在验证 Copernicus 账号（获取 Token）...", "info")
            try:
                app.api.get_token(cu, cp)
                L("✅ Copernicus 登录成功！Token 已获取", "ok")
                app.after(0, lambda: app.lbl_token.config(
                    text="CDSE ● 已登录", fg=app.colors["GRN"]))
            except Exception as e:
                L(f"❌ Copernicus 登录失败: {e}", "err")
                app.after(0, lambda: app.lbl_token.config(
                    text="CDSE ● 登录失败", fg=app.colors["RED"]))

        # ── NASA Earthdata：Basic 认证校验（独立于 Copernicus）──
        if has_nasa:
            L("正在验证 NASA Earthdata 账号...", "info")
            ok, msg = verify_credentials(eu, ep)
            if ok is True:
                L(f"✅ Earthdata 验证成功：{msg}", "ok")
                app.after(0, lambda: app.lbl_token_nasa.config(
                    text="NASA ● 已验证", fg=app.colors["GRN"]))
            elif ok is False:
                L(f"❌ Earthdata 验证失败：{msg}", "err")
                app.after(0, lambda: app.lbl_token_nasa.config(
                    text="NASA ● 验证失败", fg=app.colors["RED"]))
            else:
                L(f"⚠️ Earthdata {msg}", "warn")
                app.after(0, lambda: app.lbl_token_nasa.config(
                    text="NASA ● 未确认", fg=app.colors["ORG"]))

        app.after(0, lambda: app.set_status("登录测试完成"))

    threading.Thread(target=_run, daemon=True).start()


def _save_config(app):
    # 合并写：先读出整份配置再更新这些键，保留 settings / nasa_proc 等其它子字典
    # （早期版本这里整体覆盖，会把设置页与裁剪配置一并冲掉）
    cfg = load_config() or {}
    cfg.update({
        "username":  app.ent_user.get(),
        "save_path": app.ent_path.get(),
        "date_from": app.ent_from.get(),
        "date_to":   app.ent_to.get(),
        # NASA Earthdata（用户名与保存目录持久化；密码同 CDSE 不落盘）
        "earthdata_username": app.ent_eduser.get(),
        "nasa_save_path": getattr(app, "ent_nasa_path", None).get()
                          if hasattr(app, "ent_nasa_path") else "",
    })
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
    if hasattr(app, "ent_eduser"):
        app.ent_eduser.insert(0, cfg.get("earthdata_username", ""))
    if hasattr(app, "ent_nasa_path"):
        app.ent_nasa_path.insert(0, cfg.get("nasa_save_path", ""))
    if cfg.get("date_from"):
        app.ent_from.delete(0, "end")
        app.ent_from.insert(0, cfg["date_from"])
    if cfg.get("date_to"):
        app.ent_to.delete(0, "end")
        app.ent_to.insert(0, cfg["date_to"])
