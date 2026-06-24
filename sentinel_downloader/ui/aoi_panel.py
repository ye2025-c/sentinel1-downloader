#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AOI 管理面板
────────────────────────────────────────────────────────
build_aoi_section(app, parent) — 在左侧条件面板中构建"研究区 AOI"区块。

替换原 tab_search.py 中的 AOI 单选按钮 + WKT 文本框，提供：
  - 内置预设 AOI（不可删除）+ 用户自定义 AOI 的统一列表
  - 文件导入（GeoJSON / Shapefile / KML）
  - 打开地图画框窗口
  - 保存当前 WKT / 重命名 / 删除
  - app.aoi_panel_refresh 钩子，供地图窗口、下载历史等调用
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from core.aoi_manager import AoiManager
from ui.map_widget import open_map_window


def build_aoi_section(app, parent):
    """在 parent（左侧 Canvas 内的 Frame）上构建 AOI 区块，挂载到 app。"""
    C = app.colors

    abox = ttk.LabelFrame(parent, text=" 研究区 AOI ", padding=10)
    abox.pack(fill="x", pady=(0, 8))

    # ── AOI 列表 ──────────────────────────────────────────
    list_frame = ttk.Frame(abox)
    list_frame.pack(fill="x", pady=(0, 6))

    scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
    app.aoi_tree = ttk.Treeview(
        list_frame,
        show="tree",
        height=5,
        selectmode="browse",
        yscrollcommand=scrollbar.set,
    )
    app.aoi_tree.column("#0", width=260, stretch=True)
    app.aoi_tree.tag_configure("builtin", foreground=C["DIS"])
    app.aoi_tree.tag_configure("custom",  foreground=C["FG"])
    scrollbar.config(command=app.aoi_tree.yview)
    app.aoi_tree.pack(side="left", fill="x", expand=True)
    scrollbar.pack(side="right", fill="y")

    # ── 按钮行 ────────────────────────────────────────────
    btn_row1 = ttk.Frame(abox)
    btn_row1.pack(fill="x", pady=(0, 4))
    ttk.Button(btn_row1, text="📂 导入文件",
               command=lambda: _import_file(app)).pack(side="left", padx=(0, 4))
    ttk.Button(btn_row1, text="✏ 在地图上画框",
               command=lambda: _open_map(app)).pack(side="left")

    btn_row2 = ttk.Frame(abox)
    btn_row2.pack(fill="x", pady=(0, 6))
    ttk.Button(btn_row2, text="💾 保存当前WKT",
               command=lambda: _save_current_wkt(app)).pack(side="left", padx=(0, 4))
    ttk.Button(btn_row2, text="重命名",
               command=lambda: _rename_aoi(app)).pack(side="left", padx=(0, 4))
    ttk.Button(btn_row2, text="删除",
               command=lambda: _delete_aoi(app)).pack(side="left")

    # ── WKT 文本框 ────────────────────────────────────────
    ttk.Label(abox, text="WKT：", style="Hint.TLabel").pack(anchor="w")
    app.ent_wkt = tk.Text(
        abox, height=3,
        bg=C["BG2"], fg=C["FG"],
        font=(app.FONT_MONO, 8),
        insertbackground=C["FG"],
        relief="flat", wrap="word"
    )
    app.ent_wkt.pack(fill="x", pady=(2, 0))

    # ── 当前 AOI 提示标签 ─────────────────────────────────
    app.lbl_aoi_hint = ttk.Label(
        abox, text="", foreground=C["ACC"],
        font=(app.FONT_UI, 8), anchor="w", wraplength=260
    )
    app.lbl_aoi_hint.pack(fill="x", pady=(4, 0))

    dep_text = ("GeoJSON/KML 可用；Shapefile 可用"
                if AoiManager.has_gdal()
                else "GeoJSON/KML 可用；Shapefile 需要 GDAL（标准版 exe 会跳过）")
    ttk.Label(abox, text=dep_text, style="Hint.TLabel", anchor="w", wraplength=260).pack(
        fill="x", pady=(4, 0))

    # ── 内部状态 ──────────────────────────────────────────
    app._aoi_items = []      # 当前列表中的 AOI 条目（与 Listbox 行一一对应）

    # ── 注册刷新钩子 ──────────────────────────────────────
    def _refresh():
        _reload_list(app)

    app.aoi_panel_refresh = _refresh

    # ── 绑定选中事件 ──────────────────────────────────────
    app.aoi_tree.bind("<<TreeviewSelect>>", lambda e: _on_select(app))

    # 初始加载
    _reload_list(app)


# ── 内部操作 ──────────────────────────────────────────────
def _reload_list(app):
    """重新加载 AOI 列表（内置预设 + 用户自定义）。"""
    for iid in app.aoi_tree.get_children():
        app.aoi_tree.delete(iid)
    app._aoi_items = AoiManager.get_display_list()
    for i, item in enumerate(app._aoi_items):
        prefix = "  " if item.get("builtin") else "★ "
        tag = "builtin" if item.get("builtin") else "custom"
        app.aoi_tree.insert("", "end", iid=str(i),
                            text=prefix + item["name"], tags=(tag,))


def _on_select(app):
    """列表选中时将 WKT 填入文本框，更新提示标签。"""
    sel = app.aoi_tree.selection()
    if not sel:
        return
    idx = int(sel[0])
    if idx >= len(app._aoi_items):
        return
    item = app._aoi_items[idx]
    wkt  = item.get("wkt", "")

    app.ent_wkt.delete("1.0", "end")
    app.ent_wkt.insert("1.0", wkt)

    if hasattr(app, "map_panel"):
        app.map_panel.show_aoi(wkt)

    bbox = AoiManager.wkt_to_bbox(wkt)
    if bbox:
        hint = (f"{item['name']}  "
                f"[{bbox[0]:.2f}°, {bbox[1]:.2f}°] → [{bbox[2]:.2f}°, {bbox[3]:.2f}°]")
    else:
        hint = item["name"]
    app.lbl_aoi_hint.config(text=hint)


def _import_file(app):
    """导入 AOI 文件（GeoJSON / Shapefile / KML），解析后填入 WKT 并保存到库。"""
    path = filedialog.askopenfilename(
        title="导入 AOI 文件",
        filetypes=[
            ("支持的格式", "*.geojson *.json *.shp *.kml"),
            ("GeoJSON", "*.geojson *.json"),
            ("Shapefile", "*.shp"),
            ("KML", "*.kml"),
            ("所有文件", "*.*"),
        ]
    )
    if not path:
        return
    try:
        wkt, source = AoiManager.parse_file(path)
    except Exception as e:
        messagebox.showerror("导入失败", str(e))
        return

    # 提示命名
    import os
    default_name = os.path.splitext(os.path.basename(path))[0]
    name = simpledialog.askstring("保存 AOI", "为此 AOI 命名：",
                                  initialvalue=default_name)
    if not name or not name.strip():
        return

    AoiManager.add(name.strip(), wkt, source=source)

    # 填入 WKT
    app.ent_wkt.delete("1.0", "end")
    app.ent_wkt.insert("1.0", wkt)

    _reload_list(app)

    # 选中刚导入的条目（最后一条）
    children = app.aoi_tree.get_children()
    if children:
        last_iid = children[-1]
        app.aoi_tree.selection_set(last_iid)
        app.aoi_tree.see(last_iid)
        _on_select(app)

    messagebox.showinfo("✅ 导入成功", f"已导入并保存：{name.strip()}")


def _open_map(app):
    """进入地图画框模式（常驻面板）；地图未加载时降级到弹窗。"""
    if hasattr(app, "map_panel") and app.map_panel._has_map:
        app.map_panel.start_draw()
    else:
        current_wkt = app.ent_wkt.get("1.0", "end").strip()
        open_map_window(app, initial_wkt=current_wkt)


def _save_current_wkt(app):
    """将当前 WKT 文本框内容命名后存入 AOI 库。"""
    wkt = app.ent_wkt.get("1.0", "end").strip()
    if not wkt:
        messagebox.showinfo("提示", "WKT 为空，请先输入或导入坐标范围")
        return
    name = simpledialog.askstring("保存 AOI", "请输入 AOI 名称：")
    if not name or not name.strip():
        return
    AoiManager.add(name.strip(), wkt, source="manual")
    _reload_list(app)
    messagebox.showinfo("✅", f"已保存：{name.strip()}")


def _rename_aoi(app):
    sel = app.aoi_tree.selection()
    if not sel:
        messagebox.showinfo("提示", "请先选择一个 AOI")
        return
    item = app._aoi_items[int(sel[0])]
    if item.get("builtin"):
        messagebox.showinfo("提示", "内置预设不可重命名")
        return
    new_name = simpledialog.askstring("重命名", "新名称：",
                                      initialvalue=item["name"])
    if not new_name or not new_name.strip():
        return
    AoiManager.rename(item["id"], new_name.strip())
    _reload_list(app)


def _delete_aoi(app):
    sel = app.aoi_tree.selection()
    if not sel:
        messagebox.showinfo("提示", "请先选择一个 AOI")
        return
    item = app._aoi_items[int(sel[0])]
    if item.get("builtin"):
        messagebox.showinfo("提示", "内置预设不可删除")
        return
    if messagebox.askyesno("确认", f"删除 AOI「{item['name']}」？"):
        AoiManager.delete(item["id"])
        _reload_list(app)
        app.lbl_aoi_hint.config(text="")
