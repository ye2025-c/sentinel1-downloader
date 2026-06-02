#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地图预览 / 画框窗口
────────────────────────────────────────────────────────
open_map_window(app) 打开一个 Toplevel 窗口，内嵌 tkintermapview。

功能：
  - 显示当前 AOI 轮廓（蓝色高亮多边形）
  - 两次点击绘制矩形范围（不干扰地图平移/缩放）
  - 确认后将 WKT 写回 app.ent_wkt，并触发 AOI 面板刷新
  - 底图加载失败时静默降级，显示提示文字，坐标功能正常

降级策略：
  级别 1 — 正常：tkintermapview 内嵌地图 + AOI 轮廓
  级别 2 — 失败：显示"底图加载失败"文字，bbox 坐标仍可显示
"""

import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from core.aoi_manager import AoiManager


def open_map_window(app, initial_wkt: str = ""):
    """打开地图预览 / 画框 Toplevel。"""
    win = _MapWindow(app, initial_wkt)
    win.grab_set()
    win.focus_set()


class _MapWindow(tk.Toplevel):
    def __init__(self, app, initial_wkt: str = ""):
        super().__init__(app)
        self.app          = app
        self.title("地图预览 / 画框")
        self.geometry("740x560")
        self.minsize(600, 440)
        self.resizable(True, True)

        self._has_map       = False
        self._current_poly  = None   # 当前 AOI polygon 对象
        self._drawn_wkt     = ""     # 最新绘制 / 来自文件的 WKT
        self._draw_clicks   = []     # 画框时收集的两个角点
        self._drawing       = False

        self._build_ui()
        self._load_map()

        if initial_wkt:
            self._drawn_wkt = initial_wkt
            self.after(800, lambda: self._show_aoi(initial_wkt))

    # ── 界面构建 ──────────────────────────────────────────
    def _build_ui(self):
        C = self.app.colors

        # 工具栏
        tb = ttk.Frame(self)
        tb.pack(fill="x", padx=10, pady=(8, 4))

        self.btn_draw = ttk.Button(tb, text="✏ 绘制矩形",
                                   style="Accent.TButton",
                                   command=self._start_draw)
        self.btn_draw.pack(side="left")

        ttk.Button(tb, text="清除",
                   command=self._clear_draw).pack(side="left", padx=(4, 0))

        ttk.Button(tb, text="✅ 使用此 AOI",
                   style="Green.TButton",
                   command=self._apply).pack(side="right")

        ttk.Button(tb, text="保存到 AOI 库",
                   command=self._save_to_lib).pack(side="right", padx=(0, 6))

        self.status_var = tk.StringVar(value="点击「✏ 绘制矩形」在地图上框选范围")
        tk.Label(tb, textvariable=self.status_var,
                 fg=C["DIS"], font=(self.app.FONT_UI, 9),
                 bg=C["BG"]).pack(side="left", padx=10)

        # 地图区
        self.map_frame = ttk.Frame(self)
        self.map_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _load_map(self):
        """异步加载地图；失败时显示提示文字，不阻塞窗口。"""
        try:
            from tkintermapview import TkinterMapView
            self.map_widget = TkinterMapView(
                self.map_frame, width=700, height=460, corner_radius=4)
            self.map_widget.pack(fill="both", expand=True)
            self.map_widget.set_position(39.5, 116.0, marker=False)
            self.map_widget.set_zoom(7)
            self._has_map = True
        except Exception:
            self._has_map = False
            tk.Label(
                self.map_frame,
                text="底图加载失败，请检查网络连接\n\n手动输入坐标或导入文件后\n点击「使用此 AOI」仍可正常使用",
                fg=self.app.colors["DIS"],
                font=(self.app.FONT_UI, 11),
                bg=self.app.colors["BG"]
            ).pack(expand=True)

    # ── 绘制矩形（两次点击）───────────────────────────────
    def _start_draw(self):
        if not self._has_map:
            messagebox.showinfo("提示", "地图未加载，无法在地图上绘制\n请直接在搜索页面输入 WKT 坐标",
                                parent=self)
            return
        self._drawing   = True
        self._draw_clicks = []
        self._clear_draw()
        self.map_widget.add_left_click_map_command(self._on_map_click)
        self.status_var.set("请点击第一个角点（如西北角）…")
        self.btn_draw.config(state="disabled")

    def _on_map_click(self, coords):
        if not self._drawing:
            return
        lat, lon = coords
        self._draw_clicks.append((lat, lon))

        if len(self._draw_clicks) == 1:
            self.status_var.set(
                f"第一点 ({lat:.4f}°N, {lon:.4f}°E)  —  再点击对角点")
        elif len(self._draw_clicks) >= 2:
            self._finish_draw()

    def _finish_draw(self):
        self._drawing = False
        self.map_widget.add_left_click_map_command(None)
        self.btn_draw.config(state="normal")

        (lat1, lon1), (lat2, lon2) = self._draw_clicks[0], self._draw_clicks[1]
        min_lat, max_lat = min(lat1, lat2), max(lat1, lat2)
        min_lon, max_lon = min(lon1, lon2), max(lon1, lon2)

        wkt = (f"POLYGON(({min_lon:.6f} {min_lat:.6f}, "
               f"{max_lon:.6f} {min_lat:.6f}, "
               f"{max_lon:.6f} {max_lat:.6f}, "
               f"{min_lon:.6f} {max_lat:.6f}, "
               f"{min_lon:.6f} {min_lat:.6f}))")
        self._drawn_wkt = wkt
        self._show_aoi(wkt)
        self.status_var.set(
            f"矩形已绘制  [{min_lon:.4f}°, {min_lat:.4f}°] → [{max_lon:.4f}°, {max_lat:.4f}°]"
        )

    def _clear_draw(self):
        if self._has_map and self._current_poly:
            try:
                self._current_poly.delete()
            except Exception:
                pass
            self._current_poly = None

    # ── AOI 显示 ──────────────────────────────────────────
    def _show_aoi(self, wkt: str):
        if not self._has_map or not wkt:
            return
        self._clear_draw()
        positions = AoiManager.wkt_to_positions(wkt)
        if not positions:
            return
        try:
            self._current_poly = self.map_widget.set_polygon(
                position_list=positions,
                fill_color     = "",
                outline_color  = "#2288FF",
                border_width   = 3,
            )
            # 缩放到 AOI 范围
            bbox = AoiManager.wkt_to_bbox(wkt)
            if bbox:
                center_lat = (bbox[1] + bbox[3]) / 2
                center_lon = (bbox[0] + bbox[2]) / 2
                zoom = AoiManager.bbox_zoom(bbox)
                self.map_widget.set_position(center_lat, center_lon, marker=False)
                self.map_widget.set_zoom(zoom)
        except Exception:
            pass

    # ── 按钮回调 ──────────────────────────────────────────
    def _apply(self):
        """将 WKT 写回主窗口 ent_wkt，关闭地图窗口。"""
        wkt = self._drawn_wkt
        if not wkt:
            messagebox.showinfo("提示", "请先绘制矩形范围", parent=self)
            return
        self.app.ent_wkt.delete("1.0", "end")
        self.app.ent_wkt.insert("1.0", wkt)
        if callable(getattr(self.app, "aoi_panel_refresh", None)):
            self.app.aoi_panel_refresh()
        self.destroy()

    def _save_to_lib(self):
        """将当前 WKT 命名后存入 AOI 库。"""
        wkt = self._drawn_wkt
        if not wkt:
            messagebox.showinfo("提示", "请先绘制矩形范围", parent=self)
            return
        name = simpledialog.askstring("保存 AOI", "请输入 AOI 名称：", parent=self)
        if not name or not name.strip():
            return
        AoiManager.add(name.strip(), wkt, source="drawn")
        if callable(getattr(self.app, "aoi_panel_refresh", None)):
            self.app.aoi_panel_refresh()
        messagebox.showinfo("✅", f"已保存到 AOI 库：{name.strip()}", parent=self)
